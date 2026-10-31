"""Read-only CJ API authentication probe. This never creates or pays for orders."""

import httpx


TOKEN_URL = "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken"


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
