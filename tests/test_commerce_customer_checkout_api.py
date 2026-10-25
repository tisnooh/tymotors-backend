"""Public owner boundary with a mocked bridge; never a real payment test."""
import base64
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
import server
import app.commerce_customer_checkout_api as boundary
from app.commerce_customer_checkout import CustomerCheckoutError
from app.commerce_payment_service import CommercePaymentError

QUOTE='10000000-0000-4000-8000-000000000021'
USER='10000000-0000-4000-8000-000000000022'
AUTH='10000000-0000-4000-8000-000000000023'
CART='10000000-0000-4000-8000-000000000024'
GUEST='customer_api_synthetic_guest'
PATH='/api/cart/quote/'+QUOTE+'/checkout'


@pytest.fixture
def client(monkeypatch):
    server.checkout_attempts.clear()
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='test',
        stripe_secret_key='sk_test_synthetic_not_a_credential'))
    user=AsyncMock(return_value=None);monkeypatch.setattr(server.db,'get_user',user)
    cart=AsyncMock(return_value={'id':CART,'user_id':None,'guest_session_id':GUEST})
    monkeypatch.setattr(server,'_cart_for',cart)
    # The factory captured the callable at registration, so patch its behavior
    # through the existing DB cart lookup too, not only the server alias.
    select=AsyncMock(return_value=[{'id':CART,'user_id':None,'guest_session_id':GUEST}])
    monkeypatch.setattr(server.db,'select',select)
    transport=SimpleNamespace(close_async=AsyncMock())
    transport_factory=Mock(return_value=transport)
    monkeypatch.setattr(boundary.stripe,'HTTPXClient',transport_factory)
    gateway=Mock();monkeypatch.setattr(boundary,'TestStripeGateway',gateway)
    start=AsyncMock(return_value={'url':'https://checkout.stripe.com/c/pay/cs_test_synthetic',
        'order_id':str(uuid4()),'order_number':'TY-SYNTHETIC','status':'open','is_test':True})
    service=Mock(return_value=SimpleNamespace(start=start))
    monkeypatch.setattr(boundary,'CustomerTestCheckout',service)
    rpc=AsyncMock();monkeypatch.setattr(server.db,'rpc',rpc)
    return SimpleNamespace(http=TestClient(server.app),user=user,cart=cart,select=select,
        transport=transport,transport_factory=transport_factory,gateway=gateway,
        service=service,start=start,rpc=rpc)


def post(client,*,headers=None,body=None):
    return client.http.post(PATH,headers=headers or {'X-Session-Id':GUEST},
        json=body if body is not None else {'request_key':str(uuid4())})


def test_guest_uses_only_server_derived_capability_and_test_gateway(client):
    response=post(client)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    args=client.start.await_args.args
    assert str(args[0])==QUOTE and args[2]['id']==CART and args[3] is None
    assert args[5]=={'p_user_id':None,'p_guest_session':GUEST,'p_auth_session_id':None}
    assert GUEST not in response.text
    client.transport.close_async.assert_awaited_once()
    client.rpc.assert_not_awaited()


@pytest.mark.parametrize('changes,status',[
    ({'stripe_mode':'live'},409),({'stripe_secret_key':''},503),
])
def test_closed_configuration_does_not_read_cart_or_construct_sdk(client,monkeypatch,changes,status):
    monkeypatch.setattr(server,'settings',replace(server.settings,**changes))
    assert post(client).status_code==status
    client.select.assert_not_awaited();client.transport_factory.assert_not_called()
    client.start.assert_not_awaited()


def test_invalid_bearer_never_downgrades_to_guest(client):
    assert post(client,headers={'Authorization':'Bearer invalid','X-Session-Id':GUEST}).status_code==401
    client.select.assert_not_awaited();client.start.assert_not_awaited()


def test_missing_capability_is_not_a_new_cart(client):
    assert client.http.post(PATH,json={'request_key':str(uuid4())}).status_code==400
    client.select.assert_not_awaited();client.start.assert_not_awaited()


def test_verified_auth_identity_takes_priority_over_foreign_guest_header(client):
    claims=base64.urlsafe_b64encode(json.dumps({'sub':USER,'session_id':AUTH}).encode()).decode().rstrip('=')
    client.user.return_value={'id':USER}
    client.select.return_value=[{'id':CART,'user_id':USER,'guest_session_id':None}]
    response=post(client,headers={'Authorization':'Bearer header.'+claims+'.verified_upstream',
                                  'X-Session-Id':'another_synthetic_guest_123'})
    assert response.status_code==200
    assert client.start.await_args.args[-1]=={'p_user_id':USER,'p_guest_session':None,'p_auth_session_id':AUTH}


@pytest.mark.parametrize('extra',[
    {'is_test':False},{'price_cents':1},{'p_actor':USER},
    {'p_user_id':USER},{'destination':{'country':'FR'}},{'session_id':'cs_test_foreign'},
])
def test_client_cannot_override_authority_or_financial_snapshot(client,extra):
    assert post(client,body={'request_key':str(uuid4()),**extra}).status_code==422
    client.start.assert_not_awaited();client.transport_factory.assert_not_called()


@pytest.mark.parametrize('error,status',[
    (CustomerCheckoutError('checkout_unavailable'),409),
    (CustomerCheckoutError('checkout_requires_inspection',502),502),
    (TimeoutError('PRIVATE_PROVIDER_KEY'),502),
    (CommercePaymentError('PRIVATE_PROVIDER_KEY'),503),
])
def test_safe_failures_close_owned_transport_without_retry(client,error,status):
    client.start.side_effect=error
    response=post(client)
    assert response.status_code==status and 'PRIVATE' not in response.text
    client.start.assert_awaited_once();client.transport.close_async.assert_awaited_once()
    client.rpc.assert_not_awaited()


def test_cleanup_failure_does_not_expose_details_or_override_result(client,caplog):
    client.transport.close_async.side_effect=RuntimeError('PRIVATE_TRANSPORT_SECRET')
    assert post(client).status_code==200
    assert 'PRIVATE' not in caplog.text
    assert 'cleanup requires review' in caplog.text


def test_invalid_uuid_or_request_key_refused_before_sdk(client):
    assert client.http.post(PATH.replace(QUOTE,'bad'),json={'request_key':str(uuid4())},
                           headers={'X-Session-Id':GUEST}).status_code==422
    assert post(client,body={'request_key':'bad'}).status_code==422
    client.transport_factory.assert_not_called();client.start.assert_not_awaited()
