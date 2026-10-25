"""Actual service/SDK validation with mocked transports, NOT Stripe E2E proof."""
from copy import deepcopy
from unittest.mock import AsyncMock
import pytest

from app.commerce_payment_service import CommerceTestPayments, CommercePaymentError, TestStripeGateway as Gateway
from app.commerce_checkout_events import CheckoutEventError
from tests.test_commerce_checkout_events import event_context  # noqa: F401
from tests.test_commerce_api import client  # noqa: F401

@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def wired(event_context):
    context = deepcopy(event_context)
    context['attempt'].update(state='ready', params={'frozen':'exact'},idempotency_key='fixed-test-key',session_id=None)
    context['session'].update(status='open',payment_status='unpaid',payment_intent=None)
    async def select(table, *, params=None):
        if table=='commerce_checkout_attempts': return [context['attempt']]
        if table=='orders': return [context['order']]
        if table=='commerce_test_sessions': return []
        raise AssertionError(table)
    async def rpc(name,payload):
        if name=='commerce_claim_checkout_attempt':
            assert context['attempt']['state']=='ready'
            context['attempt']['state']='creating'
            return deepcopy(context['attempt'])
        if name=='commerce_bind_test_session': return {'session_id':payload['p_session_id']}
        if name=='commerce_checkout_unknown':
            context['attempt']['state']='unknown'; return context['attempt']
        if name=='commerce_settle_test_checkout': return {'is_test':True,'duplicate':False}
        raise AssertionError(name)
    from types import SimpleNamespace
    db = SimpleNamespace(select=AsyncMock(side_effect=select),rpc=AsyncMock(side_effect=rpc))
    gateway = Gateway('sk_test_synthetic_not_a_credential')
    gateway.create = AsyncMock(return_value=context['session'])
    return context, db, gateway, CommerceTestPayments(db,gateway)


@pytest.mark.parametrize('key',[None,'','sk_live_never','rk_live_never','rkcs_live_never','random','sk_test_','rkcs_test_','unknown_test_never'])
def test_non_test_key_rejected_before_any_sdk(key):
    with pytest.raises(CommercePaymentError,match='test_credentials_required'):
        Gateway(key)


@pytest.mark.parametrize('prefix',['sk_test_','rk_test_','rkcs_test_'])
def test_explicit_test_credentials_construct_sdk_without_network(prefix, monkeypatch):
    from unittest.mock import Mock
    sdk = Mock()
    monkeypatch.setattr('app.commerce_payment_service.stripe.StripeClient', sdk)
    Gateway(prefix+'synthetic_not_a_credential')
    sdk.assert_called_once_with(prefix+'synthetic_not_a_credential')


@pytest.mark.anyio
async def test_create_claims_once_and_keeps_exact_key_params(wired):
    c,db,gateway,service = wired
    result = await service.create_session('admin',c['attempt']['id'])
    assert result['is_test'] is True
    gateway.create.assert_awaited_once_with({'frozen':'exact'},'fixed-test-key')
    assert [x.args[0] for x in db.rpc.await_args_list]==['commerce_claim_checkout_attempt','commerce_bind_test_session']
    with pytest.raises(CommercePaymentError,match='inspection'):
        await service.create_session('admin',c['attempt']['id'])
    assert gateway.create.await_count==1


@pytest.mark.anyio
async def test_real_current_sdk_resource_converted_before_validation(wired):
    import stripe
    c, db, gateway, service = wired
    # Actual installed SDK16 class, not a mock or an obsolete dict-like facade.
    gateway.create.return_value = stripe.checkout.Session.construct_from(deepcopy(c['session']), None)
    assert not hasattr(gateway.create.return_value, 'to_dict_recursive')
    result = await service.create_session('admin', c['attempt']['id'])
    assert result['session_id'] == c['session']['id']
    assert db.rpc.await_args_list[-1].args[0] == 'commerce_bind_test_session'


@pytest.mark.anyio
async def test_timeout_never_cancels_or_rotates(wired):
    c,db,gateway,service = wired
    gateway.create.side_effect=TimeoutError()
    with pytest.raises(TimeoutError): await service.create_session('admin',c['attempt']['id'])
    assert c['attempt']['state']=='unknown'
    assert c['attempt']['idempotency_key']=='fixed-test-key'
    assert all('cancel' not in x.args[0] for x in db.rpc.await_args_list)


@pytest.mark.anyio
async def test_unknown_client_refused_before_claim(wired):
    c,db,gateway,_ = wired
    with pytest.raises(CommercePaymentError,match='test_gateway_required'):
        await CommerceTestPayments(db,object()).create_session('admin',c['attempt']['id'])
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_unpaid_event_does_not_settle(wired):
    c,db,_,service = wired
    result=await service.accept_signed_event({'id':'evt_fake','type':'checkout.session.completed','livemode':False,'data':{'object':c['session']}})
    assert result['awaiting_payment'] is True
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_paid_redirect_keeps_financial_truth_but_requests_hold(wired):
    c,db,_,service = wired
    c['session'].update(status='complete',payment_status='paid',payment_intent='pi_fake')
    c['session']['shipping_details']['address']['line1']='Different address'
    await service.accept_signed_event({'id':'evt_fake','type':'checkout.session.async_payment_succeeded','livemode':False,'data':{'object':c['session']}})
    payload=db.rpc.await_args.args[1]
    assert payload['p_destination_matches'] is False


@pytest.mark.anyio
async def test_live_event_never_reaches_storage(wired):
    _,db,_,service=wired
    with pytest.raises(CommercePaymentError,match='test_events_only'):
        await service.accept_signed_event({'livemode':True})
    db.select.assert_not_awaited();db.rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_invalid_money_never_settles(wired):
    c,db,_,service=wired
    c['session']['amount_total']+=1
    with pytest.raises(CheckoutEventError):
        await service.accept_signed_event({'livemode':False,'type':'checkout.session.completed','data':{'object':c['session']}})
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('kind',['charge.refunded','refund.updated','refund.failed'])
async def test_quoted_refunds_not_silently_acknowledged(wired,kind):
    _,db,_,service=wired
    with pytest.raises(CommercePaymentError,match='requires_review'):
        await service.accept_signed_event({'livemode':False,'type':kind})
    db.rpc.assert_not_awaited()


@pytest.mark.parametrize('method,path',[
    ('GET','/api/admin/commerce/orders/10000000-0000-4000-8000-000000000001/fulfillment-plan'),
    ('POST','/api/admin/commerce/test-tasks/10000000-0000-4000-8000-000000000001/simulate'),
])
def test_private_fulfillment_requires_auth(client,method,path,monkeypatch):
    import server
    rpc=AsyncMock();monkeypatch.setattr(server.db,'rpc',rpc)
    assert client.request(method,path,json={}).status_code==401
    rpc.assert_not_awaited()


@pytest.mark.parametrize('method,path',[
    ('GET','/api/admin/commerce/orders/10000000-0000-4000-8000-000000000001/fulfillment-plan'),
    ('POST','/api/admin/commerce/test-tasks/10000000-0000-4000-8000-000000000001/simulate'),
])
def test_customer_cannot_get_supplier_plan_or_advance(client,method,path,monkeypatch):
    import server
    select=AsyncMock(return_value=[{'id':'10000000-0000-4000-8000-000000000001','role':'customer'}])
    monkeypatch.setattr(server.db,'select',select)
    rpc=AsyncMock();monkeypatch.setattr(server.db,'rpc',rpc)
    assert client.request(method,path,json={},headers={'Authorization':'Bearer commerce-customer'}).status_code==403
    rpc.assert_not_awaited()
