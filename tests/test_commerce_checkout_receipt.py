"""Pending confirmation lookup: no provider calls or payment side effects."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.commerce_checkout_receipt import checkout_receipt_order

SID='cs_test_receipt_fixture'
GUEST='synthetic_receipt_owner'


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.fixture
def store():
    oid,qid,aid=[str(uuid4()) for _ in range(3)]
    data={
        'legacy':[],
        'commerce_test_sessions':[{'session_id':SID,'attempt_id':aid}],
        'commerce_checkout_attempts':[{'id':aid,'order_id':oid,'commerce_quote_id':qid,
            'session_id':None,'is_test':True}],
        'orders':[{'id':oid,'commerce_quote_id':qid,'user_id':None,'guest_session_id':GUEST,
            'is_test':True,'stripe_session_id':None,'status':'pending','payment_status':'unpaid'}],
        'commerce_quotes':[{'id':qid,'owner_user_id':None,'owner_guest_session':GUEST}],
    }
    async def select(table,*,params):
        assert params['limit']==2
        return deepcopy(data['legacy'] if table=='orders' and 'stripe_session_id' in params else data[table])
    return SimpleNamespace(data=data,select=AsyncMock(side_effect=select),rpc=AsyncMock())


@pytest.mark.anyio
async def test_pending_bound_session_is_readable_without_settlement_or_legacy_column(store):
    before=deepcopy(store.data)
    row=await checkout_receipt_order(store,SID)
    assert row==before['orders'][0]
    assert row['payment_status']=='unpaid'
    assert row['stripe_session_id'] is None
    assert store.data==before
    store.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('sid',[None,'','cs_live_','cs_test_x.or.id','cs_test_x\n','pi_example','cs_test_x/foreign'])
async def test_invalid_identifiers_do_not_touch_storage(store,sid):
    assert await checkout_receipt_order(store,sid) is None
    store.select.assert_not_awaited()


@pytest.mark.anyio
async def test_unknown_live_session_never_uses_test_binding(store):
    assert await checkout_receipt_order(store,'cs_live_unknown') is None
    assert store.select.await_count==1


@pytest.mark.anyio
async def test_existing_legacy_order_still_uses_direct_session_lookup(store):
    store.data['legacy']=[{'id':'legacy','stripe_session_id':SID}]
    assert (await checkout_receipt_order(store,SID))['id']=='legacy'
    assert store.select.await_count==1
    store.data['legacy'].append({'id':'ambiguous'})
    assert await checkout_receipt_order(store,SID) is None


@pytest.mark.anyio
@pytest.mark.parametrize('table',['commerce_test_sessions','commerce_checkout_attempts','orders','commerce_quotes'])
@pytest.mark.parametrize('count',[0,2])
async def test_missing_or_ambiguous_rows_fail_closed(store,table,count):
    store.data[table]=[] if count==0 else store.data[table]*2
    assert await checkout_receipt_order(store,SID) is None
    store.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('table,field,value',[
    ('commerce_test_sessions','session_id','cs_test_foreign'),
    ('commerce_test_sessions','attempt_id','not-a-uuid'),
    ('commerce_checkout_attempts','is_test',False),
    ('commerce_checkout_attempts','id',str(uuid4())),
    ('orders','is_test',False),('orders','commerce_quote_id',str(uuid4())),
    ('orders','stripe_session_id','cs_test_foreign'),('orders','guest_session_id',None),
    ('orders','user_id',str(uuid4())),('commerce_quotes','owner_guest_session','foreign'),
])
async def test_inconsistent_quote_attempt_order_or_owner_refuses_receipt(store,table,field,value):
    store.data[table][0][field]=value
    assert await checkout_receipt_order(store,SID) is None
    store.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('user,guest',[(None,'foreign'),({'id':str(uuid4())},GUEST)])
async def test_receipt_route_checks_owner_before_projecting_customer_data(monkeypatch,store,user,guest):
    import server
    monkeypatch.setattr(server,'checkout_receipt_order',AsyncMock(return_value=store.data['orders'][0]))
    projection=AsyncMock()
    monkeypatch.setattr(server,'_orders_with_items',projection)
    with pytest.raises(HTTPException) as rejected:
        await server.checkout_session(SID,guest,user)
    assert rejected.value.status_code==404
    projection.assert_not_awaited()
