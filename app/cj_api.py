"""Read-only CJ API authentication probe. This never creates or pays for orders."""

import httpx


TOKEN_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"
SHOPS_URL = "https://developers.cjdropshipping.com/api2.0/v1/shop/getShops"
CONNECTIONS_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/conn/connection"


async def probe_cj_auth(api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if not api_key:
        return {"status": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            response = await client.post(TOKEN_URL, json={"apiKey": api_key})
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"status": "unavailable"}

    if response.status_code >= 500:
        return {"status": "unavailable"}
    if not isinstance(payload, dict):
        return {"status": "invalid_response"}
    if response.status_code == 200 and payload.get("code") in (0, 200) and isinstance(payload.get("data"), dict):
        if payload["data"].get("accessToken"):
            return {"status": "api_authenticated"}
    return {"status": "rejected", "request_id": payload.get("requestId")}


async def probe_cj_connections(api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Read CJ's real shop/variant connections; never upload products or orders."""
    if not api_key:
        return {"status": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            auth = await client.post(TOKEN_URL, json={"apiKey": api_key})
            auth_payload = auth.json()
            token = auth_payload.get("data", {}).get("accessToken") if isinstance(auth_payload, dict) and isinstance(auth_payload.get("data"), dict) else None
            if auth.status_code != 200 or auth_payload.get("code") not in (0, 200) or not token:
                return {"status": "unavailable" if auth.status_code >= 500 else "rejected"}
            headers = {"CJ-Access-Token": token}
            shops_response = await client.get(SHOPS_URL, headers=headers)
            shops_payload = shops_response.json()
            if shops_response.status_code != 200 or shops_payload.get("code") not in (0, 200) or not isinstance(shops_payload.get("data"), list):
                return {"status": "api_authenticated", "mapping_status": "unavailable"}
            shops = [shop for shop in shops_payload["data"] if isinstance(shop, dict) and shop.get("status") == 1]
            if not shops:
                return {"status": "api_authenticated", "mapping_status": "no_authorized_shop", "connected_variants": 0}
            counts = []
            for shop in shops:
                shop_id = str(shop.get("id") or "")
                if not shop_id:
                    continue
                response = await client.get(CONNECTIONS_URL, headers=headers, params={"shopId": shop_id, "page": 1, "pageSize": 1})
                payload = response.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                total = data.get("total") if isinstance(data, dict) else None
                if response.status_code != 200 or payload.get("code") not in (0, 200) or not isinstance(total, int) or total < 0:
                    return {"status": "api_authenticated", "mapping_status": "unavailable"}
                counts.append(total)
            if len(counts) != len(shops):
                return {"status": "api_authenticated", "mapping_status": "unavailable"}
            total = sum(counts)
            return {"status": "api_authenticated", "mapping_status": "connected" if total else "no_products", "connected_variants": total, "authorized_shops": len(shops)}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return {"status": "unavailable"}
