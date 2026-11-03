"""Conservative CJ order-draft creation and read-only reconciliation.

Only createOrderV2 with payType=3 is permitted. A timed-out or malformed POST
has an uncertain outcome and must be reconciled by order ID/number, never
submitted again by this module. No payment, cart or confirmation API is used.
"""

import re
import uuid

import httpx

from app import cj_api


CREATE_ORDER_URL = "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/createOrderV2"
ORDER_DETAIL_URL = "https://developers.cjdropshipping.com/api2.0/v1/shopping/order/getOrderDetail"

_REQUIRED_TEXT = {
    "orderNumber": 50,
    "shippingZip": 20,
    "shippingCountry": 50,
    "shippingProvince": 50,
    "shippingCity": 50,
    "shippingCustomerName": 50,
    "shippingAddress": 500,
    "logisticName": 50,
    "storeName": 50,
}
_OPTIONAL_TEXT = {"shippingPhone": 20, "shippingAddress2": 500, "email": 50, "remark": 500}
_PRODUCT_TEXT = {"vid": 50, "sku": 50, "storeLineItemId": 125, "storeProductId": 64, "storeSku": 60}
_SAFE_ID = re.compile(r"[A-Za-z0-9_#.-]+\Z")


def _text(value: object, maximum: int) -> bool:
    return (isinstance(value, str) and 0 < len(value.strip()) <= maximum
            and value == value.strip() and not any(ord(char) < 32 for char in value))


def _safe_id(value: object, maximum: int) -> str | None:
    return value if _text(value, maximum) and _SAFE_ID.fullmatch(value) else None


def _request_id(payload: object) -> str | None:
    return _safe_id(payload.get("requestId"), 48) if isinstance(payload, dict) else None


def _draft_payload(value: object) -> dict | None:
    """Reject unknown controls and carry only documented, explicitly checked fields."""
    if not isinstance(value, dict) or set(value) - (
        set(_REQUIRED_TEXT) | set(_OPTIONAL_TEXT) | {
            "shippingCountryCode", "fromCountryCode", "payType", "orderFlow", "isSandbox", "products",
            "platform", "shopLogisticsType",
        }
    ):
        return None
    if (type(value.get("payType")) is not int or value["payType"] != 3
            or type(value.get("orderFlow")) is not int or value["orderFlow"] != 1
            or type(value.get("isSandbox")) is not int or value["isSandbox"] != 0
            or value.get("platform") != "Api"
            or type(value.get("shopLogisticsType")) is not int or value["shopLogisticsType"] != 2):
        return None
    if value.get("shippingCountryCode") != "FR" or value.get("shippingCountry") != "France":
        return None
    if not isinstance(value.get("fromCountryCode"), str) or not re.fullmatch(r"[A-Z]{2}", value["fromCountryCode"]):
        return None
    if any(not _text(value.get(field), limit) for field, limit in _REQUIRED_TEXT.items()):
        return None
    if not _safe_id(value["orderNumber"], 50):
        return None
    if any(field in value and value[field] is not None and not _text(value[field], limit)
           for field, limit in _OPTIONAL_TEXT.items()):
        return None
    products = value.get("products")
    if not isinstance(products, list) or not 1 <= len(products) <= 20:
        return None
    clean_products = []
    line_ids = set()
    for row in products:
        if not isinstance(row, dict) or set(row) != set(_PRODUCT_TEXT) | {"quantity"}:
            return None
        if any(not _safe_id(row.get(field), maximum) for field, maximum in _PRODUCT_TEXT.items()):
            return None
        try:
            if str(uuid.UUID(row["storeProductId"])) != row["storeProductId"]:
                return None
        except (ValueError, AttributeError):
            return None
        if type(row.get("quantity")) is not int or not 1 <= row["quantity"] <= 20:
            return None
        if row["storeLineItemId"] in line_ids:
            return None
        line_ids.add(row["storeLineItemId"])
        clean_products.append({field: row[field] for field in _PRODUCT_TEXT} | {"quantity": row["quantity"]})
    return {field: value[field] for field in _REQUIRED_TEXT} | {
        field: value[field] for field in _OPTIONAL_TEXT if value.get(field) is not None
    } | {
        "shippingCountryCode": "FR", "fromCountryCode": value["fromCountryCode"],
        "payType": 3, "orderFlow": 1, "isSandbox": 0,
        "platform": "Api", "shopLogisticsType": 2, "products": clean_products,
    }


async def _token(client: httpx.AsyncClient, api_key: str, deadline: float,
                 bypass_rate_limit: bool) -> tuple[str | None, str | None]:
    """Return token or safe request ID. This call cannot create an order."""
    response = await cj_api._cj_request(client, "POST", cj_api.TOKEN_URL, deadline=deadline,
                                        bypass_rate_limit=bypass_rate_limit, json={"apiKey": api_key})
    payload = response.json()
    data = payload.get("data") if cj_api._cj_success(response, payload) else None
    token = data.get("accessToken") if isinstance(data, dict) else None
    return (token if isinstance(token, str) and token else None, _request_id(payload))


async def create_cj_order_draft(api_key: str, payload: dict,
                                transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Submit at most one unpaid CJ draft. Any post-submit ambiguity stays uncertain."""
    if not api_key:
        return {"status": "not_configured"}
    clean = _draft_payload(payload)
    if clean is None:
        return {"status": "rejected"}
    deadline = cj_api._now() + cj_api.CJ_CALL_BUDGET_SECONDS
    bypass_rate_limit = transport is not None  # MockTransport never reaches CJ.
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            try:
                token, auth_request_id = await _token(client, api_key, deadline, bypass_rate_limit)
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
                return {"status": "rejected"}  # No order POST was attempted.
            if not token:
                return {"status": "rejected", **({"request_id": auth_request_id} if auth_request_id else {})}
            try:
                response = await cj_api._cj_request(client, "POST", CREATE_ORDER_URL, deadline=deadline,
                                                    bypass_rate_limit=bypass_rate_limit,
                                                    headers={"CJ-Access-Token": token}, json=clean)
                result = response.json()
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
                return {"status": "uncertain"}
            request_id = _request_id(result)
            uncertain = {"status": "uncertain", **({"request_id": request_id} if request_id else {})}
            if not cj_api._cj_success(response, result):
                return uncertain
            data = result.get("data")
            if not isinstance(data, dict):
                return uncertain
            order_id = _safe_id(data.get("orderId"), 200)
            returned_number = data.get("orderNumber")
            if not order_id or (returned_number not in (None, "") and returned_number != clean["orderNumber"]):
                return uncertain
            return {"status": "submitted", "cj_order_id": order_id,
                    **({"request_id": request_id} if request_id else {})}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        return {"status": "uncertain"}


def _safe_product_lines(value: object) -> list[dict] | None:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        return None
    lines = []
    line_ids = set()
    for row in value:
        if (not isinstance(row, dict) or not _safe_id(row.get("vid"), 50)
                or not _safe_id(row.get("storeLineItemId"), 125)):
            return None
        if row["storeLineItemId"] in line_ids:
            return None
        line_ids.add(row["storeLineItemId"])
        quantity = row.get("quantity")
        if type(quantity) is not int or not 1 <= quantity <= 100000:
            return None
        lines.append({
            "vid": row["vid"], "quantity": quantity,
            "store_line_item_id": row["storeLineItemId"],
        })
    return lines


async def query_cj_order(api_key: str, cj_order_id: str,
                         transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Read only the requested order, returning documented non-PII fields."""
    if not api_key:
        return {"status": "not_configured"}
    if not _safe_id(cj_order_id, 200):
        return {"status": "rejected"}
    deadline = cj_api._now() + cj_api.CJ_CALL_BUDGET_SECONDS
    bypass_rate_limit = transport is not None
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            try:
                token, _ = await _token(client, api_key, deadline, bypass_rate_limit)
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
                return {"status": "unavailable"}
            if not token:
                return {"status": "rejected"}
            response = await cj_api._cj_request(client, "GET", ORDER_DETAIL_URL, deadline=deadline,
                                                bypass_rate_limit=bypass_rate_limit,
                                                headers={"CJ-Access-Token": token}, params={"orderId": cj_order_id})
            result = response.json()
            data = result.get("data") if cj_api._cj_success(response, result) else None
            if not isinstance(data, dict) or data.get("orderId") != cj_order_id:
                return {"status": "unavailable"}
            lines = _safe_product_lines(data.get("productList"))
            shop_id = _safe_id(data.get("shopId"), 200)
            order_status = _safe_id(data.get("orderStatus"), 200)
            if lines is None or not shop_id or not order_status:
                return {"status": "unavailable"}
            return {"status": "observed", "observation": {
                "order_id": cj_order_id, "shop_id": shop_id,
                "order_number": _safe_id(data.get("orderNum"), 200),
                "order_status": order_status,
                "sub_status": _safe_id(data.get("subStatus"), 200),
                "tracking_number": _safe_id(data.get("trackNumber"), 200),
                "tracking_provider": _safe_id(data.get("trackingProvider"), 200),
                "logistic_name": _safe_id(data.get("logisticName"), 200),
                "products": lines,
            }}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        return {"status": "unavailable"}
