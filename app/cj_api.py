"""Read-only CJ API probes and exact variant lookup; never writes orders."""

import asyncio
import re
import threading
import time

import httpx


TOKEN_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
SHOPS_URL = "https://developers.cjdropshipping.com/api2.0/v1/shop/getShops"
CONNECTIONS_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/conn/connection"
MAX_RESOLVE_PRODUCTS = 20
MAX_CONNECTION_PAGES = 3
CONNECTION_PAGE_SIZE = 100
CJ_REQUEST_INTERVAL_SECONDS = 1.0
CJ_CALL_BUDGET_SECONDS = 30.0
_now = time.monotonic
_sleep = asyncio.sleep
_rate_lock = threading.Lock()
_next_cj_request_at = 0.0
SAFE_CONNECTION_FIELDS = (
    "shopId", "platformProductId", "platformVariantId", "cjProductId",
    "cjVariantId", "cjSku", "sourceCountryCode", "targetCountryCode", "logistics",
)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,48}\Z")


def _contains_secret(value: object, secrets: tuple[str, ...]) -> bool:
    return isinstance(value, str) and any(secret and secret in value for secret in secrets)


def _safe_request_id(payload: object, forbidden: tuple[str, ...] = ()) -> str | None:
    value = payload.get("requestId") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not _SAFE_REQUEST_ID.fullmatch(value):
        return None
    return None if _contains_secret(value, forbidden) else value


def _probe_failure(stage: str, response: httpx.Response | None = None,
                   payload: object = None, forbidden: tuple[str, ...] = ()) -> dict:
    """Expose only stable, bounded CJ diagnostics; never echo provider content."""
    diagnostics = {"stage": stage}
    if response is not None and type(response.status_code) is int and 100 <= response.status_code <= 599:
        diagnostics["http_status"] = response.status_code
    if isinstance(payload, dict):
        code = payload.get("code")
        if type(code) is int and 0 <= code <= 2_147_483_647:
            diagnostics["code"] = code
        request_id = _safe_request_id(payload, forbidden)
        if request_id is not None:
            diagnostics["request_id"] = request_id
    return diagnostics


async def _wait_for_cj_slot(deadline: float) -> None:
    """Space CJ network starts across async callers in this Python process."""
    global _next_cj_request_at
    while True:
        with _rate_lock:
            now = _now()
            if now >= deadline:
                raise TimeoutError("CJ call budget exhausted")
            if now >= _next_cj_request_at:
                _next_cj_request_at = now + CJ_REQUEST_INTERVAL_SECONDS
                return
            delay = min(_next_cj_request_at - now, deadline - now)
        await _sleep(delay)


async def _cj_request(client: httpx.AsyncClient, method: str, url: str, *,
                      deadline: float, bypass_rate_limit: bool = False, **kwargs) -> httpx.Response:
    if not bypass_rate_limit:
        await _wait_for_cj_slot(deadline)
    remaining = deadline - _now()
    if remaining <= 0:
        raise TimeoutError("CJ call budget exhausted")
    return await asyncio.wait_for(client.request(method, url, **kwargs), timeout=remaining)


def _cj_success(response: httpx.Response, payload: object) -> bool:
    return (response.status_code == 200 and isinstance(payload, dict)
            and type(payload.get("code")) is int and payload["code"] in (0, 200)
            and payload.get("result") is True)


def _safe_connection(row: object, product_id: str, shop_id: str) -> dict | None:
    if not isinstance(row, dict):
        return None
    if row.get("platformProductId") != product_id or row.get("shopId") != shop_id:
        return None
    required = ("platformVariantId", "cjProductId", "cjVariantId", "cjSku")
    if any(not isinstance(row.get(field), str) or not row[field].strip() for field in required):
        return None
    result = {}
    for field in SAFE_CONNECTION_FIELDS:
        value = row.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            return None
        result[field] = value
    return result


async def resolve_cj_variants(
    api_key: str,
    product_ids: list[str],
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    shop_id: str | None = None,
) -> dict:
    """Read exact TYMotors product connections in one authorized CJ shop.

    A unique identifier mapping is not a supplier offer, shipping quote or
    authorization to create a CJ order. No API write endpoint is used here.
    """
    if (not isinstance(product_ids, list) or not 1 <= len(product_ids) <= MAX_RESOLVE_PRODUCTS
            or any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value)
                   for value in product_ids)):
        return {"status": "invalid_request", "products": {}}
    unique_ids = list(dict.fromkeys(product_ids))
    unavailable = {product_id: {"status": "unavailable"} for product_id in unique_ids}
    if not isinstance(shop_id, str) or not shop_id.strip():
        return {"status": "shop_not_configured", "products": unavailable}
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", shop_id):
        return {"status": "invalid_request", "products": unavailable}
    if not api_key:
        return {"status": "not_configured", "products": unavailable}

    deadline = _now() + CJ_CALL_BUDGET_SECONDS
    bypass_rate_limit = transport is not None
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            auth = await _cj_request(client, "POST", TOKEN_URL, deadline=deadline,
                                     bypass_rate_limit=bypass_rate_limit, json={"apiKey": api_key})
            auth_payload = auth.json()
            if not _cj_success(auth, auth_payload):
                return {"status": "unavailable" if auth.status_code == 429 or auth.status_code >= 500 else "rejected",
                        "products": unavailable}
            data = auth_payload.get("data")
            token = data.get("accessToken") if isinstance(data, dict) else None
            if not isinstance(token, str) or not token:
                return {"status": "invalid_response", "products": unavailable}
            if _contains_secret(shop_id, (api_key, token)):
                return {"status": "api_authenticated", "products": unavailable}
            headers = {"CJ-Access-Token": token}
            shop_response = await _cj_request(client, "GET", SHOPS_URL, deadline=deadline,
                                              bypass_rate_limit=bypass_rate_limit, headers=headers)
            shop_payload = shop_response.json()
            if not _cj_success(shop_response, shop_payload) or not isinstance(shop_payload.get("data"), list):
                return {"status": "api_authenticated", "products": unavailable}
            authorized = [shop for shop in shop_payload["data"] if
                isinstance(shop, dict) and shop.get("id") == shop_id and shop.get("status") == 1
            ]
            if len(authorized) != 1:
                return {"status": "api_authenticated", "products": unavailable}

            products = {}
            for product_id in unique_ids:
                records = []
                total = None
                product_status = "unavailable"
                for page in range(1, MAX_CONNECTION_PAGES + 1):
                    response = await _cj_request(client, "GET", CONNECTIONS_URL,
                                                 deadline=deadline, bypass_rate_limit=bypass_rate_limit,
                                                 headers=headers, params={
                        "shopId": shop_id, "platformProductId": product_id,
                        "page": page, "pageSize": CONNECTION_PAGE_SIZE,
                    })
                    if response.status_code == 429:
                        return {"status": "unavailable", "products": unavailable}
                    payload = response.json()
                    data = payload.get("data") if _cj_success(response, payload) else None
                    if not isinstance(data, dict):
                        break
                    count, batch = data.get("total"), data.get("list")
                    if (type(count) is not int or count < 0 or count > MAX_CONNECTION_PAGES * CONNECTION_PAGE_SIZE
                            or not isinstance(batch, list) or len(batch) > CONNECTION_PAGE_SIZE
                            or (total is not None and count != total)):
                        break
                    total = count
                    if count == 0:
                        product_status = "missing" if not batch else "unavailable"
                        break
                    safe_batch = [_safe_connection(row, product_id, shop_id) for row in batch]
                    if not batch or any(row is None for row in safe_batch):
                        break
                    records.extend(safe_batch)
                    if len(records) > count:
                        break
                    if len(records) == count:
                        product_status = "mapped" if count == 1 else "ambiguous"
                        break
                entry = {"status": product_status}
                if product_status == "mapped":
                    entry["connection"] = records[0]
                products[product_id] = entry
            name = authorized[0].get("name")
            return {"status": "api_authenticated", "products": products, "shop_id": shop_id,
                    "shop_name": name if (isinstance(name, str) and 0 < len(name) <= 50
                                           and not _contains_secret(name, (api_key, token))) else None}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        return {"status": "unavailable", "products": unavailable}


async def probe_cj_auth(api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if not api_key:
        return {"status": "not_configured"}
    deadline = _now() + CJ_CALL_BUDGET_SECONDS
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            response = await _cj_request(client, "POST", TOKEN_URL, deadline=deadline,
                                         bypass_rate_limit=transport is not None, json={"apiKey": api_key})
            payload = response.json()
    except (httpx.HTTPError, TimeoutError, ValueError):
        return {"status": "unavailable"}

    if response.status_code == 429 or response.status_code >= 500:
        return {"status": "unavailable"}
    if not isinstance(payload, dict):
        return {"status": "invalid_response"}
    if _cj_success(response, payload) and isinstance(payload.get("data"), dict):
        token = payload["data"].get("accessToken")
        if isinstance(token, str) and token:
            return {"status": "api_authenticated"}
    auth_data = payload.get("data")
    auth_token = auth_data.get("accessToken") if isinstance(auth_data, dict) else None
    request_id = _safe_request_id(payload, tuple(value for value in (api_key, auth_token)
                                                 if isinstance(value, str)))
    return {"status": "rejected", **({"request_id": request_id} if request_id else {})}


async def probe_cj_connections(api_key: str, transport: httpx.AsyncBaseTransport | None = None,
                               *, shop_id: str | None = None) -> dict:
    """Count connections in one explicitly chosen authorized shop, never all shops."""
    if not api_key:
        return {"status": "not_configured"}
    if shop_id is not None and (not isinstance(shop_id, str)
                                or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", shop_id)):
        return {"status": "invalid_request", "mapping_status": "shop_not_authorized"}
    deadline = _now() + CJ_CALL_BUDGET_SECONDS
    bypass_rate_limit = transport is not None
    failure_stage = None
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            auth = await _cj_request(client, "POST", TOKEN_URL, deadline=deadline,
                                     bypass_rate_limit=bypass_rate_limit, json={"apiKey": api_key})
            auth_payload = auth.json()
            token = auth_payload.get("data", {}).get("accessToken") if _cj_success(auth, auth_payload) and isinstance(auth_payload.get("data"), dict) else None
            if not isinstance(token, str) or not token:
                return {"status": "unavailable" if auth.status_code == 429 or auth.status_code >= 500 else "rejected"}
            headers = {"CJ-Access-Token": token}
            failure_stage = "shops"
            shops_response = await _cj_request(client, "GET", SHOPS_URL, deadline=deadline,
                                               bypass_rate_limit=bypass_rate_limit, headers=headers)
            try:
                shops_payload = shops_response.json()
            except ValueError:
                shops_payload = None
            if not _cj_success(shops_response, shops_payload) or not isinstance(shops_payload.get("data"), list):
                return {"status": "api_authenticated", "mapping_status": "unavailable",
                        "diagnostics": _probe_failure("shops", shops_response, shops_payload,
                                                       (api_key, token))}
            shops = []
            for shop in shops_payload["data"]:
                if (isinstance(shop, dict) and shop.get("status") == 1
                        and isinstance(shop.get("id"), str)
                        and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", shop["id"])
                        and not _contains_secret(shop["id"], (api_key, token))):
                    name = shop.get("name")
                    shops.append({"id": shop["id"], "name": name if (isinstance(name, str)
                        and len(name) <= 200 and not _contains_secret(name, (api_key, token))) else ""})
            if shop_id is None:
                return {"status": "api_authenticated", "mapping_status": "shop_not_configured", "shops": shops}
            if not any(shop["id"] == shop_id for shop in shops):
                return {"status": "api_authenticated", "mapping_status": "shop_not_authorized", "shops": shops}
            failure_stage = "connections"
            response = await _cj_request(client, "GET", CONNECTIONS_URL,
                                         deadline=deadline, bypass_rate_limit=bypass_rate_limit,
                                         headers=headers, params={"shopId": shop_id, "page": 1, "pageSize": 1})
            try:
                payload = response.json()
            except ValueError:
                payload = None
            data = payload.get("data") if _cj_success(response, payload) else None
            total = data.get("total") if isinstance(data, dict) else None
            rows = data.get("list") if isinstance(data, dict) else None
            if (type(total) is not int or total < 0 or not isinstance(rows, list)
                    or (total == 0 and rows)
                    or (total > 0 and (len(rows) != 1 or not isinstance(rows[0], dict)
                                       or rows[0].get("shopId") != shop_id))):
                return {"status": "api_authenticated", "mapping_status": "unavailable",
                        "diagnostics": _probe_failure("connections", response, payload,
                                                       (api_key, token))}
            return {"status": "api_authenticated", "mapping_status": "connected" if total else "no_products",
                    "connected_variants": total, "shop_id": shop_id, "authorized_shops": 1}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        if failure_stage:
            return {"status": "api_authenticated", "mapping_status": "unavailable",
                    "diagnostics": _probe_failure(failure_stage)}
        return {"status": "unavailable"}
