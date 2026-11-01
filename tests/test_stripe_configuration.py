from dataclasses import replace
from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from fastapi.testclient import TestClient

import server
from tests.test_email_system import settings


@pytest.mark.parametrize("prefix", ["sk_test_", "rk_test_"])
def test_test_secret_and_restricted_keys_are_accepted(prefix):
    config = settings(email_enabled=False, stripe_secret_key=prefix + "synthetic_fixture")
    config.validate()
    assert config.stripe_test_mode is True


@pytest.mark.parametrize("prefix", ["sk_live_", "rk_live_", "invalid_"])
def test_non_test_keys_cannot_start_staging(prefix):
    config = settings(email_enabled=False, stripe_secret_key=prefix + "synthetic_fixture")
    with pytest.raises(RuntimeError, match="live Stripe key"):
        config.validate()


@pytest.mark.parametrize("livemode", [True, None])
def test_test_checkout_rejects_live_or_unspecified_webhook_before_database(monkeypatch, livemode):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_secret_key="rk_test_synthetic_fixture", stripe_webhook_secret="synthetic_signing_fixture"))
    monkeypatch.setattr(server.stripe.Webhook, "construct_event", lambda *args: server.stripe.Event.construct_from({"livemode": livemode}, None))
    database = AsyncMock()
    monkeypatch.setattr(server.db, "select", database)
    response = TestClient(server.app).post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "synthetic"})
    assert response.status_code == 400
    database.assert_not_called()


def test_test_webhook_is_processed_and_duplicate_remains_idempotent(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_secret_key="rk_test_synthetic_fixture", stripe_webhook_secret="synthetic_signing_fixture"))
    monkeypatch.setattr(server.stripe.Webhook, "construct_event", lambda *args: server.stripe.Event.construct_from({"id": "evt_synthetic", "livemode": False}, None))
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{"status": "completed"}]))
    response = TestClient(server.app).post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "synthetic"})
    assert response.json() == {"received": True, "duplicate": True}


SIGNING_SECRET = "whsec_synthetic_fixture_not_a_credential"


def signed_payload(event, secret=SIGNING_SECRET):
    payload = json.dumps(event).encode()
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={timestamp},v1={digest}"}


def configure_signed_webhook(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings,
        stripe_secret_key="rk_test_synthetic_fixture", stripe_webhook_secret=SIGNING_SECRET))


def test_real_sdk_signed_fixture_without_order_is_acknowledged_once(monkeypatch):
    configure_signed_webhook(monkeypatch)
    select = AsyncMock(side_effect=[[], [{"status": "completed"}]])
    insert, update, rpc, email = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, "select", select)
    monkeypatch.setattr(server.db, "insert", insert)
    monkeypatch.setattr(server.db, "update", update)
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server, "_send_order_email", email)
    payload, headers = signed_payload({"id": "evt_sdk_synthetic", "object": "event", "livemode": False,
        "type": "checkout.session.completed", "data": {"object": {"id": "cs_test_synthetic",
        "object": "checkout.session", "payment_status": "paid", "metadata": {}}}})
    client = TestClient(server.app)
    assert client.post("/api/stripe/webhook", content=payload, headers=headers).json() == {"received": True}
    assert client.post("/api/stripe/webhook", content=payload, headers=headers).json() == {"received": True, "duplicate": True}
    insert.assert_awaited_once()
    update.assert_awaited_once()
    assert update.call_args.args[1]["status"] == "completed"
    rpc.assert_not_called()
    email.assert_not_called()


@pytest.mark.parametrize("event_type", ["checkout.session.completed", "checkout.session.async_payment_succeeded"])
def test_real_sdk_recursively_converts_paid_checkout_data(monkeypatch, event_type):
    configure_signed_webhook(monkeypatch)
    order_id = "10000000-0000-4000-8000-000000000009"
    expected = {"id": order_id, "stripe_session_id": "cs_test_synthetic", "total_cents": 4900,
        "currency": "EUR", "customer_email": "fixture@example.com"}
    monkeypatch.setattr(server.db, "select", AsyncMock(side_effect=[[], [expected], [{"user_id": None}]]))
    monkeypatch.setattr(server.db, "insert", AsyncMock())
    monkeypatch.setattr(server.db, "update", AsyncMock())
    rpc, email = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server, "_send_order_email", email)
    payload, headers = signed_payload({"id": "evt_sdk_paid", "object": "event", "livemode": False,
        "type": event_type, "data": {"object": {"id": "cs_test_synthetic", "object": "checkout.session",
        "payment_status": "paid", "amount_total": 4900, "currency": "eur", "client_reference_id": order_id,
        "payment_intent": "pi_synthetic", "metadata": {"order_id": order_id},
        "customer_details": {"email": "fixture@example.com", "name": "Client test", "phone": "+33123456789", "address": {"country": "FR"}},
        "collected_information": {"shipping_details": {"address": {"country": "FR", "city": "Paris"}}}}}})
    response = TestClient(server.app).post("/api/stripe/webhook", content=payload, headers=headers)
    assert response.status_code == 200
    rpc.assert_awaited_once()
    assert rpc.call_args.args[0] == "complete_paid_order"
    assert rpc.call_args.args[1]["p_order_id"] == order_id
    assert rpc.call_args.args[1]["p_shipping_address"]["city"] == "Paris"
    assert rpc.call_args.args[1]["p_billing_address"]["country"] == "FR"
    assert email.await_args_list == [call("order_confirmation", order_id), call("payment_confirmed", order_id)]
    assert any(call.args[0] == "orders" and call.args[1].get("customer_phone") == "+33123456789" for call in server.db.update.call_args_list)


def test_checkout_uses_database_cents_and_separate_shipping(monkeypatch):
    create = AsyncMock(return_value=SimpleNamespace(id="cs_test_fixture", url="https://checkout.stripe.com/test"))
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
    monkeypatch.setattr(server, "settings", replace(server.settings, shipping_rate_cents=1500, free_shipping_threshold_cents=35000, shipping_countries=("FR",), public_test_checkout_enabled=True))
    monkeypatch.setattr(server, "_cart_for", AsyncMock(return_value={"id": "cart_fixture"}))
    monkeypatch.setattr(server, "_cart_response", AsyncMock(return_value={"currency": "EUR", "items": [{
        "id": "product_fixture", "slug": "fixture", "sku": "FIX", "name": "Test", "quantity": 2,
        "status": "active", "stock": 5, "price": 0.01, "price_cents": 1999, "currency": "EUR", "images": [],
        "selected_vehicle": {"brand_slug":"bmw", "compatibility_status":"compatible", "compatibility_reason":"Display-only label"},
        "compatible_brands": ["bmw"],
    }]}))
    monkeypatch.setattr(server.db, "insert", AsyncMock(side_effect=[[{"id": "order_fixture", "order_number": "TY-TEST"}], []]))
    monkeypatch.setattr(server.db, "update", AsyncMock())
    server.checkout_attempts.clear()
    response = TestClient(server.app).post("/api/create-checkout-session", headers={"X-Session-Id": "guest_fixture_qa"}, json={"price": 1})
    assert response.status_code == 200
    params = create.call_args.kwargs["params"]
    assert params["line_items"][0]["price_data"]["unit_amount"] == 1999
    assert params["line_items"][1]["price_data"]["unit_amount"] == 1500
    assert params["line_items"][1]["price_data"]["product_data"]["name"] == "Livraison suivie"
    assert params["shipping_address_collection"]["allowed_countries"] == ["FR"]
    assert params["phone_number_collection"]["enabled"] is True
    assert params["billing_address_collection"] == "required"
    assert "payment_method_types" not in params
    assert server.db.insert.call_args_list[0].args[1]['requires_compatibility_review'] is True


def test_unlinked_checkout_session_is_expired_and_never_returned(monkeypatch):
    create = AsyncMock(return_value=SimpleNamespace(id="cs_test_unlinked", url="https://checkout.stripe.com/test"))
    expire = AsyncMock()
    sessions = SimpleNamespace(create_async=create, expire_async=expire)
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))))
    monkeypatch.setattr(server, "settings", replace(server.settings, public_test_checkout_enabled=True))
    monkeypatch.setattr(server, "_cart_for", AsyncMock(return_value={"id": "cart_fixture"}))
    monkeypatch.setattr(server, "_cart_response", AsyncMock(return_value={"currency": "EUR", "items": [{
        "id": "product_fixture", "slug": "fixture", "sku": "FIX", "name": "Test", "quantity": 1,
        "status": "active", "stock": 5, "price": 19.99, "price_cents": 1999, "currency": "EUR", "images": [],
        "selected_vehicle": {"brand_slug": "bmw"}, "compatible_brands": ["bmw"],
    }]}))
    monkeypatch.setattr(server.db, "insert", AsyncMock(side_effect=[[{"id": "order_fixture", "order_number": "TY-TEST"}], []]))
    monkeypatch.setattr(server.db, "update", AsyncMock(side_effect=[[], [{"id": "order_fixture"}]]))
    server.checkout_attempts.clear()
    response = TestClient(server.app).post("/api/create-checkout-session", headers={"X-Session-Id": "guest_unlinked_qa"})
    assert response.status_code == 503
    assert "checkout.stripe.com" not in response.text
    expire.assert_awaited_once_with("cs_test_unlinked")
    assert server.db.update.call_args_list[-1].args[1] == {"status": "payment_failed", "payment_status": "failed"}


def test_order_email_uses_public_tracking_for_guest_and_account_for_member(monkeypatch):
    order = {"id": "order_fixture", "order_number": "TY-20261101-ABC12345", "customer_email": "guest@example.test",
             "total_cents": 1999, "currency": "EUR", "user_id": None}
    monkeypatch.setattr(server.db, "select", AsyncMock(side_effect=[[order], []]))
    send = AsyncMock()
    monkeypatch.setattr(server.email_service, "send", send)
    asyncio.run(server._send_order_email("order_confirmation", order["id"]))
    assert "/support/track?order=TY-20261101-ABC12345" in send.call_args.kwargs["content"].text
    assert "/account/orders/" not in send.call_args.kwargs["content"].text
    order["user_id"] = "user_fixture"
    monkeypatch.setattr(server.db, "select", AsyncMock(side_effect=[[order], []]))
    asyncio.run(server._send_order_email("order_confirmation", order["id"]))
    assert "/account/orders/order_fixture" in send.call_args.kwargs["content"].text


def test_live_checkout_reserves_atomically_and_reuses_open_session(monkeypatch):
    create = AsyncMock(return_value=SimpleNamespace(id="cs_live_fixture", url="https://checkout.stripe.com/live"))
    retrieve = AsyncMock(return_value=SimpleNamespace(id="cs_live_fixture", status="open", url="https://checkout.stripe.com/live"))
    sessions = SimpleNamespace(create_async=create, retrieve_async=retrieve)
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))))
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_mode="live", environment="production",
        stripe_secret_key="sk_live_synthetic_fixture", shipping_countries=("FR",)))
    monkeypatch.setattr(server, "legal_ready", lambda: True)
    monkeypatch.setattr(server, "check_compatibility", lambda *_: {"status": "compatible", "reason": "fixture"})
    monkeypatch.setattr(server, "_cart_for", AsyncMock(return_value={"id": "cart_fixture"}))
    monkeypatch.setattr(server, "_cart_response", AsyncMock(return_value={"currency": "EUR", "items": [{
        "id": "product_fixture", "slug": "fixture", "sku": "FIX", "name": "Test", "quantity": 1,
        "status": "active", "stock": 5, "price": 19.99, "price_cents": 1999, "currency": "EUR", "images": [],
        "selected_vehicle": {"brand_slug": "bmw"},
    }]}))
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{
        "supplier_name": "Verified supplier", "supplier_reference": "EXACT-1", "cost_price_cents": 500,
        "shipping_cost_cents": 200, "supplier_verified": True,
    }]))
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    rpc = AsyncMock(side_effect=[
        {"order_id": "10000000-0000-4000-8000-000000000009", "order_number": "TY-LIVE-1",
         "discount_cents": 0, "stripe_session_id": None, "expires_at": future, "reused": False},
        {"order_id": "10000000-0000-4000-8000-000000000009", "order_number": "TY-LIVE-1",
         "discount_cents": 0, "stripe_session_id": "cs_live_fixture", "expires_at": future, "reused": True},
    ])
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server.db, "insert", AsyncMock())
    monkeypatch.setattr(server.db, "update", AsyncMock(return_value=[{"id": "10000000-0000-4000-8000-000000000009"}]))
    server.checkout_attempts.clear()
    client = TestClient(server.app)
    first = client.post("/api/create-checkout-session", headers={"X-Session-Id": "guest_live_fixture"})
    second = client.post("/api/create-checkout-session", headers={"X-Session-Id": "guest_live_fixture"})
    assert first.status_code == second.status_code == 200
    assert first.json()["url"] == second.json()["url"]
    assert create.await_count == retrieve.await_count == 1
    server.db.insert.assert_not_called()
    assert rpc.await_args_list[0].args[0] == "create_reserved_checkout_order"


def test_live_expired_checkout_releases_reserved_stock(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_mode="live", environment="production",
        stripe_secret_key="sk_live_synthetic_fixture", stripe_webhook_secret=SIGNING_SECRET))
    monkeypatch.setattr(server.db, "select", AsyncMock(side_effect=[[], [{"stripe_session_id": "cs_live_fixture", "is_test": False}]]))
    monkeypatch.setattr(server.db, "insert", AsyncMock())
    monkeypatch.setattr(server.db, "update", AsyncMock())
    rpc = AsyncMock(return_value=True)
    monkeypatch.setattr(server.db, "rpc", rpc)
    order_id = "10000000-0000-4000-8000-000000000009"
    payload, headers = signed_payload({"id": "evt_live_expired", "object": "event", "livemode": True,
        "type": "checkout.session.expired", "data": {"object": {"id": "cs_live_fixture",
        "metadata": {"order_id": order_id}}}})
    response = TestClient(server.app).post("/api/stripe/webhook", content=payload, headers=headers)
    assert response.status_code == 200
    rpc.assert_awaited_once_with("release_checkout_stock", {"p_order_id": order_id, "p_reason": "stripe_expired"})


def test_failed_payment_intent_keeps_checkout_stock_reserved(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_mode="live", environment="production",
        stripe_secret_key="sk_live_synthetic_fixture", stripe_webhook_secret=SIGNING_SECRET))
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[]))
    monkeypatch.setattr(server.db, "insert", AsyncMock())
    update, rpc = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, "update", update)
    monkeypatch.setattr(server.db, "rpc", rpc)
    payload, headers = signed_payload({"id": "evt_live_failed_card", "object": "event", "livemode": True,
        "type": "payment_intent.payment_failed", "data": {"object": {"metadata": {"order_id": "fixture"}}}})
    response = TestClient(server.app).post("/api/stripe/webhook", content=payload, headers=headers)
    assert response.status_code == 200
    rpc.assert_not_called()
    assert all(call.args[0] == "stripe_events" for call in update.call_args_list)


def test_reconciliation_releases_only_stripe_expired_reservation(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_mode="live", environment="production",
        stripe_secret_key="sk_live_synthetic_fixture"))
    retrieve = AsyncMock(return_value=SimpleNamespace(status="expired", payment_status="unpaid"))
    sessions = SimpleNamespace(retrieve_async=retrieve, expire_async=AsyncMock())
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))))
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{"id": "order_fixture", "stripe_session_id": "cs_live_expired"}]))
    rpc, update = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server.db, "update", update)
    assert asyncio.run(server._reconcile_expired_checkouts()) == 1
    rpc.assert_awaited_once_with("release_checkout_stock", {"p_order_id": "order_fixture", "p_reason": "stripe_expired"})
    assert update.call_args.args[1]["payment_status"] == "failed"


def test_reconciliation_completes_paid_session_without_releasing_stock(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_mode="live", environment="production",
        stripe_secret_key="sk_live_synthetic_fixture"))
    session = SimpleNamespace(status="complete", payment_status="paid", to_dict=lambda: {"id": "cs_live_paid"})
    sessions = SimpleNamespace(retrieve_async=AsyncMock(return_value=session), expire_async=AsyncMock())
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=sessions))))
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{"id": "order_fixture", "stripe_session_id": "cs_live_paid"}]))
    complete = AsyncMock(return_value="order_fixture")
    monkeypatch.setattr(server, "_complete_checkout_payment", complete)
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    assert asyncio.run(server._reconcile_expired_checkouts()) == 1
    complete.assert_awaited_once_with({"id": "cs_live_paid"})
    rpc.assert_not_called()


def test_explicit_live_mode_requires_production_and_live_key():
    with pytest.raises(RuntimeError, match="outside production"):
        settings(email_enabled=False, stripe_mode="live", stripe_secret_key="sk_live_synthetic").validate()
    settings(email_enabled=False, environment="production", stripe_mode="live", stripe_secret_key="sk_live_synthetic").validate()


@pytest.mark.parametrize("livemode", [True, None])
def test_real_sdk_signed_live_event_is_rejected_before_database(monkeypatch, livemode):
    configure_signed_webhook(monkeypatch)
    database = AsyncMock()
    monkeypatch.setattr(server.db, "select", database)
    payload, headers = signed_payload({"id": "evt_sdk_rejected", "object": "event", "livemode": livemode})
    response = TestClient(server.app).post("/api/stripe/webhook", content=payload, headers=headers)
    assert response.status_code == 400
    database.assert_not_called()


@pytest.mark.parametrize("tamper", ["secret", "payload"])
def test_real_sdk_rejects_invalid_signature_before_database(monkeypatch, tamper):
    configure_signed_webhook(monkeypatch)
    database = AsyncMock()
    monkeypatch.setattr(server.db, "select", database)
    payload, headers = signed_payload({"id": "evt_sdk_invalid", "object": "event", "livemode": False},
        secret="wrong_synthetic_secret" if tamper == "secret" else SIGNING_SECRET)
    if tamper == "payload":
        payload += b" "
    response = TestClient(server.app).post("/api/stripe/webhook", content=payload, headers=headers)
    assert response.status_code == 400
    database.assert_not_called()
