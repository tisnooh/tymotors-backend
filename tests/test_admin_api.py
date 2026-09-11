import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
import server
from app.admin import PromotionInput, StockInput, product_input_data, search_filter
from app.schemas import ProductInput, ProfileUpdateInput
from tests.test_security_and_catalog import active_product_payload

ADMIN = "10000000-0000-4000-8000-000000000001"
CUSTOMER = "10000000-0000-4000-8000-000000000002"


@pytest.fixture
def client(monkeypatch):
    async def user(token):
        if token == "admin-test-token": return {"id": ADMIN}
        if token == "customer-test-token": return {"id": CUSTOMER}
        return None
    async def select(table, *, params=None):
        if table == "profiles":
            return [{"id": ADMIN, "role": "admin"}] if params["id"] == f"eq.{ADMIN}" else [{"id": CUSTOMER, "role": "customer"}]
        return []
    monkeypatch.setattr(server.db, "get_user", user)
    monkeypatch.setattr(server.db, "select", select)
    # Deliberately do not enter lifespan: no network or production credentials.
    return TestClient(server.app)


def admin_routes():
    for route in server.app.routes:
        if getattr(route, "path", "").startswith("/api/admin") and route.path != "/api/admin/login":
            for method in route.methods:
                if method in {"HEAD", "OPTIONS"}: continue
                path = route.path
                for param in ("product_id", "order_id", "return_id", "promotion_id"):
                    path = path.replace("{" + param + "}", ADMIN)
                path = path.replace("{slug}", "test-product").replace("{channel}", "leboncoin")
                yield method, path


@pytest.mark.parametrize("method,path", list(admin_routes()))
@pytest.mark.parametrize("token,status", [(None, 401), ("customer-test-token", 403), ("expired-token", 401)])
def test_every_admin_endpoint_rejects_unauthorized(client, method, path, token, status):
    response = client.request(method, path, headers={"Authorization": f"Bearer {token}"} if token else {}, json={})
    assert response.status_code == status, (method, path, response.text)


def test_admin_is_verified_from_current_profile(client):
    assert client.get("/api/admin/verify", headers={"Authorization": "Bearer admin-test-token"}).json()["authenticated"] is True


def test_products_are_paginated_on_server(client, monkeypatch):
    mock = AsyncMock(return_value={"items": [], "page": 2, "limit": 25, "total": 75, "pages": 3})
    monkeypatch.setattr(server.db, "page", mock)
    response = client.get("/api/admin/products?page=2&q=BMW&status=draft", headers={"Authorization": "Bearer admin-test-token"})
    assert response.status_code == 200
    assert response.json()["total"] == 75
    kwargs = mock.call_args.kwargs
    assert kwargs["page"] == 2
    assert kwargs["params"]["status"] == "eq.draft"
    assert "BMW" in kwargs["params"]["or"]


def test_customer_cannot_mass_assign_role():
    with pytest.raises(ValidationError): ProfileUpdateInput(role="admin")


def test_product_edit_accepts_hydrated_compatibilities_without_leaking_fields():
    p = active_product_payload()
    p["id"] = ADMIN
    p["updated_at"] = "2026-09-11"
    p["compatibilities"][0]["id"] = CUSTOMER
    cleaned = product_input_data(p, ProductInput)
    assert "id" not in cleaned
    assert "id" not in cleaned["compatibilities"][0]
    assert ProductInput.model_validate(cleaned).status == "active"


def test_product_input_rejects_script_image_urls():
    p = active_product_payload()
    p["images"] = ["javascript:alert(1)"]
    with pytest.raises(ValidationError): ProductInput.model_validate(p)


def test_filter_grammar_cannot_be_injected():
    f = search_filter("x),role.eq.admin,*", ["name", "sku"])
    assert "role.eq.admin" not in f
    assert f.count("(") == f.count(")") == 1


def test_promotion_validation():
    with pytest.raises(ValidationError): PromotionInput(code="TEST", discount_type="percent", value=101)
    with pytest.raises(ValidationError): PromotionInput(code="TEST", discount_type="fixed", value=-5)


def test_promotion_dates_require_timezone_and_chronological_order():
    base = {"code": "TEST", "discount_type": "percent", "value": 10}
    with pytest.raises(ValidationError):
        PromotionInput(**base, starts_at="2026-09-11T10:00:00", ends_at="2026-09-12T10:00:00Z")
    with pytest.raises(ValidationError):
        PromotionInput(**base, starts_at="2026-09-12T10:00:00Z", ends_at="2026-09-11T10:00:00Z")
    assert PromotionInput(**base, starts_at="2026-09-11T10:00:00+02:00", ends_at="2026-09-12T10:00:00Z").starts_at


def test_inventory_payload_rejects_arbitrary_fields():
    with pytest.raises(ValidationError): StockInput(expected_stock=10, delta=1, reason="received", role="admin")


def test_upload_rejects_forged_webp(client):
    response = client.post("/api/admin/upload-image", headers={"Authorization": "Bearer admin-test-token"},
                           files={"file": ("attack.webp", b"RIFFxxxxWAVEbad-data", "image/webp")})
    assert response.status_code == 400


def test_invalid_admin_request_never_calls_mutation(client, monkeypatch):
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    response = client.post(f"/api/admin/inventory/{ADMIN}", headers={"Authorization": "Bearer customer-test-token"},
                           json={"expected_stock": 1, "delta": 100, "reason": "correction"})
    assert response.status_code == 403
    rpc.assert_not_called()


def test_pending_and_failed_refunds_never_reduce_revenue(monkeypatch):
    class RefundPage:
        async def auto_paging_iter(self):
            for status, amount in [("succeeded", 400), ("pending", 600), ("failed", 500)]:
                yield {"status": status, "amount": amount}
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, "rpc", rpc)
    monkeypatch.setattr(server, "stripe_client", SimpleNamespace(v1=SimpleNamespace(refunds=SimpleNamespace(list_async=AsyncMock(return_value=RefundPage())))))
    asyncio.run(server._sync_refunds("pi_test"))
    rpc.assert_awaited_once_with("record_order_refund", {"p_payment_intent": "pi_test", "p_refunded": 400})
