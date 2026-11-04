"""CJ order draft tests use MockTransport only; no provider call is made."""

import asyncio
import json

import httpx

from app.cj_api import TOKEN_URL
from app.cj_orders import CREATE_ORDER_URL, ORDER_DETAIL_URL, create_cj_order_draft, query_cj_order


def _payload():
    return {
        "orderNumber": "TY-20261103-FIXTURE", "shippingZip": "75001",
        "shippingCountry": "France", "shippingCountryCode": "FR",
        "shippingProvince": "Paris", "shippingCity": "Paris",
        "shippingCustomerName": "Fixture Client", "shippingAddress": "1 rue Exemple",
        "logisticName": "CJPacket", "fromCountryCode": "CN", "storeName": "TYMotors",
        "payType": 3, "orderFlow": 1, "isSandbox": 0,
        "platform": "Api", "shopLogisticsType": 2,
        "products": [{"vid": "CJ-VARIANT-1", "sku": "CJ-SKU-1", "quantity": 1,
                      "storeLineItemId": "item-1", "storeProductId": "7c1b2c09-cf4d-45f5-839c-2e2c9558ca1d",
                      "storeSku": "TY-SKU-1"}],
    }


def _auth():
    return httpx.Response(200, json={"code": 200, "result": True,
                                     "data": {"accessToken": "private-token"}})


def test_draft_posts_once_only_to_create_order_v2_without_payment():
    requests = []

    def handler(request):
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            assert json.loads(request.read()) == {"apiKey": "private-key"}
            return _auth()
        assert str(request.url) == CREATE_ORDER_URL
        assert request.method == "POST"
        assert request.headers["CJ-Access-Token"] == "private-token"
        sent = json.loads(request.read())
        assert sent == _payload()
        assert type(sent["payType"]) is int and sent["payType"] == 3
        return httpx.Response(200, json={"code": 200, "result": True, "requestId": "trace-1",
                                         "data": {"orderId": "CJ-ORDER-1", "orderNumber": sent["orderNumber"],
                                                  "cjPayUrl": "https://should-never-be-returned.invalid"}})

    result = asyncio.run(create_cj_order_draft("private-key", _payload(), httpx.MockTransport(handler)))
    assert result == {"status": "submitted", "cj_order_id": "CJ-ORDER-1", "request_id": "trace-1"}
    assert [request.method for request in requests] == ["POST", "POST"]
    assert "private" not in repr(result)
    assert "should-never" not in repr(result)


def test_invalid_payment_controls_and_line_items_are_rejected_without_network():
    def no_network(_request):
        raise AssertionError("Invalid draft must not call CJ")

    transport = httpx.MockTransport(no_network)
    for change in (
        {"payType": 2}, {"payType": "3"}, {"orderFlow": 2}, {"isSandbox": 1},
        {"platform": "Shopify"}, {"shopLogisticsType": 1}, {"shopLogisticsType": "2"},
        {"shippingCountryCode": "US"}, {"shippingCountry": "Belgium"}, {"products": []},
        {"products": [{**_payload()["products"][0], "storeProductId": "not-uuid"}]},
        {"products": [{**_payload()["products"][0], "quantity": 0}]},
        {"products": [{**_payload()["products"][0], "quantity": True}]},
        {"products": [{**_payload()["products"][0], "payType": 3}]},
        {"payBalance": True},
    ):
        payload = {**_payload(), **change}
        assert asyncio.run(create_cj_order_draft("key", payload, transport)) == {"status": "rejected"}
    assert asyncio.run(create_cj_order_draft("", _payload(), transport)) == {"status": "not_configured"}


def test_auth_failure_before_order_post_never_submits():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == TOKEN_URL
        return httpx.Response(401, json={"code": 1601000, "result": False,
                                         "requestId": "auth-failed", "data": None})

    result = asyncio.run(create_cj_order_draft("bad-key", _payload(), httpx.MockTransport(handler)))
    assert result == {"status": "rejected", "request_id": "auth-failed"}
    assert len(requests) == 1


def test_any_ambiguous_create_response_is_uncertain_and_never_retried():
    def run(post_response):
        submitted = []

        def handler(request):
            if str(request.url) == TOKEN_URL:
                return _auth()
            assert str(request.url) == CREATE_ORDER_URL
            submitted.append(request)
            return post_response(request) if callable(post_response) else post_response

        result = asyncio.run(create_cj_order_draft("key", _payload(), httpx.MockTransport(handler)))
        assert len(submitted) == 1
        assert result["status"] == "uncertain"

    run(httpx.Response(429, json={"code": 1600200, "result": False, "requestId": "rate-1"}))
    run(httpx.Response(200, json={"code": 1600100, "result": False, "message": "ORDER_CODE_EXIST"}))
    run(httpx.Response(503, json={"message": "unavailable"}))
    run(httpx.Response(200, text="not JSON"))
    run(httpx.Response(200, json={"code": 200, "result": True, "data": {"orderId": ""}}))
    run(httpx.Response(200, json={"code": 200, "result": True,
                                  "data": {"orderId": "CJ-ORDER-1", "orderNumber": "DIFFERENT"}}))

    def timeout(request):
        raise httpx.ReadTimeout("provider did not respond", request=request)

    run(timeout)


def test_detail_query_returns_only_matching_order_and_whitelisted_observation():
    requests = []

    def handler(request):
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            return _auth()
        assert request.method == "GET" and request.url.path == httpx.URL(ORDER_DETAIL_URL).path
        assert request.url.params["orderId"] == "CJ-ORDER-1"
        assert request.headers["CJ-Access-Token"] == "private-token"
        return httpx.Response(200, json={"code": 200, "result": True, "data": {
            "orderId": "CJ-ORDER-1", "orderNum": "TY-20261103-FIXTURE", "shopId": "shop-1",
            "orderStatus": "CREATED", "subStatus": None, "logisticName": "CJPacket",
            "trackNumber": None, "trackingProvider": None,
            "shippingAddress": "private customer address", "shippingPhone": "private phone",
            "productList": [{"vid": "CJ-VARIANT-1", "quantity": 1,
                             "storeLineItemId": "item-1", "sellPrice": 999}],
        }})

    result = asyncio.run(query_cj_order("key", "CJ-ORDER-1", httpx.MockTransport(handler)))
    assert result == {"status": "observed", "observation": {
        "order_id": "CJ-ORDER-1", "shop_id": "shop-1", "order_number": "TY-20261103-FIXTURE",
        "order_status": "CREATED", "sub_status": None, "tracking_number": None,
        "tracking_provider": None, "logistic_name": "CJPacket",
        "products": [{"vid": "CJ-VARIANT-1", "quantity": 1, "store_line_item_id": "item-1"}],
    }}
    assert len(requests) == 2
    assert "private" not in repr(result)
    assert "999" not in repr(result)


def test_detail_query_rejects_cross_order_and_malformed_responses():
    def run(detail_response):
        def handler(request):
            if str(request.url) == TOKEN_URL:
                return _auth()
            return detail_response

        return asyncio.run(query_cj_order("key", "CJ-ORDER-1", httpx.MockTransport(handler)))

    assert run(httpx.Response(200, json={"code": 200, "result": True, "data": {
        "orderId": "SOMEONE-ELSE", "shopId": "shop-1", "orderStatus": "CREATED",
        "productList": [{"vid": "CJ-VARIANT-1", "quantity": 1}],
    }})) == {"status": "unavailable"}
    assert run(httpx.Response(200, json={"code": 200, "result": True, "data": {
        "orderId": "CJ-ORDER-1", "shopId": None, "orderStatus": "CREATED",
        "productList": [{"vid": "CJ-VARIANT-1", "quantity": 1}],
    }})) == {"status": "unavailable"}
    assert run(httpx.Response(200, json={"code": 200, "result": True, "data": {
        "orderId": "CJ-ORDER-1", "shopId": "shop-1", "orderStatus": "CREATED",
        "productList": [{"vid": "CJ-VARIANT-1", "quantity": 1}],
    }})) == {"status": "unavailable"}
    assert run(httpx.Response(429, json={"code": 1600200, "result": False})) == {"status": "unavailable"}
    assert run(httpx.Response(200, text="not JSON")) == {"status": "unavailable"}

    def no_network(_request):
        raise AssertionError("Invalid query must not call CJ")

    assert asyncio.run(query_cj_order("key", "../other", httpx.MockTransport(no_network))) == {"status": "rejected"}
    assert asyncio.run(query_cj_order("", "CJ-ORDER-1", httpx.MockTransport(no_network))) == {"status": "not_configured"}
