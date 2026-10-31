import asyncio

import httpx

from app.cj_api import TOKEN_URL, probe_cj_auth


def test_cj_auth_probe_never_returns_tokens_or_key():
    def handler(request):
        assert str(request.url) == TOKEN_URL
        assert request.method == "POST"
        assert request.read() == b'{"apiKey":"private-key"}'
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
