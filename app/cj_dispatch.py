"""Admin-triggered, persistent CJ draft dispatch. No supplier payment API exists here."""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException

from .cj_api import resolve_cj_variants
from .cj_fulfillment import prepare_cj_dossier
from .cj_orders import create_cj_order_draft, query_cj_order, _draft_payload


# These block a purchase/dispatch, but not an explicitly unpaid CJ draft.
# They remain in the preview as warnings. Nothing here clears supplier approval.
UNPAID_DRAFT_WARNINGS = frozenset({"unit_shipping_quote_required", "purchase_currency_and_complete_cost_required",
                                  "financial_approval_snapshot_required", "cj_paid_fulfillment_not_enabled"})


def draft_preview(order, items, supplier, supplier_items, cj):
    dossier = prepare_cj_dossier(order, items, supplier, supplier_items, cj)
    blockers = [b for b in dossier["blockers"] if b["code"] not in UNPAID_DRAFT_WARNINGS]
    warnings = [b for b in dossier["blockers"] if b["code"] in UNPAID_DRAFT_WARNINGS]
    if order.get("status") != "paid" or not order.get("stock_applied_at") or order.get("stock_shortfall_at"):
        blockers.append({"code": "paid_order_stock_not_secured"})
    if (not supplier or not supplier.get("approved_by") or not supplier.get("approved_at")
            or supplier.get("agent_provider") != "CJdropshipping"):
        blockers.append({"code": "supplier_approval_evidence_required"})
    lines = dossier["snapshot"]["lines"]
    routes = {(line["connection"]["sourceCountryCode"], line["connection"]["logistics"])
              for line in lines if line.get("connection")}
    if len(routes) != 1:
        blockers.append({"code": "mixed_or_missing_cj_routes"})
    shop_name = cj.get("shop_name")
    if not isinstance(shop_name, str) or not shop_name.strip() or len(shop_name) > 50:
        blockers.append({"code": "cj_store_name_not_verified"})
    if any(not line.get("connection") or line["connection"].get("shopId") != cj.get("shop_id") for line in lines):
        blockers.append({"code": "cj_store_mismatch"})
    payload = None
    if not blockers:
        address = order["shipping_address"]
        source, logistics = next(iter(routes))
        payload = {
            "orderNumber": order.get("order_number"), "payType": 3, "orderFlow": 1, "isSandbox": 0,
            "platform": "Api", "shopLogisticsType": 2,
            "storeName": shop_name, "shippingCountryCode": "FR", "shippingCountry": "France",
            "shippingProvince": address["state"], "shippingCity": address["city"],
            "shippingZip": address["postal_code"], "shippingCustomerName": order["customer_name"],
            "shippingAddress": address["line1"], "fromCountryCode": source, "logisticName": logistics,
            "products": [{"vid": line["connection"]["cjVariantId"], "sku": line["connection"]["cjSku"],
                          "quantity": line["quantity"], "storeLineItemId": line["order_item_id"],
                          "storeProductId": line["product_id"], "storeSku": line["sku"]} for line in lines],
        }
        if address.get("line2"):
            payload["shippingAddress2"] = address["line2"]
        if order.get("customer_phone"):
            payload["shippingPhone"] = order["customer_phone"]
        limits = {"orderNumber": 50, "storeName": 50, "shippingProvince": 50, "shippingCity": 50,
                  "shippingZip": 20, "shippingCustomerName": 50, "shippingAddress": 500,
                  "shippingAddress2": 500, "shippingPhone": 20, "logisticName": 50, "fromCountryCode": 2}
        if any(not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > limit
               for key, limit in limits.items() if key in payload):
            blockers.append({"code": "cj_field_length_or_type_invalid"})
            payload = None
        elif _draft_payload(payload) is None:
            blockers.append({"code": "cj_payload_not_supported"})
            payload = None
    fingerprint = hashlib.sha256(json.dumps({"dossier": dossier["fingerprint"], "payload": payload},
                                            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"scope": "unpaid_cj_draft", "can_submit_draft": not blockers,
            "can_pay_supplier": False, "blockers": blockers, "warnings": warnings,
            "fingerprint": fingerprint, "expected_updated_at": (supplier or {}).get("updated_at"), "payload": payload}


def submission_view(row: dict) -> dict:
    """No shipping payload/customer address in status responses or audit logs."""
    return {key: row.get(key) for key in ("id", "order_id", "state", "cj_order_id", "cj_shop_id", "request_id",
                                         "fingerprint", "reserved_at", "finished_at", "observed_at", "updated_at", "observation")}


async def load_draft_preview(db, cfg, order_id: str):
    rows = await db.select("orders", params={"id": f"eq.{order_id}", "limit": 1})
    if not rows:
        raise HTTPException(404, "Commande introuvable")
    order = rows[0]
    items = await db.select("order_items", params={"order_id": f"eq.{order_id}", "order": "id.asc", "limit": 21})
    suppliers = await db.select("supplier_orders", params={"order_id": f"eq.{order_id}", "limit": 1})
    supplier = suppliers[0] if suppliers else None
    sources = await db.select("supplier_order_items", params={"supplier_order_id": f"eq.{supplier['id']}", "limit": 21}) if supplier else []
    excluded = order.get("is_test") is not False or order.get("sales_channel") == "diagnostic"
    cj = {"status": "test_order_excluded", "products": {}} if excluded else await resolve_cj_variants(
        cfg.cj_api_key, list(dict.fromkeys(str(i["product_id"]) for i in items if i.get("product_id"))), shop_id=cfg.cj_shop_id)
    return order, draft_preview(order, items, supplier, sources, cj)


async def submit_draft(db, cfg, actor: str, order_id: str, expected: str, fingerprint: str):
    if getattr(cfg, "environment", None) != "production" or getattr(cfg, "stripe_mode", None) != "live":
        raise HTTPException(409, "L'envoi CJ réel est désactivé hors de la production Stripe réelle")
    existing = await db.select("cj_order_submissions", params={"order_id": f"eq.{order_id}", "limit": 1})
    if existing:
        return {"reused": True, "submission": submission_view(existing[0])}
    order, preview = await load_draft_preview(db, cfg, order_id)
    if not preview["can_submit_draft"]:
        raise HTTPException(409, {"message": "Dossier CJ incomplet", "blockers": preview["blockers"]})
    if preview["fingerprint"] != fingerprint:
        raise HTTPException(409, "Dossier modifié ; vérifier à nouveau avant l'envoi")
    claim = await db.rpc("admin_claim_cj_submission", {"p_actor": actor, "p_order_id": order_id,
        "p_expected": expected, "p_fingerprint": fingerprint, "p_payload": preview["payload"], "p_cj_shop_id": cfg.cj_shop_id})
    row = claim["submission"]
    if not claim["claimed"]:
        return {"reused": True, "submission": submission_view(row)}
    # The reserved row remains after a process crash. It is NEVER claimed again.
    # Any uncertain result requires provider reconciliation, not another POST.
    try:
        result = await create_cj_order_draft(cfg.cj_api_key, row["payload"])
    except Exception:
        result = {"status": "uncertain"}
    state = "submitted" if result.get("status") == "submitted" else "uncertain"
    finished = await db.rpc("admin_finish_cj_submission", {"p_actor": actor, "p_submission_id": row["id"],
        "p_state": state, "p_cj_order_id": result.get("cj_order_id") if state == "submitted" else None,
        "p_request_id": result.get("request_id")})
    return {"reused": False, "submission": submission_view(finished), "supplier_payment": "not_initiated"}


async def refresh_draft(db, cfg, actor: str, order_id: str):
    rows = await db.select("cj_order_submissions", params={"order_id": f"eq.{order_id}", "limit": 1})
    if not rows:
        raise HTTPException(404, "Aucun brouillon CJ enregistré")
    row = rows[0]
    if row.get("cj_shop_id") != cfg.cj_shop_id:
        raise HTTPException(409, "Le magasin configuré a changé ; rapprochement CJ requis")
    if row.get("state") != "submitted" or not row.get("cj_order_id"):
        raise HTTPException(409, "Envoi incertain : rapprochement CJ requis, aucun renvoi automatique")
    result = await query_cj_order(cfg.cj_api_key, row["cj_order_id"])
    if result.get("status") != "observed":
        raise HTTPException(503, "Statut CJ indisponible ; état local conservé")
    observation = result["observation"]
    if observation.get("shop_id") != cfg.cj_shop_id:
        raise HTTPException(409, "La commande CJ ne correspond pas au magasin TYMotors")
    expected_lines = sorted((p["storeLineItemId"], p["vid"], p["quantity"]) for p in row["payload"]["products"])
    actual_lines = observation.get("products")
    if (not isinstance(actual_lines, list) or len(actual_lines) != len(expected_lines)
            or not all(isinstance(p, dict) and isinstance(p.get("store_line_item_id"), str)
                       and isinstance(p.get("vid"), str) and type(p.get("quantity")) is int for p in actual_lines)
            or sorted((p["store_line_item_id"], p["vid"], p["quantity"]) for p in actual_lines) != expected_lines):
        raise HTTPException(409, "Les lignes CJ ne correspondent pas à la commande réservée")
    stored = await db.rpc("admin_observe_cj_submission", {"p_actor": actor, "p_submission_id": row["id"],
                                                           "p_observation": observation})
    return {"submission": submission_view(stored), "customer_tracking_updated": False}
