import asyncio
import json
import os
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "tymotors_test")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-only-secret-that-is-longer-than-thirty-two-characters")

from server import (  # noqa: E402
    CartItemInput,
    ProductCreateInput,
    VehicleSelection,
    check_compatibility,
    create_checkout_session,
    create_admin_token,
    require_admin,
    stripe_webhook,
)
import server  # noqa: E402


def active_product_payload():
    return {
        "slug": "calandre-bmw-f30",
        "name": "Calandre BMW F30",
        "subtitle": "BMW Série 3 F30 2012-2018",
        "description": "Une description suffisamment complète pour valider un produit de test.",
        "price": 99,
        "images": ["https://example.com/product.webp"],
        "category_slug": "performance",
        "subcategory": "Calandres",
        "sku": "TY-BMW-F30-001",
        "stock": 3,
        "compatibilities": [{
            "brand_slug": "bmw",
            "model": "Série 3",
            "chassis": "F30",
            "generation": "F30 / F35",
            "year_from": 2012,
            "year_to": 2018,
            "is_verified": True,
        }],
        "package_contents": ["Calandre"],
        "installation_difficulty": "medium",
        "delivery_estimate": "5 à 8 jours ouvrés",
        "status": "active",
        "is_verified": True,
        "admin": {"supplier_name": "Test Supplier", "cost_price": 35},
    }


def test_active_product_requires_verified_commercial_data():
    payload = active_product_payload()
    payload["compatibilities"][0]["is_verified"] = False
    with pytest.raises(ValidationError):
        ProductCreateInput.model_validate(payload)


def test_verified_exact_vehicle_is_compatible():
    payload = active_product_payload()
    product = ProductCreateInput.model_validate(payload).model_dump()
    result = check_compatibility(
        product,
        VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2016),
    )
    assert result["status"] == "compatible"


def test_unverified_or_incomplete_vehicle_requires_confirmation():
    payload = active_product_payload()
    payload["status"] = "draft"
    payload["is_verified"] = False
    payload["compatibilities"][0]["is_verified"] = False
    product = ProductCreateInput.model_validate(payload).model_dump()
    result = check_compatibility(
        product,
        VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2016),
    )
    assert result["status"] == "confirm"


def test_wrong_year_is_incompatible():
    product = ProductCreateInput.model_validate(active_product_payload()).model_dump()
    result = check_compatibility(
        product,
        VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2022),
    )
    assert result["status"] == "incompatible"


def test_cart_quantity_is_limited():
    with pytest.raises(ValidationError):
        CartItemInput(product_id="product", quantity=21)


def test_admin_token_is_short_lived_and_role_protected():
    token, expires_in = create_admin_token()
    assert 0 < expires_in <= 3600
    claims = jwt.decode(
        token,
        os.environ["ADMIN_JWT_SECRET"],
        algorithms=["HS256"],
        audience="tymotors-admin",
        issuer="tymotors-api",
    )
    assert claims["role"] == "admin"
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    authorized = asyncio.run(require_admin(credentials))
    assert authorized["sub"] == "tymotors-admin"


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    async def find_one(self, query, projection=None):
        if "session_id" in query:
            return next((doc.copy() for doc in self.documents if doc.get("session_id") == query["session_id"]), None)
        if "id" in query:
            return next((doc.copy() for doc in self.documents if doc.get("id") == query["id"]), None)
        return None

    async def insert_one(self, document):
        self.documents.append(document.copy())
        return SimpleNamespace(inserted_id=document.get("id"))

    async def update_one(self, query, update, upsert=False):
        document = next((doc for doc in self.documents if all(doc.get(key) == value for key, value in query.items() if not key.startswith("$"))), None)
        if document:
            document.update(update.get("$set", {}))
        return SimpleNamespace(modified_count=1 if document else 0)


def test_checkout_uses_server_price_and_creates_pending_order_first(monkeypatch):
    product = {
        "id": "prod-1", "slug": "calandre", "sku": "TY-1", "name": "Calandre",
        "price": 99.0, "currency": "EUR", "stock": 3, "status": "active", "compatibilities": [],
    }
    carts = MemoryCollection([{"session_id": "session-test", "items": [{"product_id": "prod-1", "quantity": 2}]}])
    products = MemoryCollection([product])
    orders = MemoryCollection()
    fake_db = SimpleNamespace(carts=carts, products=products, orders=orders)
    monkeypatch.setattr(server, "db", fake_db)
    monkeypatch.setattr(server.stripe, "api_key", "sk_test_unit")
    server.checkout_attempts.clear()

    def fake_create(**kwargs):
        assert orders.documents and orders.documents[0]["status"] == "pending"
        assert orders.documents[0]["subtotal_cents"] == 19800
        assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 9900
        return SimpleNamespace(id="cs_test_unit", url="https://checkout.stripe.test/unit")

    monkeypatch.setattr(server.stripe.checkout.Session, "create", fake_create)
    response = asyncio.run(create_checkout_session("session-test"))
    assert response["url"].startswith("https://checkout.stripe.test/")
    assert orders.documents[0]["stripe_session_id"] == "cs_test_unit"
    assert orders.documents[0]["requires_compatibility_review"] is True


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_unit_test")
    payload = json.dumps({"id": "evt_test", "type": "checkout.session.completed", "data": {"object": {}}}).encode()

    class FakeRequest:
        async def body(self):
            return payload

    with pytest.raises(HTTPException) as exc:
        asyncio.run(stripe_webhook(FakeRequest(), "t=1,v1=invalid"))
    assert exc.value.status_code == 400
