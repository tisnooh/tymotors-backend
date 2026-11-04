from copy import deepcopy

import pytest

from app.cj_fulfillment import prepare_cj_dossier


def dossier():
    order = {"id": "order-1", "updated_at": "2026-11-03T12:00:00Z", "is_test": False,
             "payment_status": "paid", "fulfillment_status": "unfulfilled", "requires_compatibility_review": False,
             "customer_name": "Test Recipient", "currency": "EUR", "total_cents": 7900,
             "shipping_address": {"country": "FR", "state": "Paris", "city": "Paris", "postal_code": "75001", "line1": "Test address"}}
    items = [{"id": "item-1", "product_id": "product-1", "sku": "TY-MIRROR", "quantity": 1,
              "compatibility_result": {"status": "compatible"}}]
    supplier = {"id": "supplier-order-1", "status": "approved", "updated_at": "2026-11-03T12:01:00Z"}
    sources = [{"order_item_id": "item-1", "supplier_order_id": "supplier-order-1", "product_id": "product-1",
                "sku": "TY-MIRROR", "quantity": 1, "supplier_reference": "MR3BF2021", "supplier_name": "Supplier",
                "exact_source_url": "https://example.com/fixture", "unit_cost_cents": 1600, "currency": "EUR"}]
    cj = {"status": "api_authenticated", "products": {"product-1": {"status": "mapped", "connection": {
        "shopId": "fixture-shop", "platformProductId": "product-1", "platformVariantId": "TY-MIRROR",
        "cjProductId": "fixture-product", "cjVariantId": "fixture-variant", "cjSku": "FIXTURE-SKU",
        "sourceCountryCode": "CN", "targetCountryCode": "FR", "logistics": "Fixture method"}}}}
    return [order, items, supplier, sources, cj]


def codes(result):
    return {entry["code"] for entry in result["blockers"]}


def test_exact_mapping_is_not_spending_authorization_or_confirmed_cost():
    result = prepare_cj_dossier(*dossier())
    assert result["scope"] == "read_only_preparation"
    assert result["can_transmit"] is result["transmitted"] is False
    assert codes(result) == {"unit_shipping_quote_required", "purchase_currency_and_complete_cost_required",
                             "financial_approval_snapshot_required", "cj_paid_fulfillment_not_enabled"}
    assert "margin" not in result


@pytest.mark.parametrize("field,value,expected", [
    ("is_test", True, "test_order_excluded"),
    ("is_test", None, "test_order_excluded"),
    ("payment_status", "refunded", "payment_not_confirmed"),
    ("payment_status", "unpaid", "payment_not_confirmed"),
    ("requires_compatibility_review", True, "compatibility_review_required"),
    ("fulfillment_status", "shipped", "order_not_dispatchable"),
])
def test_ineligible_order_cannot_be_prepared_for_dispatch(field, value, expected):
    args = dossier()
    args[0][field] = value
    assert expected in codes(prepare_cj_dossier(*args))


def test_similar_sku_or_wrong_supplier_snapshot_never_match():
    args = dossier()
    args[4]["products"]["product-1"]["connection"]["platformVariantId"] = "TY-MIRROR-CARBON"
    args[3][0]["quantity"] = 2
    result = prepare_cj_dossier(*args)
    assert {"cj_variant_mismatch", "supplier_line_not_verified"} <= codes(result)
    assert result["snapshot"]["lines"][0]["connection"] is None


def test_wrong_route_address_and_missing_fitment_are_explicit():
    args = dossier()
    args[0]["shipping_address"]["country"] = "DE"
    del args[0]["shipping_address"]["state"]
    args[1][0]["compatibility_result"] = {"status": "confirm"}
    args[4]["products"]["product-1"]["connection"]["targetCountryCode"] = "US"
    assert {"destination_not_verified", "cj_shipping_province_required", "fitment_not_confirmed",
            "cj_route_not_verified"} <= codes(prepare_cj_dossier(*args))


def test_repeated_preview_is_stable_without_mutating_order_and_changes_invalidate_fingerprint():
    args = dossier()
    original = deepcopy(args)
    first = prepare_cj_dossier(*args)
    assert first == prepare_cj_dossier(*args)
    assert args == original
    args[0]["shipping_address"]["line1"] = "Changed address"
    assert first["fingerprint"] != prepare_cj_dossier(*args)["fingerprint"]
    args = deepcopy(original)
    args[4]["products"]["product-1"]["connection"]["cjVariantId"] = "different-variant"
    assert first["fingerprint"] != prepare_cj_dossier(*args)["fingerprint"]


def test_existing_agent_order_missing_lines_and_duplicate_lines_are_blocked():
    args = dossier()
    args[2]["agent_order_id"] = "existing-cj-order"
    args[1].append(deepcopy(args[1][0]))
    assert {"already_has_agent_order", "invalid_order_line"} <= codes(prepare_cj_dossier(*args))
    args[1] = []
    assert "invalid_order_lines" in codes(prepare_cj_dossier(*args))


@pytest.mark.parametrize("value", ["compatible", ["compatible"], 1, None])
def test_malformed_fitment_produces_blocker_instead_of_crash(value):
    args = dossier()
    args[1][0]["compatibility_result"] = value
    assert "fitment_not_confirmed" in codes(prepare_cj_dossier(*args))


def test_decision_and_provenance_changes_invalidate_fingerprint():
    original = dossier()
    fingerprint = prepare_cj_dossier(*original)["fingerprint"]
    changes = [(0, "fulfillment_status", "cancelled"), (0, "requires_compatibility_review", True),
               (2, "agent_order_id", "cj-order-existing")]
    for index, field, value in changes:
        args = deepcopy(original)
        args[index][field] = value
        assert prepare_cj_dossier(*args)["fingerprint"] != fingerprint
    args = deepcopy(original)
    args[3][0]["exact_source_url"] = "https://example.com/different-source"
    assert prepare_cj_dossier(*args)["fingerprint"] != fingerprint
