import asyncio
import json

import httpx

from app.cj_api import TOKEN_URL, SHOPS_URL, CONNECTIONS_URL, probe_cj_auth, probe_cj_connections


def test_cj_auth_probe_never_returns_tokens_or_key():
    def handler(request):
        assert str(request.url) == TOKEN_URL
        assert request.method == "POST"
        assert json.loads(request.read()) == {"apiKey": "private-key"}
        return httpx.Response(200, json={"code": 200, "data": {"accessToken": "private-token"}})

    result = asyncio.run(probe_cj_auth("private-key", httpx.MockTransport(handler)))
    assert result == {"status": "api_authenticated"}
    assert "private" not in repr(result)


def test_cj_auth_probe_distinguishes_missing_and_rejected_credentials():
    assert asyncio.run(probe_cj_auth("")) == {"status": "not_configured"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 1601000, "requestId": "trace-1", "data": None}))
    assert asyncio.run(probe_cj_auth("bad-key", transport)) == {"status": "rejected", "request_id": "trace-1"}
    outage = httpx.MockTransport(lambda request: httpx.Response(503, json={"message": "Unavailable"}))
    assert asyncio.run(probe_cj_auth("private-key", outage)) == {"status": "unavailable"}


def test_cj_connection_probe_reports_real_mapping_count_without_exposing_token():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "data": {"accessToken": "private-token"}})
        assert request.headers["CJ-Access-Token"] == "private-token"
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "data": [{"id": "shop-1", "status": 1}, {"id": "shop-2", "status": 2}]})
        assert request.url.path == httpx.URL(CONNECTIONS_URL).path
        assert request.url.params["shopId"] == "shop-1"
        return httpx.Response(200, json={"code": 200, "data": {"total": 2, "list": []}})

    result = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(handler)))
    assert result == {"status": "api_authenticated", "mapping_status": "connected", "connected_variants": 2, "authorized_shops": 1}
    assert len(seen) == 3
    assert "private" not in repr(result)


def test_cj_connection_probe_does_not_claim_mapping_when_cj_has_none_or_errors():
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "data": {"accessToken": "token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "data": [{"id": "shop-1", "status": 1}]})
        return httpx.Response(200, json={"code": 200, "data": {"total": 0, "list": []}})

    assert asyncio.run(probe_cj_connections("key", httpx.MockTransport(handler)))["mapping_status"] == "no_products"

    def failed_connections(request):
        if str(request.url) == CONNECTIONS_URL.split("?")[0] or request.url.path == httpx.URL(CONNECTIONS_URL).path:
            return httpx.Response(503, json={"message": "outage"})
        return handler(request)

    result = asyncio.run(probe_cj_connections("key", httpx.MockTransport(failed_connections)))
    assert result["status"] == "api_authenticated"
    assert result["mapping_status"] == "unavailable"
    assert "connected_variants" not in result
