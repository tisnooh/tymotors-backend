from pathlib import Path

import pytest
from pydantic import ValidationError

from app.compatibility import check_compatibility
from app.config import Settings, get_settings
from app.schemas import CartItemInput, ProductInput, VehicleSelection
from app.supabase_rest import SupabaseRest
from scripts.import_legacy_catalog import contains_replacement_character


def active_product_payload():
    return {
        "slug": "calandre-bmw-f30",
        "name": "Calandre BMW F30",
        "subtitle": "BMW Série 3 F30 2012-2018",
        "description": "Une description suffisamment complète pour valider un produit de test.",
        "price": 99,
        "images": ["https://example.com/product.webp"],
        "category_slug": "exterior",
        "subcategory": "Calandres",
        "sku": "TY-BMW-F30-001",
        "stock": 3,
        "compatibilities": [{
            "brand_slug": "bmw", "model": "Série 3", "chassis": "F30", "generation": "F30 / F35",
            "year_from": 2012, "year_to": 2018, "is_verified": True,
        }],
        "package_contents": ["Calandre"],
        "installation_difficulty": "medium",
        "delivery_estimate": "5 à 8 jours ouvrés",
        "status": "active",
        "is_verified": True,
        "admin": {"supplier_name": "Test Supplier", "supplier_verified": True, "cost_price": 35},
    }


def test_active_product_requires_verified_commercial_data():
    payload = active_product_payload(); payload["admin"]["supplier_verified"] = False
    with pytest.raises(ValidationError):
        ProductInput.model_validate(payload)


def test_verified_exact_vehicle_is_compatible():
    product = ProductInput.model_validate(active_product_payload()).model_dump()
    result = check_compatibility(product, VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2016))
    assert result["status"] == "compatible"


def test_unverified_data_requires_confirmation():
    payload = active_product_payload(); payload.update(status="draft", is_verified=False)
    payload["compatibilities"][0]["is_verified"] = False
    product = ProductInput.model_validate(payload).model_dump()
    result = check_compatibility(product, VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2016))
    assert result["status"] == "confirm"


def test_wrong_year_is_incompatible():
    product = ProductInput.model_validate(active_product_payload()).model_dump()
    result = check_compatibility(product, VehicleSelection(brand_slug="bmw", model="Série 3", chassis="F30", year=2022))
    assert result["status"] == "incompatible"


def test_cart_quantity_is_limited():
    with pytest.raises(ValidationError):
        CartItemInput(product_id="product", quantity=21)


def test_settings_reject_shared_public_and_service_key():
    settings = Settings(
        environment="test", supabase_url="https://example.supabase.co", supabase_publishable_key="same",
        supabase_service_role_key="same", frontend_url="http://localhost:3000", cors_origins=["http://localhost:3000"],
        cors_origin_regex=None, stripe_secret_key="", stripe_webhook_secret="", shipping_rate_cents=0,
        free_shipping_threshold_cents=0, cloudinary_url="", cloudinary_cloud_name="", cloudinary_api_key="",
        cloudinary_api_secret="",
    )
    with pytest.raises(RuntimeError): settings.validate()


def test_settings_prefers_modern_supabase_secret_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_modern")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-service-role")
    get_settings.cache_clear()
    try:
        assert get_settings().supabase_service_role_key == "sb_secret_modern"
    finally:
        get_settings.cache_clear()


def test_modern_supabase_secret_is_not_sent_as_bearer_token():
    modern = SupabaseRest("https://example.supabase.co", "sb_secret_modern", "sb_publishable_public")
    legacy = SupabaseRest("https://example.supabase.co", "legacy-service-role-jwt", "sb_publishable_public")

    assert modern._headers()["apikey"] == "sb_secret_modern"
    assert "Authorization" not in modern._headers()
    assert legacy._headers()["Authorization"] == "Bearer legacy-service-role-jwt"


def test_catalog_import_detects_nested_unicode_replacement_characters():
    assert contains_replacement_character({"name": "S\ufffdrie 3"}) is True
    assert contains_replacement_character({"name": "Série 3", "generations": ["F30"]}) is False


def test_schema_enables_rls_and_atomic_payment_completion():
    sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "202608240001_initial_ecommerce.sql").read_text(encoding="utf-8")
    for table in ("profiles", "products", "product_supplier_data", "orders", "order_items", "wishlists", "stripe_events"):
        assert f"alter table public.{table} enable row level security" in sql
    assert "create or replace function public.complete_paid_order" in sql
    assert "for update" in sql
    assert "grant execute on function public.complete_paid_order" in sql


def test_runtime_has_no_mongodb_dependency():
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(encoding="utf-8").casefold()
    server = (Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8").casefold()
    assert "motor" not in requirements
    assert "pymongo" not in requirements
    assert "mongo" not in server


def test_checkout_and_webhook_enforce_vehicle_and_order_integrity():
    server = (Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8")
    assert 'compatibility_result["status"] == "incompatible"' in server
    assert 'obj.get("amount_total") != expected.get("total_cents")' in server
    assert 'obj.get("client_reference_id") != order_id' in server
    assert 'completed is not True' in server
    assert 'checkout.sessions.retrieve_async(stripe_session_id)' in server
    assert 'collected.get("shipping_details")' in server


def test_cart_response_exposes_server_calculated_totals_and_compatibility():
    server = (Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8")
    assert '"line_total": line_total_cents / 100' in server
    assert '"compatibility_result": compatibility_result' in server
    assert '"shipping": shipping_cents / 100' in server
    assert '"total": (subtotal_cents + shipping_cents) / 100' in server
