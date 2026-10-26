"""Customer-owned sandbox bridge, simulated storage/provider; no real payment."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.commerce_customer_checkout import (
    CustomerCheckoutError,CustomerTestCheckout,OwnedCheckoutStore,customer_owner,hosted_test_url,
)
from app.commerce_payment_service import TestStripeGateway as Gateway
from app.supabase_rest import SupabaseError
from tests.test_commerce_checkout_params import snapshot  # noqa: F401

GUEST='synthetic_customer_checkout_owner'
OTHER='synthetic_customer_checkout_other'
USER='10000000-0000-4000-8000-000000000011'
AUTH_SESSION='10000000-0000-4000-8000-000000000012'
OWNER={'p_user_id':None,'p_guest_session':GUEST,'p_auth_session_id':None}


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def token(claims):
    encoded=base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
    return 'Bearer header.'+encoded+'.signature_only_verified_by_upstream_auth'


def test_guest_and_verified_user_derive_disjoint_authority():
    assert customer_owner(None,None,GUEST)==OWNER
    assert customer_owner({'id':USER},token({'sub':USER,'session_id':AUTH_SESSION}),OTHER)=={
        'p_user_id':USER,'p_guest_session':None,'p_auth_session_id':AUTH_SESSION}


@pytest.mark.parametrize('user,authorization,guest',[
    (None,'Bearer invalid',GUEST), (None,None,'short'),
    ({'id':USER},None,GUEST), ({'id':USER},'Bearer malformed',GUEST),
    ({'id':USER},token({'sub':str(uuid4()),'session_id':AUTH_SESSION}),GUEST),
    ({'id':USER},token({'sub':USER}),GUEST),
    ({'id':USER},token({'sub':USER,'session_id':'00000000-0000-0000-0000-000000000000'}),GUEST),
])
def test_unverified_or_ambiguous_authentication_never_downgrades_to_guest(user,authorization,guest):
    with pytest.raises(CustomerCheckoutError):customer_owner(user,authorization,guest)


@pytest.mark.parametrize('url',[
    'http://checkout.stripe.com/c/pay/cs_test_fixture',
    'https://checkout.stripe.com.evil.test/c/pay/cs_test_fixture',
    'https://user@checkout.stripe.com/c/pay/cs_test_fixture',
    'https://checkout.stripe.com:444/c/pay/cs_test_fixture',
    'https://checkout.stripe.com/c/pay/cs_test_other',
    'https://checkout.stripe.com/c/pay/cs_test_fixture/extra',
    'https://checkout.stripe.com\\evil.test/c/pay/cs_test_fixture',
    'https://checkout.stripe.com/c/pay/cs_test_fixture\n',None,
])
def test_hosted_url_is_exact_origin_and_bound_session_only(url):
    with pytest.raises(CustomerCheckoutError):hosted_test_url(url,'cs_test_fixture')


def test_official_url_fragment_and_standard_tls_port_allowed():
    for authority in ('checkout.stripe.com','checkout.stripe.com:443'):
        value='https://'+authority+'/c/pay/cs_test_fixture#provider_fragment'
        assert hosted_test_url(value,'cs_test_fixture')==value


@pytest.fixture
def wired(snapshot):
    c=deepcopy(snapshot)
    cart_id=str(uuid4()); deadline=datetime.now(timezone.utc)+timedelta(minutes=40)
    c['cart']={'id':cart_id,'user_id':None,'guest_session_id':GUEST}
    c['order'].update(cart_id=cart_id,user_id=None,guest_session_id=GUEST,order_number='TY-SYNTHETIC',
                      refunded_amount_cents=0,quote_expires_at=deadline.isoformat())
    c['attempt'].update(state='drafting',params=None,first_requested_at=None,session_id=None,
        idempotency_key='synthetic_durable_key_123456789',expires_at=int(deadline.timestamp()),
        quote_expires_at=deadline.isoformat())
    c['quote']={'id':c['order']['commerce_quote_id'],'cart_id':cart_id,'owner_user_id':None,
                'owner_guest_session':GUEST}
    sid='cs_test_customer_fixture'
    c['session']={'id':sid,'object':'checkout.session','mode':'payment','livemode':False,
        'metadata':{'attempt_id':c['attempt']['id'],'order_id':c['order']['id'],
                    'quote_id':c['quote']['id']},'client_reference_id':c['order']['id'],
        'expires_at':int(deadline.timestamp()),'currency':'eur','amount_total':10500,
        'amount_subtotal':10000,'total_details':{'amount_discount':0,'amount_shipping':500,'amount_tax':0},
        'automatic_tax':{'enabled':False},'discounts':[],'status':'open','payment_status':'unpaid',
        'payment_intent':None,'url':'https://checkout.stripe.com/c/pay/'+sid+'#synthetic',
        'shipping_details':{'address':deepcopy(c['order']['shipping_address'])}}
    c['bindings']=[]
    async def select(table,*,params=None):
        if table=='commerce_quotes':return [deepcopy(c['quote'])] if c['quote'] is not None else []
        if table=='carts':return [deepcopy(c['cart'])]
        if table=='orders':return [deepcopy(c['order'])]
        if table=='commerce_checkout_attempts':return [deepcopy(c['attempt'])]
        if table=='commerce_test_sessions':return deepcopy(c['bindings'])
        raise AssertionError(table)
    async def rpc(name,payload):
        if name=='is_auth_session_active':return True
        if name=='commerce_bind_test_session':
            c['bindings']=[{'attempt_id':c['attempt']['id'],'session_id':payload['p_session_id']}]
            return deepcopy(c['bindings'][0])
        assert name.startswith('commerce_customer_') and 'p_actor' not in payload
        assert {k:payload[k] for k in OWNER}==c.get('owner',OWNER)
        if name=='commerce_customer_order_from_quote':return {'order_id':c['order']['id'],
            'order_number':'TY-SYNTHETIC','is_test':True}
        if name=='commerce_customer_prepare_checkout_attempt':return deepcopy(c)
        if name=='commerce_customer_store_checkout_params':
            c['attempt'].update(state='ready',params=deepcopy(payload['p_params']))
            return deepcopy(c['attempt'])
        if name=='commerce_customer_claim_checkout_attempt':
            if c['attempt']['state']!='ready':raise SupabaseError(409,'private conflict')
            c['attempt'].update(state='creating',first_requested_at=datetime.now(timezone.utc).isoformat())
            return deepcopy(c['attempt'])
        if name=='commerce_customer_checkout_unknown':
            c['attempt']['state']='unknown';return deepcopy(c['attempt'])
        if name=='commerce_customer_cancel_checkout_draft':
            c['attempt']['state']='cancelled';return deepcopy(c['attempt'])
        raise AssertionError(name)
    db=SimpleNamespace(select=AsyncMock(side_effect=select),rpc=AsyncMock(side_effect=rpc))
    gateway=Gateway('sk_test_synthetic_not_a_credential')
    gateway.create=AsyncMock(side_effect=lambda *_:deepcopy(c['session']))
    gateway.retrieve=AsyncMock(side_effect=lambda *_:deepcopy(c['session']))
    service=CustomerTestCheckout(db,gateway,'https://shop.example.com',('FR',))
    return c,db,gateway,service


async def start(wired,**changes):
    c,_,_,service=wired
    args={'quote_id':c['order']['commerce_quote_id'],'request_key':str(uuid4()),
          'cart':deepcopy(c['cart']),'user':None,'guest_session':GUEST,'owner':OWNER}
    return await service.start(**{**args,**changes})


@pytest.mark.anyio
async def test_owned_quote_reuses_durable_services_without_admin_actor(wired):
    c,db,gateway,_=wired
    result=await start(wired)
    assert result=={'order_id':c['order']['id'],'order_number':'TY-SYNTHETIC','status':'open',
                    'quote_id':c['order']['commerce_quote_id'],'session_id':c['session']['id'],
                    'is_test':True,'url':c['session']['url']}
    gateway.create.assert_awaited_once_with(c['attempt']['params'],c['attempt']['idempotency_key'])
    names=[call.args[0] for call in db.rpc.await_args_list]
    assert names==['commerce_customer_order_from_quote','commerce_customer_prepare_checkout_attempt',
        'commerce_customer_store_checkout_params','commerce_customer_claim_checkout_attempt','commerce_bind_test_session']
    assert not any('settle' in name or 'refund' in name for name in names)


@pytest.mark.anyio
async def test_retry_new_http_key_never_recreates_bound_provider_payment(wired):
    _,db,gateway,_=wired
    first=await start(wired);second=await start(wired)
    assert first==second and gateway.create.await_count==1 and gateway.retrieve.await_count==2
    assert sum(call.args[0]=='commerce_customer_claim_checkout_attempt' for call in db.rpc.await_args_list)==1


@pytest.mark.anyio
@pytest.mark.parametrize('state',['creating','unknown','cancelled'])
async def test_unbound_ambiguous_or_cancelled_attempt_never_retried(wired,state):
    c,_,gateway,_=wired
    c['attempt']['state']=state
    with pytest.raises(CustomerCheckoutError):await start(wired)
    gateway.create.assert_not_awaited();gateway.retrieve.assert_not_awaited()


@pytest.mark.anyio
async def test_lost_provider_response_retains_unknown_and_exact_key(wired):
    c,db,gateway,_=wired
    gateway.create.side_effect=TimeoutError('PRIVATE secret provider body')
    with pytest.raises(CustomerCheckoutError) as caught:await start(wired)
    assert 'PRIVATE' not in str(caught.value) and c['attempt']['state']=='unknown'
    assert c['attempt']['idempotency_key']=='synthetic_durable_key_123456789'
    assert all('cancel' not in x.args[0] for x in db.rpc.await_args_list)
    with pytest.raises(CustomerCheckoutError):await start(wired)
    assert gateway.create.await_count==1


@pytest.mark.anyio
@pytest.mark.parametrize('changes',[{'amount_total':1},{'livemode':True},{'currency':'usd'},
    {'id':'cs_test_foreign'},{'metadata':{}},{'url':'https://evil.test/checkout'}])
async def test_provider_conflict_never_exposes_payment_url(wired,changes):
    c,_,gateway,_=wired
    await start(wired)
    c['session'].update(changes)
    with pytest.raises(CustomerCheckoutError):await start(wired)
    assert gateway.create.await_count==1


@pytest.mark.anyio
async def test_observed_paid_requires_signed_webhook_without_settlement(wired):
    c,db,gateway,_=wired
    await start(wired)
    c['session'].update(status='complete',payment_status='paid',payment_intent='pi_synthetic_customer')
    result=await start(wired)
    assert result['status']=='awaiting_webhook' and result['url'] is None
    assert c['order']['payment_status']=='unpaid'
    assert all('settle' not in x.args[0] for x in db.rpc.await_args_list)


@pytest.mark.anyio
async def test_already_locally_paid_never_prepares_or_calls_provider(wired):
    c,_,gateway,_=wired
    c['order'].update(status='paid',payment_status='paid')
    result=await start(wired)
    assert result['status']=='paid' and result['url'] is None
    gateway.create.assert_not_awaited();gateway.retrieve.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('field,value',[('user_id',USER),('guest_session_id',OTHER),
    ('cart_id',str(uuid4())),('commerce_quote_id',str(uuid4())),('is_test',False)])
async def test_foreign_or_live_order_refused_before_sdk(wired,field,value):
    c,_,gateway,_=wired
    c['order'][field]=value
    with pytest.raises(CustomerCheckoutError):await start(wired)
    gateway.create.assert_not_awaited();gateway.retrieve.assert_not_awaited()


@pytest.mark.anyio
async def test_foreign_quote_does_not_even_prepare_an_order(wired):
    c,db,gateway,_=wired
    c['quote']['owner_guest_session']=OTHER
    with pytest.raises(CustomerCheckoutError):await start(wired)
    db.rpc.assert_not_awaited();gateway.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('mode',['expired','cart_claimed','cancelled','refunded','money_changed'])
async def test_race_or_expiry_after_provider_read_never_exposes_url(wired,mode):
    c,_,gateway,_=wired
    async def retrieve(_):
        if mode=='expired':c['session'].update(status='expired')
        if mode=='cart_claimed':c['cart'].update(user_id=USER,guest_session_id=None)
        if mode=='cancelled':c['order']['status']='cancelled'
        if mode=='refunded':c['order']['refunded_amount_cents']=100
        if mode=='money_changed':c['order']['total_cents']+=1
        return deepcopy(c['session'])
    gateway.retrieve.side_effect=retrieve
    with pytest.raises(CustomerCheckoutError):await start(wired)


@pytest.mark.anyio
async def test_owned_rpc_adapter_does_not_impersonate_or_allow_financial_rpcs():
    db=SimpleNamespace(rpc=AsyncMock())
    store=OwnedCheckoutStore(db,OWNER)
    for name,payload in [('commerce_claim_checkout_attempt',{'p_actor':USER}),
                         ('commerce_settle_test_checkout',{}),('admin_save_product',{})]:
        with pytest.raises(CustomerCheckoutError):await store.rpc(name,payload)
    db.rpc.assert_not_awaited()
