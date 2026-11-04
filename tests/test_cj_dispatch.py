import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

import app.cj_dispatch as dispatch
from tests.test_cj_fulfillment import dossier


def valid_data():
    args = dossier()
    args[0]["order_number"] = "TY-FIXTURE-ORDER"
    args[0].update(status="paid", stock_applied_at="2026-11-03T12:00:00Z", stock_shortfall_at=None)
    args[2].update(approved_by="fixture-admin", approved_at="2026-11-03T12:01:00Z", agent_provider="CJdropshipping")
    args[4].update(shop_id="fixture-shop", shop_name="TYMotors")
    product_id = "10000000-0000-4000-8000-000000000001"
    args[1][0]["product_id"] = args[3][0]["product_id"] = product_id
    args[4]["products"][product_id] = args[4]["products"].pop("product-1")
    args[4]["products"][product_id]["connection"]["platformProductId"] = product_id
    return args


def args_product_id():
    return "10000000-0000-4000-8000-000000000001"


def test_unpaid_draft_preserves_exact_lines_without_authorizing_payment():
    preview = dispatch.draft_preview(*valid_data())
    assert preview["can_submit_draft"] is True
    assert preview["can_pay_supplier"] is False
    assert preview["warnings"]
    payload = preview["payload"]
    assert (payload["payType"], payload["orderFlow"], payload["isSandbox"]) == (3, 1, 0)
    assert payload["storeName"] == "TYMotors"
    assert payload["products"] == [{"vid": "fixture-variant", "sku": "FIXTURE-SKU", "quantity": 1,
                                    "storeLineItemId": "item-1", "storeProductId": args_product_id(), "storeSku": "TY-MIRROR"}]
    assert "email" not in payload and "shopAmount" not in payload and "iossType" not in payload


def test_free_diagnostic_unverified_supplier_and_wrong_mapping_remain_blocked():
    args = valid_data()
    args[0]["is_test"] = True
    args[2]["status"] = "pending_validation"
    args[4]["products"][args_product_id()]["connection"]["platformVariantId"] = "DIFFERENT-SKU"
    preview = dispatch.draft_preview(*args)
    assert not preview["can_submit_draft"] and preview["payload"] is None
    assert {"test_order_excluded", "supplier_approval_required", "cj_variant_mismatch"} <= {b["code"] for b in preview["blockers"]}


def test_draft_does_not_truncate_recipient_or_mix_shipping_routes():
    args = valid_data()
    args[0]["customer_name"] = "x" * 51
    preview = dispatch.draft_preview(*args)
    assert preview["payload"] is None
    assert {b["code"] for b in preview["blockers"]} == {"cj_field_length_or_type_invalid"}
    args = valid_data()
    args[4]["shop_name"] = None
    assert not dispatch.draft_preview(*args)["can_submit_draft"]


class MemoryDb:
    """Isolated orchestration fixture; SQL invariants tested separately in PGlite."""
    def __init__(self):
        self.row = None
        self.claimed = False
        self.calls = []

    async def select(self, table, *, params=None):
        assert table == "cj_order_submissions"
        return [deepcopy(self.row)] if self.row else []

    async def rpc(self, name, params):
        self.calls.append(name)
        if name == "admin_claim_cj_submission":
            self.row = {"id": "submission-1", "order_id": "order-1", "state": "reserved", "payload": params["p_payload"],
                        "fingerprint": params["p_fingerprint"], "cj_shop_id": params["p_cj_shop_id"]}
            return {"claimed": True, "submission": deepcopy(self.row)}
        if name == "admin_finish_cj_submission":
            self.row.update(state=params["p_state"], cj_order_id=params["p_cj_order_id"], request_id=params["p_request_id"])
            return deepcopy(self.row)
        if name == "admin_observe_cj_submission":
            self.row["observation"] = params["p_observation"]
            return deepcopy(self.row)
        raise AssertionError(name)


CFG = SimpleNamespace(cj_api_key="fixture-key", cj_shop_id="fixture-shop", environment="production", stripe_mode="live")


def prepared(monkeypatch):
    args = valid_data()
    preview = dispatch.draft_preview(*args)
    monkeypatch.setattr(dispatch, "load_draft_preview", AsyncMock(return_value=(args[0], preview)))
    return preview


def test_simulated_submit_then_repeat_and_status_sync_never_sends_second_order(monkeypatch):
    preview = prepared(monkeypatch)
    provider = AsyncMock(return_value={"status": "submitted", "cj_order_id": "cj-fixture-1", "request_id": "request-1"})
    monkeypatch.setattr(dispatch, "create_cj_order_draft", provider)
    monkeypatch.setattr(dispatch, "query_cj_order", AsyncMock(return_value={"status": "observed", "observation": {
        "shop_id": "fixture-shop", "order_id": "cj-fixture-1", "order_status": "CREATED", "tracking_number": None,
        "products": [{"store_line_item_id": "item-1", "vid": "fixture-variant", "quantity": 1}]}}))
    db = MemoryDb()

    async def flow():
        one = await dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"])
        two = await dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"])
        observed = await dispatch.refresh_draft(db, CFG, "admin", "order-1")
        return one, two, observed

    one, two, observed = asyncio.run(flow())
    assert one["reused"] is False and two["reused"] is True
    assert one["supplier_payment"] == "not_initiated"
    assert "payload" not in repr(one)
    assert observed["customer_tracking_updated"] is False
    assert provider.await_count == 1
    assert db.calls == ["admin_claim_cj_submission", "admin_finish_cj_submission", "admin_observe_cj_submission"]


def test_timeout_is_persisted_and_crashed_reservation_never_resends(monkeypatch):
    preview = prepared(monkeypatch)
    provider = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(dispatch, "create_cj_order_draft", provider)
    db = MemoryDb()

    async def flow():
        first = await dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"])
        again = await dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"])
        return first, again

    first, again = asyncio.run(flow())
    assert first["submission"]["state"] == "uncertain" and again["reused"]
    assert provider.await_count == 1
    db.row["state"] = "reserved"
    result = asyncio.run(dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"]))
    assert result["reused"] and provider.await_count == 1


def test_changed_dossier_never_claims_or_sends(monkeypatch):
    prepared(monkeypatch)
    provider = AsyncMock()
    monkeypatch.setattr(dispatch, "create_cj_order_draft", provider)
    db = MemoryDb()
    with pytest.raises(HTTPException) as error:
        asyncio.run(dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", "0" * 64))
    assert error.value.status_code == 409
    assert db.calls == []
    provider.assert_not_awaited()


def test_concurrent_reservation_loser_does_not_send(monkeypatch):
    preview = prepared(monkeypatch)
    db = MemoryDb()
    row = {"id": "existing", "order_id": "order-1", "state": "reserved"}
    db.rpc = AsyncMock(return_value={"claimed": False, "submission": row})
    provider = AsyncMock()
    monkeypatch.setattr(dispatch, "create_cj_order_draft", provider)
    result = asyncio.run(dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"]))
    assert result["reused"]
    provider.assert_not_awaited()


def test_wrong_shop_or_unavailable_status_never_overwrites_local_state(monkeypatch):
    db = MemoryDb()
    db.row = {"id": "existing", "order_id": "order-1", "state": "submitted", "cj_order_id": "cj-fixture", "cj_shop_id": "fixture-shop"}
    for result, expected_status in [({"status": "unavailable"}, 503),
        ({"status": "observed", "observation": {"shop_id": "other-shop"}}, 409)]:
        monkeypatch.setattr(dispatch, "query_cj_order", AsyncMock(return_value=result))
        with pytest.raises(HTTPException) as error:
            asyncio.run(dispatch.refresh_draft(db, CFG, "admin", "order-1"))
        assert error.value.status_code == expected_status
    assert not db.calls


def test_service_payload_is_accepted_by_actual_cj_adapter_using_simulated_transport(monkeypatch):
    from app.cj_orders import create_cj_order_draft, CREATE_ORDER_URL
    from app.cj_api import TOKEN_URL
    import json
    preview = prepared(monkeypatch)
    calls = []

    def provider(request):
        calls.append(str(request.url))
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={"code": 200, "result": True, "data": {"accessToken": "fixture-token"}})
        assert str(request.url) == CREATE_ORDER_URL
        payload = json.loads(request.content)
        assert payload == preview["payload"]
        assert payload["payType"] == 3
        return httpx.Response(200, json={"code": 200, "result": True, "data": {
            "orderId": "cj-fixture-1", "orderNumber": "TY-FIXTURE-ORDER"}, "requestId": "fixture-request"})

    async def send(api_key, payload):
        return await create_cj_order_draft(api_key, payload, transport=httpx.MockTransport(provider))

    monkeypatch.setattr(dispatch, "create_cj_order_draft", send)
    db = MemoryDb()
    result = asyncio.run(dispatch.submit_draft(db, CFG, "admin", "order-1", "timestamp", preview["fingerprint"]))
    assert result["submission"]["state"] == "submitted"
    assert calls == [TOKEN_URL, CREATE_ORDER_URL]


@pytest.mark.parametrize("environment,mode", [("test", "test"), ("staging", "live"), ("production", "test")])
def test_real_dispatch_is_disabled_in_non_live_environments(monkeypatch, environment, mode):
    preview = prepared(monkeypatch)
    db = MemoryDb()
    provider = AsyncMock()
    monkeypatch.setattr(dispatch, "create_cj_order_draft", provider)
    cfg = SimpleNamespace(cj_api_key="fixture-key", cj_shop_id="fixture-shop", environment=environment, stripe_mode=mode)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dispatch.submit_draft(db, cfg, "admin", "order-1", "timestamp", preview["fingerprint"]))
    assert error.value.status_code == 409 and db.calls == []
    provider.assert_not_awaited()
