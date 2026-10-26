"""Delivery discovery is read-only, exact-owner, bounded and evidence-gated."""
from copy import deepcopy
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.commerce_delivery_options import CartDeliveryOptions
from app.commerce_models import CartDeliveryOptionsInput, CartQuoteInput, DELIVERY_DISCOVERY_MODE
from app.commerce_quote_engine import CartQuoteError
from app.supabase_rest import SupabaseError
from tests.test_commerce_quote_engine import context, CART, OFFER, RATE  # noqa: F401

GUEST='synthetic_delivery_options_guest'
ADDRESS={'name':'Synthetic recipient','line1':'1 Synthetic street','city':'Paris','postal_code':'75001','country':'FR'}


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.fixture
def wired(context):
    context['cart'].update(user_id=None,guest_session_id=GUEST)
    context['mode']=DELIVERY_DISCOVERY_MODE
    for product in context['products']: product['currency']='EUR'
    for key in ('offers','rates','image_permissions'):
        for row in context.get(key,[]): row['valid_until']='2099-01-01T00:00:00+00:00'
    rates=deepcopy(context['rates'])
    db=SimpleNamespace(rpc=AsyncMock(side_effect=lambda *_args,**_kw:deepcopy(context)),
        page=AsyncMock(side_effect=lambda *_args,**_kw:{'items':deepcopy(rates),'total':len(rates)}))
    return db,context,rates,CartDeliveryOptions(db,('FR','BE'))


async def discover(wired, address=None,cart=None,user=None,guest=GUEST):
    _,source,_,service=wired
    return await service.discover(CartDeliveryOptionsInput(destination=address or ADDRESS),
        cart or source['cart'],user,guest)


@pytest.mark.anyio
async def test_options_are_computed_by_existing_engine_without_mutation_or_private_data(wired):
    db,source,_,_=wired
    before=deepcopy(source)
    result=await discover(wired)
    assert result['country']=='FR' and result['requires_quote'] is True
    assert len(result['options'])==1
    option=result['options'][0]
    assert set(option)=={'mode','currency','subtotal_cents','shipping_cents','tax_cents','total_cents','expires_at'}
    assert option['mode']=='tracked' and option['total_cents']==24600 and option['shipping_cents']==600
    assert source==before
    assert [call.args[0] for call in db.rpc.call_args_list]==['commerce_cart_context']
    assert db.rpc.call_args.args[1]['p_mode']==DELIVERY_DISCOVERY_MODE
    query=db.page.call_args.kwargs['params']
    assert query['offer_id']=='in.('+OFFER+')' and query['country']=='eq.FR'
    for private in ('supplier_id','offer_id','unit_cost_cents','evidence_ref','destination','owner_guest_session','source_context'):
        assert private not in repr(result)


@pytest.mark.anyio
@pytest.mark.parametrize('country',['BE','DE','US'])
async def test_other_destinations_are_not_enabled_by_config_alone(wired,country):
    with pytest.raises(CartQuoteError,match='destination_not_supported'):
        await discover(wired,{**ADDRESS,'country':country})
    wired[0].rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_wrong_owner_never_reads_or_quotes_another_cart(wired):
    with pytest.raises(CartQuoteError,match='cart_not_accessible'):
        await discover(wired,guest='different_guest_capability')
    wired[0].rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('field,value',[('id',str(uuid4())),('guest_session_id','foreign'),('user_id',str(uuid4()))])
async def test_changed_source_cart_refuses_options(wired,field,value):
    db,source,_,_=wired
    cart=deepcopy(source['cart'])
    source['cart'][field]=value
    with pytest.raises(CartQuoteError): await discover(wired,cart=cart)
    db.page.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('page',[
    {'items':[],'total':1},{'items':[],'total':True},{'items':[],'total':1001},
    {'items':None,'total':0},
])
async def test_incomplete_or_malformed_pages_never_invent_a_mode(wired,page):
    wired[0].page.side_effect=None; wired[0].page.return_value=page
    with pytest.raises(CartQuoteError,match='incomplete_delivery_options'): await discover(wired)


@pytest.mark.anyio
@pytest.mark.parametrize('field,value',[
    ('offer_id',str(uuid4())),('country','BE'),('verification_state','unverified'),
    ('mode','invalid mode'),('mode','x'*101),
])
async def test_foreign_or_unverified_rates_are_rejected_even_if_storage_ignores_filter(wired,field,value):
    wired[2][0][field]=value
    with pytest.raises(CartQuoteError): await discover(wired)


@pytest.mark.anyio
async def test_unverified_images_or_expired_rates_return_no_shipping_promise(wired):
    wired[1]['image_permissions']=[]
    assert (await discover(wired))['options']==[]


@pytest.mark.anyio
@pytest.mark.parametrize('field,value',[
    ('valid_until','2020-01-01T00:00:00+00:00'),('postal_prefix','130'),
    ('customer_shipping_cents',None),('goods_tax_bps',None),
])
async def test_expired_wrong_postcode_or_incomplete_finance_never_produces_free_fallback(wired,field,value):
    wired[2][0][field]=value
    assert (await discover(wired))['options']==[]


@pytest.mark.anyio
async def test_each_mode_is_evaluated_for_the_whole_cart_without_cheapest_default(wired):
    original=deepcopy(wired[2][0])
    wired[2].append({**original,'id':str(uuid4()),'mode':'alternate','customer_shipping_cents':1234})
    options=(await discover(wired))['options']
    assert [o['mode'] for o in options]==['alternate','tracked']
    assert [o['shipping_cents'] for o in options]==[1234,600]
    assert all('selected' not in option for option in options)


@pytest.mark.anyio
async def test_large_offer_sets_are_batched_to_bound_private_query_uris(wired):
    db,source,_,_=wired
    original=deepcopy(source['offers'][0])
    source['offers'][:]=[{**original,'id':str(uuid4())} for _ in range(41)]
    db.page.side_effect=None; db.page.return_value={'items':[],'total':0}
    assert (await discover(wired))['options']==[]
    assert db.page.await_count==2
    assert all(len(call.kwargs['params']['offer_id'])<1600 for call in db.page.call_args_list)
    wired[2].clear()
    assert (await discover(wired))['options']==[]


@pytest.mark.anyio
async def test_modes_have_no_arbitrary_truncation_or_internal_mode_leak(wired):
    rates=wired[2]
    original=deepcopy(rates[0])
    rates[:]=[{**original,'id':str(uuid4()),'mode':'mode_'+str(i)} for i in range(11)]
    with pytest.raises(CartQuoteError,match='incomplete_delivery_options'): await discover(wired)
    rates[:]=[{**original,'mode':DELIVERY_DISCOVERY_MODE}]
    assert (await discover(wired))['options']==[]


def test_internal_mode_cannot_be_persisted_as_customer_quote():
    with pytest.raises(ValidationError):
        CartQuoteInput(destination=ADDRESS,mode=DELIVERY_DISCOVERY_MODE,request_key=uuid4())


@pytest.mark.parametrize('destination',[
    {**ADDRESS,'name':'  '},{**ADDRESS,'city':'  '},{**ADDRESS,'line1':'  '},
    {**ADDRESS,'line1':'Bad\naddress'},{**ADDRESS,'country':'FR','postal_code':'---'},
])
def test_destination_requires_meaningful_non_controlled_input(destination):
    with pytest.raises(ValidationError): CartDeliveryOptionsInput(destination=destination)


@pytest.mark.parametrize('postal_code',['ABC','1234','123456','750 01','７５００１'])
def test_french_postcode_format_is_enforced_for_both_customer_endpoints(postal_code):
    destination={**ADDRESS,'postal_code':postal_code}
    with pytest.raises(ValidationError): CartDeliveryOptionsInput(destination=destination)
    with pytest.raises(ValidationError):
        CartQuoteInput(destination=destination,mode='tracked',request_key=uuid4())


@pytest.mark.parametrize('authorization',['Basic invalid','Bearer','Bearer ', ''])
def test_explicit_invalid_auth_never_downgrades_to_guest(monkeypatch,authorization):
    import server
    cart_lookup=AsyncMock(return_value=[{'id':CART,'user_id':None,'guest_session_id':GUEST}])
    monkeypatch.setattr(server.db,'select',cart_lookup)
    client=TestClient(server.app)
    headers={'X-Session-Id':GUEST,'Authorization':authorization}
    for path,payload in (
        ('/api/cart/delivery-options',{'destination':ADDRESS}),
        ('/api/cart/quote',{'destination':ADDRESS,'mode':'tracked','request_key':str(uuid4())}),
    ):
        assert client.post(path,json=payload,headers=headers).status_code==401
    assert client.get('/api/cart/quote/'+str(uuid4()),headers=headers).status_code==401
    cart_lookup.assert_not_awaited()


def test_api_owner_boundary_strict_payload_and_expunged_storage_error(monkeypatch):
    import server
    from app.commerce_delivery_options import CartDeliveryOptions as Service
    cart={'id':CART,'user_id':None,'guest_session_id':GUEST}
    monkeypatch.setattr(server.db,'get_user',AsyncMock(return_value=None))
    monkeypatch.setattr(server.db,'select',AsyncMock(return_value=[cart]))
    call=AsyncMock(side_effect=SupabaseError(409,'PRIVATE supplier reference and address'))
    monkeypatch.setattr(Service,'discover',call)
    server.quote_attempts.clear()
    client=TestClient(server.app)
    headers={'X-Session-Id':GUEST}
    assert client.post('/api/cart/delivery-options',json={'destination':ADDRESS},headers={**headers,'Authorization':'Bearer invalid'}).status_code==401
    assert client.post('/api/cart/delivery-options',json={'destination':ADDRESS,'price':1},headers=headers).status_code==422
    call.assert_not_awaited()
    result=client.post('/api/cart/delivery-options',json={'destination':ADDRESS},headers=headers)
    assert result.status_code==409 and 'PRIVATE' not in result.text
    assert result.json()['detail']=={'code':'delivery_options_unavailable'}
    assert result.headers['cache-control']=='no-store'
