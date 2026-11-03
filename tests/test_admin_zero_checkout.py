"""Private zero-euro diagnostic: no public cart, stock or supplier effects."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server


ADMIN_ID = "10000000-0000-4000-8000-000000000001"
ORDER_ID = "20000000-0000-4000-8000-000000000001"
SESSION_ID = "cs_live_zero_fixture"
ADMIN = {"id": ADMIN_ID, "profile": {"email": "admin@example.test", "role": "admin"}}


def _live_settings(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(
        server.settings, environment="production", stripe_mode="live",
        stripe_secret_key="sk_live_synthetic_fixture"))
    server.checkout_attempts.clear()


def test_zero_checkout_is_admin_only_before_any_database_write(monkeypatch):
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    response = TestClient(server.app).post("/api/admin/diagnostics/zero-checkout")
    assert response.status_code == 401
    rpc.assert_not_awaited()


def test_zero_checkout_rejects_a_signed_in_non_admin(monkeypatch):
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{"role": "customer"}]))
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    server.app.dependency_overrides[server.require_user] = lambda: {"id": ADMIN_ID}
    try:
        response = TestClient(server.app).post("/api/admin/diagnostics/zero-checkout")
    finally:
        server.app.dependency_overrides.clear()
    assert response.status_code == 403
    rpc.assert_not_awaited()


def test_zero_checkout_uses_internal_zero_item_and_reuses_the_same_session(monkeypatch):
    _live_settings(monkeypatch)
    create = AsyncMock(return_value=SimpleNamespace(id=SESSION_ID, url="https://checkout.stripe.com/c/zero"))
    retrieve = AsyncMock(return_value=SimpleNamespace(id=SESSION_ID, status="open", url="https://checkout.stripe.com/c/zero"))
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create, retrieve_async=retrieve)))))
    rpc = AsyncMock(side_effect=[
        {"order_id": ORDER_ID, "order_number": "TY-DIAG-1", "stripe_session_id": None},
        {"order_id": ORDER_ID, "order_number": "TY-DIAG-1", "stripe_session_id": SESSION_ID},
    ])
    update = AsyncMock(return_value=[{"id": ORDER_ID, "stripe_session_id": SESSION_ID}])
    audit = AsyncMock(return_value=[{"id": "audit-fixture"}])
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server.db, "update", update)
    monkeypatch.setattr(server.db, "insert", audit)
    server.app.dependency_overrides[server.require_admin] = lambda: ADMIN
    try:
        client = TestClient(server.app)
        bad = client.post("/api/admin/diagnostics/zero-checkout", json={"price_cents": 100})
        assert bad.status_code == 422
        rpc.assert_not_awaited()
        first = client.post("/api/admin/diagnostics/zero-checkout")
        second = client.post("/api/admin/diagnostics/zero-checkout")
    finally:
        server.app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "url": "https://checkout.stripe.com/c/zero", "order_reference": "TY-DIAG-1",
        "order_id": ORDER_ID, "is_test": True, "scope": "stripe_order_only",
    }
    assert rpc.await_count == 2
    assert all(c.args == ("create_admin_zero_diagnostic_order", {"p_admin_id": ADMIN_ID}) for c in rpc.await_args_list)
    create.assert_awaited_once()
    params = create.await_args.kwargs["params"]
    assert params["mode"] == "payment"
    assert params["line_items"][0]["price_data"]["unit_amount"] == 0
    assert params["metadata"] == {"order_id": ORDER_ID, "diagnostic_zero": "1"}
    assert params["customer_creation"] == "always"
    assert params["integration_identifier"] == "tymotors_zero_caaaaaaa"
    assert "payment_method_collection" not in params
    assert "shipping_address_collection" not in params
    assert create.await_args.kwargs["options"]["idempotency_key"] == f"admin_zero_{ORDER_ID}"
    assert update.await_args.kwargs["params"]["stripe_session_id"] == "is.null"
    assert audit.await_args.args[1]["action"] == "diagnostic.zero_checkout.session"
    retrieve.assert_awaited_once_with(SESSION_ID)


@pytest.mark.parametrize("payment_status", ["paid", "no_payment_required"])
def test_live_zero_completion_is_strict_and_never_emails_a_customer(monkeypatch, payment_status):
    _live_settings(monkeypatch)
    row = {"id": ORDER_ID, "total_cents": 0, "currency": "EUR",
           "stripe_session_id": SESSION_ID, "customer_email": "admin@example.test",
           "is_test": True, "sales_channel": "diagnostic",
           "checkout_attempt_key": "admin-zero:10000000-0000-4000-8000-000000000099"}
    select = AsyncMock(side_effect=[[row], [{"user_id": ADMIN_ID, "customer_email": "admin@example.test"}]])
    rpc = AsyncMock(return_value=True)
    email = AsyncMock()
    monkeypatch.setattr(server.db, "select", select)
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server.db, "update", AsyncMock())
    monkeypatch.setattr(server, "_send_order_email", email)
    event = {"payment_status": payment_status, "metadata": {"order_id": ORDER_ID, "diagnostic_zero": "1"},
             "id": SESSION_ID, "client_reference_id": ORDER_ID, "amount_total": 0,
             "currency": "eur", "payment_intent": None,
             "customer_details": {"email": "admin@example.test"}}
    assert asyncio.run(server._complete_checkout_payment(event)) == ORDER_ID
    assert rpc.await_args.args[0] == "complete_paid_order"
    assert rpc.await_args.args[1]["p_payment_intent_id"] is None
    email.assert_not_awaited()


def test_live_event_cannot_convert_a_normal_test_order_into_a_zero_diagnostic(monkeypatch):
    _live_settings(monkeypatch)
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{
        "id": ORDER_ID, "total_cents": 0, "currency": "EUR", "stripe_session_id": SESSION_ID,
        "is_test": True, "sales_channel": "website", "checkout_attempt_key": None,
    }]))
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    event = {"payment_status": "paid", "metadata": {"order_id": ORDER_ID, "diagnostic_zero": "1"},
             "id": SESSION_ID, "client_reference_id": ORDER_ID, "amount_total": 0,
             "currency": "eur", "payment_intent": None}
    try:
        asyncio.run(server._complete_checkout_payment(event))
        assert False, "ordinary test order must reject a live event"
    except RuntimeError as error:
        assert "test order cannot" in str(error)
    rpc.assert_not_awaited()
