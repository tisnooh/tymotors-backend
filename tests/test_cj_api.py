import asyncio
import json

import httpx

import app.cj_api as cj_api
from app.cj_api import TOKEN_URL, SHOPS_URL, CONNECTIONS_URL, probe_cj_auth, probe_cj_connections, resolve_cj_variants


def test_cj_auth_probe_never_returns_tokens_or_key():
    def handler(request):
        assert str(request.url) == TOKEN_URL
        assert request.method == "POST"
        assert json.loads(request.read()) == {"apiKey": "private-key"}
        return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "private-token"}})

    result = asyncio.run(probe_cj_auth("private-key", httpx.MockTransport(handler)))
    assert result == {"status": "api_authenticated"}
    assert "private" not in repr(result)


def test_cj_auth_probe_distinguishes_missing_and_rejected_credentials():
    assert asyncio.run(probe_cj_auth("")) == {"status": "not_configured"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"code": 1601000, "result": False, "requestId": "trace-1", "data": None}))
    assert asyncio.run(probe_cj_auth("bad-key", transport)) == {"status": "rejected", "request_id": "trace-1"}
    outage = httpx.MockTransport(lambda request: httpx.Response(503, json={"message": "Unavailable"}))
    assert asyncio.run(probe_cj_auth("private-key", outage)) == {"status": "unavailable"}


def test_cj_connection_probe_reports_real_mapping_count_without_exposing_token():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "private-token"}})
        assert request.headers["CJ-Access-Token"] == "private-token"
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": [{"id": "shop-1", "name": "TYMotors", "status": 1}, {"id": "shop-2", "status": 2}]})
        assert request.url.path == httpx.URL(CONNECTIONS_URL).path
        assert request.url.params["shopId"] == "shop-1"
        return httpx.Response(200, json={"code": 200, "result": True, "data": {"total": 2, "list": [{"shopId": "shop-1"}]}})

    result = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(handler), shop_id="shop-1"))
    assert result == {"status": "api_authenticated", "mapping_status": "connected", "connected_variants": 2, "shop_id": "shop-1", "authorized_shops": 1}
    assert len(seen) == 3
    assert "private" not in repr(result)


def test_cj_connection_probe_does_not_claim_mapping_when_cj_has_none_or_errors():
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": [{"id": "shop-1", "name": "TYMotors", "status": 1}]})
        return httpx.Response(200, json={"code": 200, "result": True, "data": {"total": 0, "list": []}})

    assert asyncio.run(probe_cj_connections("key", httpx.MockTransport(handler), shop_id="shop-1"))["mapping_status"] == "no_products"
    no_shop = asyncio.run(probe_cj_connections("key", httpx.MockTransport(handler)))
    assert no_shop == {"status": "api_authenticated", "mapping_status": "shop_not_configured",
                       "shops": [{"id": "shop-1", "name": "TYMotors"}]}

    def failed_connections(request):
        if str(request.url) == CONNECTIONS_URL.split("?")[0] or request.url.path == httpx.URL(CONNECTIONS_URL).path:
            return httpx.Response(503, json={"message": "outage"})
        return handler(request)

    result = asyncio.run(probe_cj_connections("key", httpx.MockTransport(failed_connections), shop_id="shop-1"))
    assert result["status"] == "api_authenticated"
    assert result["mapping_status"] == "unavailable"
    assert "connected_variants" not in result


def test_cj_connection_probe_requires_exact_authorized_shop_and_valid_result():
    calls = []

    def handler(request):
        calls.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "private-token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                "data": [{"id": "shop-1", "name": "TYMotors", "status": 1},
                         {"id": "shop-2", "name": "Other", "status": 1}]})
        assert request.url.params["shopId"] == "shop-2"
        return httpx.Response(200, json={"code": 200, "result": True, "data": {"total": 9, "list": [{"shopId": "shop-2"}]}})

    transport = httpx.MockTransport(handler)
    not_authorized = asyncio.run(probe_cj_connections("key", transport, shop_id="shop-3"))
    assert not_authorized["mapping_status"] == "shop_not_authorized"
    assert "connected_variants" not in not_authorized
    assert len(calls) == 2
    selected = asyncio.run(probe_cj_connections("key", transport, shop_id="shop-2"))
    assert selected["connected_variants"] == 9
    assert selected["shop_id"] == "shop-2"

    def false_handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": False, "data": {"accessToken": "private-token"}})
        raise AssertionError("Failed auth must not query shops")

    assert asyncio.run(probe_cj_auth("key", httpx.MockTransport(false_handler)))["status"] == "rejected"
    assert asyncio.run(probe_cj_connections("key", httpx.MockTransport(false_handler), shop_id="shop-1"))["status"] == "rejected"

    def bool_total(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "private-token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": [{"id": "shop-1", "status": 1}]})
        return httpx.Response(200, json={"code": 200, "result": True, "data": {"total": True, "list": []}})

    assert asyncio.run(probe_cj_connections("key", httpx.MockTransport(bool_total), shop_id="shop-1"))["mapping_status"] == "unavailable"


def test_cj_connection_probe_reports_safe_shops_failure_diagnostics():
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        assert str(request.url) == SHOPS_URL
        return httpx.Response(200, json={"code": 1600100, "result": False,
                                         "requestId": "trace:shops-1", "message": "private-token",
                                         "data": {"debug": "private-key"}})

    result = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(handler), shop_id="shop-1"))
    assert result == {"status": "api_authenticated", "mapping_status": "unavailable",
                      "diagnostics": {"stage": "shops", "http_status": 200,
                                      "code": 1600100, "request_id": "trace:shops-1"}}
    assert "private" not in repr(result)

    def gateway_handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        return httpx.Response(200, text="<html>private-token</html>")

    gateway = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(gateway_handler), shop_id="shop-1"))
    assert gateway == {"status": "api_authenticated", "mapping_status": "unavailable",
                       "diagnostics": {"stage": "shops", "http_status": 200}}

    def network_handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        raise httpx.ConnectError("private-token", request=request)

    network = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(network_handler), shop_id="shop-1"))
    assert network == {"status": "api_authenticated", "mapping_status": "unavailable",
                       "diagnostics": {"stage": "shops"}}


def test_cj_connection_probe_reports_safe_connection_failure_diagnostics():
    def run_connections(response):
        def handler(request):
            if str(request.url) == TOKEN_URL:
                return httpx.Response(200, json={"code": 200, "result": True,
                                                 "data": {"accessToken": "private-token"}})
            if str(request.url) == SHOPS_URL:
                return httpx.Response(200, json={"code": 200, "result": True,
                                                 "data": [{"id": "shop-1", "status": 1}]})
            return response
        return asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(handler), shop_id="shop-1"))

    limited = run_connections(httpx.Response(429, json={"code": 1600100,
        "result": False, "requestId": "trace-429", "message": "private-key"}))
    assert limited["diagnostics"] == {"stage": "connections", "http_status": 429,
                                       "code": 1600100, "request_id": "trace-429"}
    assert limited["mapping_status"] == "unavailable"

    malformed = run_connections(httpx.Response(200, json={"code": 200, "result": True,
        "data": {"total": "2", "list": []}, "requestId": "trace-format"}))
    assert malformed["diagnostics"] == {"stage": "connections", "http_status": 200,
                                         "code": 200, "request_id": "trace-format"}

    hostile = run_connections(httpx.Response(200, json={"code": True, "result": False,
        "requestId": "secret\nAuthorization: token", "message": "private-token"}))
    assert hostile["diagnostics"] == {"stage": "connections", "http_status": 200}
    assert "secret" not in repr(hostile) and "private" not in repr(hostile)

    token_as_id = run_connections(httpx.Response(200, json={"code": 1600100,
        "result": False, "requestId": "trace-private-token"}))
    assert token_as_id["diagnostics"] == {"stage": "connections", "http_status": 200,
                                           "code": 1600100}

    hash_id = run_connections(httpx.Response(200, json={"code": 1600100,
        "result": False, "requestId": "trace#42"}))
    assert hash_id["diagnostics"] == {"stage": "connections", "http_status": 200,
                                       "code": 1600100}

    invalid_json = run_connections(httpx.Response(502, text="private-token"))
    assert invalid_json["diagnostics"] == {"stage": "connections", "http_status": 502}


def test_cj_auth_probe_filters_untrusted_request_id():
    response = httpx.Response(200, json={"code": 1601000, "result": False,
                                         "requestId": {"token": "private-token"}})
    result = asyncio.run(probe_cj_auth("private-key", httpx.MockTransport(lambda _request: response)))
    assert result == {"status": "rejected"}

    for unsafe_id in ("private-key", "private-token"):
        response = httpx.Response(200, json={"code": 1601000, "result": False,
                                             "requestId": unsafe_id,
                                             "data": {"accessToken": "private-token"}})
        result = asyncio.run(probe_cj_auth("private-key", httpx.MockTransport(lambda _request: response)))
        assert result == {"status": "rejected"}

    malformed_token = httpx.Response(200, json={"code": 200, "result": True,
                                                  "data": {"accessToken": {"secret": "private-token"}}})
    assert asyncio.run(probe_cj_auth("private-key",
        httpx.MockTransport(lambda _request: malformed_token))) == {"status": "rejected"}


def test_cj_shops_and_resolver_never_expose_known_secrets():
    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        assert str(request.url) == SHOPS_URL
        return httpx.Response(200, json={"code": 200, "result": True, "data": [
            {"id": "shop-1", "name": "TY private-token Motors", "status": 1},
            {"id": "private-key-2", "name": "Other", "status": 1},
            {"id": "private-token-3", "name": "Other", "status": 1},
            {"id": "shop-4", "name": "Store private-key", "status": 1},
        ]})

    result = asyncio.run(probe_cj_connections("private-key", httpx.MockTransport(handler)))
    assert result == {"status": "api_authenticated", "mapping_status": "shop_not_configured",
                      "shops": [{"id": "shop-1", "name": ""}, {"id": "shop-4", "name": ""}]}
    assert "private" not in repr(result)

    transport, _ = _resolve_transport({"ty-product-1": {"code": 200, "result": True,
        "data": {"total": 1, "list": [_connection()]} }},
        shops={"code": 200, "result": True,
               "data": [{"id": "shop-1", "name": "TY private-token Motors", "status": 1}]})
    resolved = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], transport,
                                               shop_id="shop-1"))
    assert resolved["products"]["ty-product-1"]["status"] == "mapped"
    assert resolved["shop_name"] is None
    assert "private" not in repr(resolved)


def _connection(product="ty-product-1", shop="shop-1", variant="TY-SKU-1"):
    return {"shopId": shop, "platformProductId": product, "platformVariantId": variant,
            "cjProductId": "cj-product-1", "cjVariantId": "cj-variant-1", "cjSku": "CJ-SKU-1",
            "sourceCountryCode": "CN", "targetCountryCode": "FR", "logistics": "CJPacket",
            "title": "This unverified title must not become output", "accessToken": "secret-in-row"}


def _resolve_transport(connections, *, shops=None, auth=None):
    calls = []

    def handler(request):
        calls.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json=auth or {"code": 200, "result": True, "data": {"accessToken": "private-token"}})
        assert request.headers["CJ-Access-Token"] == "private-token"
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json=shops or {"code": 200, "result": True,
                "data": [{"id": "shop-1", "status": 1}, {"id": "shop-2", "status": 1}]})
        assert request.url.path == httpx.URL(CONNECTIONS_URL).path
        assert request.method == "GET"
        assert request.url.params["shopId"] == "shop-1"
        assert request.url.params["pageSize"] == "100"
        key = request.url.params["platformProductId"]
        response = connections[key]
        return response(request) if callable(response) else httpx.Response(200, json=response)

    return httpx.MockTransport(handler), calls


def test_cj_variant_resolver_requires_selected_authorized_shop_before_network():
    def no_network(_request):
        raise AssertionError("No CJ call is allowed")

    transport = httpx.MockTransport(no_network)
    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], transport))
    assert result == {"status": "shop_not_configured", "products": {"ty-product-1": {"status": "unavailable"}}}
    assert asyncio.run(resolve_cj_variants("private-key", ["bad id"], transport, shop_id="shop-1"))["status"] == "invalid_request"
    assert asyncio.run(resolve_cj_variants("private-key", [f"id-{i}" for i in range(21)], transport, shop_id="shop-1"))["status"] == "invalid_request"
    assert asyncio.run(resolve_cj_variants("", ["ty-product-1"], transport, shop_id="shop-1"))["status"] == "not_configured"
    transport, calls = _resolve_transport({}, shops={"code": 200, "result": True, "data": [{"id": "shop-1", "status": 2}]})
    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], transport, shop_id="shop-1"))
    assert result["products"]["ty-product-1"]["status"] == "unavailable"
    assert len(calls) == 2


def test_cj_variant_resolver_returns_only_exact_unique_mapping_and_no_token():
    transport, calls = _resolve_transport({
        "ty-product-1": {"code": 200, "result": True, "data": {"total": 1, "list": [_connection()]}},
        "ty-product-2": {"code": 200, "result": True, "data": {"total": 0, "list": []}},
    })
    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1", "ty-product-2", "ty-product-1"], transport, shop_id="shop-1"))
    assert result["status"] == "api_authenticated"
    assert result["products"]["ty-product-1"]["status"] == "mapped"
    assert result["products"]["ty-product-1"]["connection"] == {
        field: _connection().get(field) for field in (
            "shopId", "platformProductId", "platformVariantId", "cjProductId",
            "cjVariantId", "cjSku", "sourceCountryCode", "targetCountryCode", "logistics")}
    assert result["products"]["ty-product-2"] == {"status": "missing"}
    assert len(calls) == 4  # auth, shops, one exact query per distinct product
    assert "private" not in repr(result)
    assert "secret" not in repr(result)
    assert "unverified title" not in repr(result)


def test_cj_variant_resolver_rejects_ambiguous_and_cross_product_responses():
    transport, _ = _resolve_transport({
        "ty-product-1": {"code": 200, "result": True, "data": {"total": 2, "list": [_connection(), _connection(variant="TY-SKU-2")]}},
        "ty-product-2": {"code": 200, "result": True, "data": {"total": 1, "list": [_connection(product="other-product")]}},
    })
    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1", "ty-product-2"], transport, shop_id="shop-1"))
    assert result["products"]["ty-product-1"] == {"status": "ambiguous"}
    assert result["products"]["ty-product-2"] == {"status": "unavailable"}


def test_cj_variant_resolver_fails_closed_for_malformed_or_failed_responses():
    responses = [
        {"code": 200, "result": False, "data": {"total": 1, "list": [_connection()]}},
        {"code": 200, "result": True, "data": {"total": "1", "list": [_connection()]}},
        {"code": 200, "result": True, "data": {"total": 1, "list": []}},
        {"code": 200, "result": True, "data": {"total": 301, "list": [_connection()]}},
        {"code": 200, "result": True, "data": {"total": 1, "list": [_connection(shop="shop-2")]}},
    ]
    for bad in responses:
        transport, _ = _resolve_transport({"ty-product-1": bad})
        result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], transport, shop_id="shop-1"))
        assert result["products"]["ty-product-1"] == {"status": "unavailable"}
    outage, _ = _resolve_transport({"ty-product-1": lambda _request: httpx.Response(503, json={"message": "down"})})
    assert asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], outage, shop_id="shop-1"))["products"]["ty-product-1"] == {"status": "unavailable"}
    rejected, _ = _resolve_transport({}, auth={"code": 1601000, "result": False, "data": None})
    assert asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], rejected, shop_id="shop-1"))["status"] == "rejected"


def test_cj_variant_resolver_paginates_with_a_bounded_budget():
    rows = [_connection(variant=f"TY-{i}") for i in range(101)]

    def paged(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"code": 200, "result": True,
            "data": {"total": 101, "list": rows[(page - 1) * 100:page * 100]}})

    transport, calls = _resolve_transport({"ty-product-1": paged})
    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1"], transport, shop_id="shop-1"))
    assert result["products"]["ty-product-1"] == {"status": "ambiguous"}
    assert len(calls) == 4


def test_cj_rate_slot_spaces_requests_and_respects_deadline(monkeypatch):
    clock = [10.0]
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(cj_api, "_now", lambda: clock[0])
    monkeypatch.setattr(cj_api, "_sleep", fake_sleep)
    monkeypatch.setattr(cj_api, "_next_cj_request_at", 0.0)

    async def reserve():
        await cj_api._wait_for_cj_slot(20.0)
        first = clock[0]
        await cj_api._wait_for_cj_slot(20.0)
        second = clock[0]
        try:
            await cj_api._wait_for_cj_slot(11.5)
        except TimeoutError:
            return first, second
        raise AssertionError("A request must not start after its call budget")

    first, second = asyncio.run(reserve())
    assert second - first >= cj_api.CJ_REQUEST_INTERVAL_SECONDS
    assert slept == [1.0, 0.5]


def test_cj_resolver_discards_partial_mappings_on_global_budget_expiry(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(cj_api, "_now", lambda: clock[0])
    seen_products = []

    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": [{"id": "shop-1", "status": 1}]})
        product_id = request.url.params["platformProductId"]
        seen_products.append(product_id)
        assert product_id == "ty-product-1"
        clock[0] = 31.0
        return httpx.Response(200, json={"code": 200, "result": True,
                                         "data": {"total": 1, "list": [_connection()]}})

    result = asyncio.run(resolve_cj_variants("private-key", ["ty-product-1", "ty-product-2"],
                                             httpx.MockTransport(handler), shop_id="shop-1"))
    assert result == {"status": "unavailable", "products": {
        "ty-product-1": {"status": "unavailable"}, "ty-product-2": {"status": "unavailable"}}}
    assert seen_products == ["ty-product-1"]


def test_cj_resolver_stops_after_429_without_partial_mapping_or_retry():
    seen_products = []

    def handler(request):
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"accessToken": "private-token"}})
        if str(request.url) == SHOPS_URL:
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": [{"id": "shop-1", "status": 1}]})
        product_id = request.url.params["platformProductId"]
        seen_products.append(product_id)
        if product_id == "ty-product-1":
            return httpx.Response(200, json={"code": 200, "result": True,
                                             "data": {"total": 1, "list": [_connection()]}})
        assert product_id == "ty-product-2"
        return httpx.Response(429, json={"code": 429, "result": False})

    result = asyncio.run(resolve_cj_variants("private-key",
                                             ["ty-product-1", "ty-product-2", "ty-product-3"],
                                             httpx.MockTransport(handler), shop_id="shop-1"))
    assert result == {"status": "unavailable", "products": {
        product_id: {"status": "unavailable"}
        for product_id in ("ty-product-1", "ty-product-2", "ty-product-3")}}
    assert seen_products == ["ty-product-1", "ty-product-2"]
