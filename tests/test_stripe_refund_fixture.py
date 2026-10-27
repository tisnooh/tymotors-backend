"""Actual raw-body SDK verification; DB is mocked, no provider calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import server
from tests.commerce_refund_http_probe import refund
from tests.serve_stripe_refund_fixture import create_app
from tests.test_stripe_configuration import SIGNING_SECRET,signed_payload


@pytest.fixture
def boundary():
    order_id=str(uuid4());intent='pi_refund_fixture_only'
    row={'id':order_id,'is_test':True,'commerce_quote_id':str(uuid4()),'stripe_payment_intent_id':intent}
    db=SimpleNamespace(query=AsyncMock(return_value=[{'id':'disposable-product'}]),
        select=AsyncMock(side_effect=lambda *a,**k:[deepcopy(row)]),
        rpc=AsyncMock(return_value={'received':True,'requires_reconciliation':True,'is_test':True}))
    previous=(server.db,server.settings,server.stripe_client,server._send_order_email)
    app=create_app(signing_secret=SIGNING_SECRET,order_id=order_id,payment_intent_id=intent,database=db)
    with TestClient(app,client=('127.0.0.1',50000)) as client:
        db.select.reset_mock()
        yield client,db,row,intent
    assert (server.db,server.settings,server.stripe_client,server._send_order_email)==previous


def post(client,event,secret=SIGNING_SECRET):
    body,headers=signed_payload(event,secret)
    return client.post('/api/stripe/webhook',content=body,headers=headers)


def test_receipt_uses_original_handler_and_private_rpc_only(boundary):
    client,db,row,intent=boundary
    response=post(client,refund(intent))
    assert response.status_code==200
    assert response.json()['requires_reconciliation'] is True
    db.rpc.assert_awaited_once()
    assert db.rpc.call_args.args[0]=='commerce_record_test_refund'
    assert db.select.await_count==2  # Bound scope, then actual production handler.
    assert server.stripe_client is None
    assert server.settings.stripe_secret_key=='' and server.settings.email_enabled is False


@pytest.mark.parametrize('change',['signature','live','foreign-intent','payment-event','malformed','oversized'])
def test_invalid_or_foreign_event_refused_before_database(boundary,change):
    client,db,row,intent=boundary
    event=refund(intent)
    if change=='live': event['livemode']=True
    elif change=='foreign-intent': event['data']['object']['payment_intent']='pi_foreign'
    elif change=='payment-event': event['type']='checkout.session.completed'
    elif change=='malformed': event['data']['object']=[]
    elif change=='oversized': event['data']['object']['metadata']={'padding':'a'*(1024*1024)}
    assert post(client,event,'wrong_synthetic_secret' if change=='signature' else SIGNING_SECRET).status_code==400
    db.select.assert_not_awaited();db.rpc.assert_not_awaited()


@pytest.mark.parametrize('path,method',[
    ('/api/create-checkout-session','POST'),('/qa-stripe-payment/example','POST'),
    ('/api/admin/commerce/quotes/example/prepare-test-order','POST'),('/api/cart','POST'),
    ('/api/products','GET'),('/api/stripe/webhook','GET'),('/docs','GET')])
def test_creation_and_unrelated_routes_do_not_exist(boundary,path,method):
    client,db,row,intent=boundary
    assert client.request(method,path).status_code==403
    db.select.assert_not_awaited();db.rpc.assert_not_awaited()


def test_identity_contains_no_secret_or_financial_identifiers(boundary):
    client,db,row,intent=boundary
    response=client.get('/qa-stripe-refund-status')
    assert response.status_code==200
    result=response.json()
    assert result['new_payment_allowed'] is False and result['supplier_send_allowed'] is False
    assert SIGNING_SECRET not in response.text and row['id'] not in response.text and intent not in response.text
    db.select.assert_not_awaited();db.rpc.assert_not_awaited()


@pytest.mark.parametrize('change',['missing','live-order','unquoted'])
def test_changed_order_scope_cannot_reach_financial_rpc(boundary,change):
    client,db,row,intent=boundary
    if change=='missing': db.select.side_effect=lambda *a,**k:[]
    elif change=='live-order': row['is_test']=False
    elif change=='unquoted': row['commerce_quote_id']=None
    assert post(client,refund(intent)).status_code==409
    db.rpc.assert_not_awaited()


def test_database_failure_is_safe_and_retryable(boundary):
    client,db,row,intent=boundary
    db.select.side_effect=RuntimeError('PRIVATE database detail')
    response=post(client,refund(intent))
    assert response.status_code==503 and 'PRIVATE' not in response.text
    db.rpc.assert_not_awaited()


def test_non_loopback_client_cannot_call_fixture():
    db=SimpleNamespace(query=AsyncMock(return_value=[{}]),select=AsyncMock())
    oid=str(uuid4());pi='pi_fixture'
    db.select.return_value=[{'id':oid,'commerce_quote_id':str(uuid4()),'is_test':True,'stripe_payment_intent_id':pi}]
    app=create_app(signing_secret=SIGNING_SECRET,order_id=oid,payment_intent_id=pi,database=db)
    with TestClient(app,client=('203.0.113.1',50000)) as client:
        db.select.reset_mock()
        assert client.get('/qa-stripe-refund-status').status_code==403
        assert post(client,refund(pi)).status_code==403
        db.select.assert_not_awaited()


@pytest.mark.parametrize('secret,oid,pi',[
    ('wrong',str(uuid4()),'pi_fixture'),(SIGNING_SECRET,'bad-uuid','pi_fixture'),
    (SIGNING_SECRET,str(uuid4()),'invalid'),(SIGNING_SECRET,None,'pi_fixture')])
def test_fixture_requires_explicit_bound_identity(secret,oid,pi):
    with pytest.raises(ValueError):
        create_app(signing_secret=secret,order_id=oid,payment_intent_id=pi)
