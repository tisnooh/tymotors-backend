"""Prepare an administrative CJ dossier, without creating an external order.

The current catalogue has one sellable SKU per product, not separate variants.
The connection contract is therefore platformProductId=product UUID and
platformVariantId=exact TYMotors SKU. Similar titles are never a match.
"""
from __future__ import annotations

import hashlib
import json


def prepare_cj_dossier(order: dict, items: list[dict], supplier_order: dict | None,
                       supplier_items: list[dict], cj: dict) -> dict:
    """Pure deterministic preview. Its fingerprint is NOT a dispatch authorization."""
    blockers: list[dict] = []

    def block(code: str, item_id: str | None = None):
        entry = {"code": code}
        if item_id:
            entry["order_item_id"] = item_id
        if entry not in blockers:
            blockers.append(entry)

    if order.get("is_test") is not False or order.get("sales_channel") == "diagnostic":
        block("test_order_excluded")
    if order.get("payment_status") != "paid":
        block("payment_not_confirmed")
    if order.get("fulfillment_status") in {"cancelled", "shipped", "delivered"}:
        block("order_not_dispatchable")
    if order.get("requires_compatibility_review") is not False:
        block("compatibility_review_required")
    if not items or len(items) > 20:
        block("invalid_order_lines")
    if not supplier_order:
        block("supplier_dossier_missing")
    elif supplier_order.get("status") != "approved":
        block("supplier_approval_required")
    if supplier_order and supplier_order.get("agent_order_id"):
        block("already_has_agent_order")
    if cj.get("status") != "api_authenticated":
        block("cj_" + str(cj.get("status") or "unavailable"))

    address = order.get("shipping_address") or {}
    if not isinstance(address, dict):
        address = {}
    if address.get("country") != "FR":
        block("destination_not_verified")
    if not all(isinstance(address.get(k), str) and address[k].strip()
               for k in ("line1", "city", "postal_code")) or not order.get("customer_name"):
        block("shipping_address_incomplete")
    # Stripe may legitimately omit state for France; CJ's order contract asks
    # for shippingProvince. Report that requirement without inventing a region.
    if not isinstance(address.get("state"), str) or not address["state"].strip():
        block("cj_shipping_province_required")

    lines = []
    seen = set()
    for item in sorted(items, key=lambda row: str(row.get("id"))):
        item_id = str(item.get("id") or "")
        product_id, sku = str(item.get("product_id") or ""), item.get("sku")
        quantity = item.get("quantity")
        if not item_id or item_id in seen or not product_id or not isinstance(sku, str) or not sku.strip() or type(quantity) is not int or not 1 <= quantity <= 20:
            block("invalid_order_line", item_id)
        seen.add(item_id)
        fitment = item.get("compatibility_result")
        if not isinstance(fitment, dict) or fitment.get("status") != "compatible":
            block("fitment_not_confirmed", item_id)
        matching = [row for row in supplier_items if row.get("order_item_id") == item_id]
        supplier = matching[0] if len(matching) == 1 else {}
        if (not supplier or supplier.get("product_id") != product_id or supplier.get("sku") != sku
                or supplier.get("quantity") != quantity
                or supplier.get("supplier_order_id") != (supplier_order or {}).get("id")
                or not all(supplier.get(k) for k in ("supplier_name", "supplier_reference", "exact_source_url"))):
            block("supplier_line_not_verified", item_id)
        product = (cj.get("products") or {}).get(product_id) or {}
        connection = product.get("connection") or {}
        mapping_ok = (product.get("status") == "mapped"
                      and connection.get("platformProductId") == product_id
                      and connection.get("platformVariantId") == sku
                      and all(connection.get(k) for k in ("shopId", "cjProductId", "cjVariantId", "cjSku")))
        if not mapping_ok:
            block("cj_variant_" + ("mismatch" if product.get("status") == "mapped" else str(product.get("status") or "missing")), item_id)
        if mapping_ok and (connection.get("targetCountryCode") != "FR"
                           or not all(connection.get(k) for k in ("sourceCountryCode", "logistics"))):
            block("cj_route_not_verified", item_id)
        lines.append({"order_item_id": item_id, "product_id": product_id, "sku": sku,
                      "quantity": quantity, "supplier_reference": supplier.get("supplier_reference"),
                      "supplier_snapshot": {k: supplier.get(k) for k in (
                          "supplier_order_id", "product_id", "sku", "quantity", "supplier_name",
                          "supplier_reference", "exact_source_url", "unit_cost_cents", "currency")},
                      "compatibility_result": fitment,
                      "mapping_status": product.get("status", "missing"),
                      "connection": connection if mapping_ok else None})

    # Existing price cents carry no purchase-currency/quote/version. Do not
    # reinterpret Soyintech USD as order EUR or turn an approval into spending.
    block("unit_shipping_quote_required")
    block("purchase_currency_and_complete_cost_required")
    block("financial_approval_snapshot_required")
    block("cj_dispatch_not_enabled")
    snapshot = {"schema_version": 1, "order_id": order["id"],
                "order_updated_at": order.get("updated_at"),
                "payment_status": order.get("payment_status"), "is_test": order.get("is_test"),
                "sales_channel": order.get("sales_channel"),
                "fulfillment_status": order.get("fulfillment_status"),
                "requires_compatibility_review": order.get("requires_compatibility_review"),
                "cj_status": cj.get("status"),
                "shipping_address": address, "customer_name": order.get("customer_name"),
                "customer_phone": order.get("customer_phone"),
                "currency": order.get("currency"), "total_cents": order.get("total_cents"),
                "supplier_order_id": (supplier_order or {}).get("id"),
                "supplier_updated_at": (supplier_order or {}).get("updated_at"),
                "supplier_status": (supplier_order or {}).get("status"),
                "agent_order_id": (supplier_order or {}).get("agent_order_id"),
                "lines": lines}
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return {"provider": "CJdropshipping", "scope": "read_only_preparation",
            "status": "blocked", "can_transmit": False, "transmitted": False,
            "fingerprint": fingerprint, "blockers": blockers, "snapshot": snapshot}
