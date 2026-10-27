"""Actual SDK signature boundary, mocked storage/legacy transport only."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from tests.commerce_refund_http_probe import refund
from tests.test_stripe_configuration import configure_signed_webhook, signed_payload


@pytest.fixture
def boundary(monkeypatch):
    configure_signed_webhook(monkeypatch)
    db = {name: AsyncMock() for name in ('select','rpc','insert','update','delete')}
    db['select'].return_value=[]
    db['rpc'].return_value={'received':True,'is_test':True,'requires_reconciliation':True}
    for name,method in db.items():
        monkeypatch.setattr(server.db,name,method)
    legacy, mail = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server,'_sync_refunds',legacy)
    monkeypatch.setattr(server,'_send_order_email',mail)
    return TestClient(server.app), db, legacy, mail


def post(client,event):
    body,headers=signed_payload(event)
    return client.post('/api/stripe/webhook',content=body,headers=headers)


@pytest.mark.parametrize('metadata',[{},[],[{'private':'data'}],'wrong',None])
def test_valid_refund_metadata_never_controls_binding_or_storage(boundary, metadata):
    client,db,legacy,mail=boundary
    event=refund('pi_synthetic')
    event['data']['object']['metadata']=metadata
    response=post(client,event)
    assert response.status_code==200
    assert response.json()['requires_reconciliation'] is True
    name,arguments=db['rpc'].call_args.args
    assert name=='commerce_record_test_refund'
    assert set(arguments)=={'p_event'}
    assert len(arguments['p_event'])==10
    assert 'metadata' not in arguments['p_event']
    assert 'PRIVATE' not in str(arguments)
    assert db['select'].call_args.kwargs['params']['stripe_payment_intent_id']=='eq.pi_synthetic'
    for name in ('insert','update','delete'):
        db[name].assert_not_awaited()
    legacy.assert_not_awaited()
    mail.assert_not_awaited()


@pytest.mark.parametrize('expanded',[False,True])
def test_legacy_order_retains_sync_with_normalized_intent(boundary, expanded):
    client,db,legacy,mail=boundary
    db['select'].side_effect=[[{'id':'legacy-order','commerce_quote_id':None}],[]]
    event=refund('pi_synthetic')
    event['data']['object']['metadata']={'attempt_id':'untrusted','quote_id':'untrusted'}
    if expanded:
        event['data']['object']['payment_intent']={'object':'payment_intent','id':'pi_synthetic'}
    assert post(client,event).status_code==200
    legacy.assert_awaited_once_with('pi_synthetic')
    db['rpc'].assert_awaited_once()
    db['insert'].assert_awaited_once()
    assert db['update'].call_args.args[0]=='stripe_events'
    assert db['update'].call_args.args[1]['status']=='completed'
    mail.assert_not_awaited()


def test_quoted_identity_uses_receipt_not_legacy_or_checkout_metadata(boundary):
    client,db,legacy,mail=boundary
    db['select'].return_value=[{'id':'quoted-order','commerce_quote_id':'private-quote'}]
    event=refund('pi_synthetic')
    assert post(client,event).status_code==200
    db['rpc'].assert_awaited_once()
    assert db['rpc'].call_args.args[0]=='commerce_record_test_refund'
    db['insert'].assert_not_awaited()
    legacy.assert_not_awaited()
    mail.assert_not_awaited()


@pytest.mark.parametrize('change',['signature','live','bad-object','bad-data','bool-amount','no-status'])
def test_invalid_refund_never_reaches_storage(boundary,change):
    client,db,legacy,mail=boundary
    event=refund('pi_synthetic')
    if change=='live': event['livemode']=True
    elif change=='bad-object': event['data']['object']=[]
    elif change=='bad-data': event['data']=[]
    elif change=='bool-amount': event['data']['object']['amount']=True
    elif change=='no-status': event['data']['object'].pop('status')
    if change=='signature':
        body,headers=signed_payload(event,secret='wrong_synthetic_secret')
        response=client.post('/api/stripe/webhook',content=body,headers=headers)
    else:
        response=post(client,event)
    assert response.status_code==400
    for method in db.values(): method.assert_not_awaited()
    legacy.assert_not_awaited()
    mail.assert_not_awaited()


def test_database_failure_is_retryable_without_provider_side_effects(boundary):
    client,db,legacy,mail=boundary
    db['rpc'].side_effect=RuntimeError('PRIVATE failure must not leak')
    response=post(client,refund('pi_synthetic'))
    assert response.status_code==500
    assert 'PRIVATE' not in response.text
    db['select'].assert_not_awaited()
    legacy.assert_not_awaited()
    mail.assert_not_awaited()


@pytest.mark.parametrize('data', [None,[],{'object':[]},{'object':{'metadata':'wrong'}}])
def test_other_malformed_event_object_is_400_before_storage(boundary, data):
    client,db,legacy,mail=boundary
    event={'object':'event','id':'evt_synthetic','livemode':False,
        'type':'payment_intent.created','data':deepcopy(data)}
    assert post(client,event).status_code==400
    for method in db.values(): method.assert_not_awaited()
