"""Signed synthetic failures and injected storage only; no Stripe/provider I/O."""
from copy import deepcopy
from unittest.mock import AsyncMock
from dataclasses import replace
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import server
from app.commerce_payment_service import CommerceTestPayments, CommercePaymentError
from app.supabase_rest import SupabaseError
from tests.test_stripe_configuration import configure_signed_webhook, signed_payload

KINDS = ('checkout.session.expired', 'checkout.session.async_payment_failed', 'payment_intent.payment_failed')


def failure(kind=KINDS[0]):
    intent = kind == KINDS[2]
    return {'id':'evt_failure_fixture', 'object':'event', 'livemode':False, 'type':kind,
            'data':{'object':{'object':'payment_intent' if intent else 'checkout.session',
                'id':'pi_failure_fixture' if intent else 'cs_test_failure_fixture',
                'metadata':{'attempt_id':'untrusted-routing-only', 'customer_email':'PRIVATE'},
                'last_payment_error':{'message':'PRIVATE'}}}}


class ReceiptStore:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.audit = []
        self.insert_error = self.update_error = None
        self.race = None

    async def select(self, table, *, params):
        assert table == 'stripe_events'
        self.calls.append(('select', table))
        row = self.rows.get(params['event_id'][3:])
        return [deepcopy(row)] if row else []

    async def insert(self, table, payload):
        if table == 'admin_audit':
            self.audit.append(deepcopy(payload)); return [payload]
        assert table == 'stripe_events'
        self.calls.append(('insert', table))
        if self.insert_error: raise self.insert_error
        if self.race:
            if self.race == 'committed': self.rows[payload['event_id']] = deepcopy(payload)
            raise SupabaseError(409, 'synthetic race')
        assert payload['event_id'] not in self.rows
        self.rows[payload['event_id']] = deepcopy(payload)
        return [deepcopy(payload)]

    async def update(self, table, payload, *, params):
        assert table == 'stripe_events'
        self.calls.append(('update', table))
        if self.update_error: raise self.update_error
        row = self.rows.get(params['event_id'][3:])
        if not row or row['event_type'] != params['event_type'][3:]: return []
        row.update(deepcopy(payload))
        return [deepcopy(row)]


@pytest.fixture
def boundary(monkeypatch):
    configure_signed_webhook(monkeypatch)
    db = ReceiptStore()
    for name in ('select','insert','update'): monkeypatch.setattr(server.db,name,getattr(db,name))
    rpc, email = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db,'rpc',rpc)
    monkeypatch.setattr(server,'_send_order_email',email)
    return TestClient(server.app),db,rpc,email


def post(client,event):
    body,headers = signed_payload(event)
    return client.post('/api/stripe/webhook',content=body,headers=headers)


@pytest.mark.parametrize('kind',KINDS)
def test_signed_failure_is_durable_minimal_and_duplicate_safe(boundary,kind):
    client,db,rpc,email = boundary
    event = failure(kind)
    first = post(client,event)
    assert first.status_code == 200
    assert first.json() == {'received':True,'requires_reconciliation':True,'is_test':True,
                            'event_recorded':True,'duplicate':False}
    assert post(client,event).json()['duplicate'] is True
    assert len(db.rows) == 1
    row = db.rows[event['id']]
    assert row['status'] == 'completed' and row['error_message'] == 'requires_payment_reconciliation'
    assert row['payload'] == {'scope':'test_failure_receipt_only',
                              'object_id':event['data']['object']['id'],'requires_reconciliation':True}
    assert 'PRIVATE' not in str(db.rows)
    assert db.calls.count(('insert','stripe_events')) == 1
    rpc.assert_not_awaited(); email.assert_not_awaited()


@pytest.mark.parametrize('phase',['insert','update'])
def test_storage_failure_is_not_acknowledged_and_retry_preserves_one_receipt(boundary,phase):
    client,db,rpc,email = boundary
    setattr(db,phase+'_error',SupabaseError(503,'synthetic unavailable'))
    assert post(client,failure()).status_code == 500
    setattr(db,phase+'_error',None)
    assert post(client,failure()).status_code == 200
    assert len(db.rows) == 1
    rpc.assert_not_awaited(); email.assert_not_awaited()


@pytest.mark.parametrize('change',['type','object_id'])
def test_reused_identity_with_another_type_or_object_requires_review(boundary,change):
    client,db,rpc,email=boundary
    original=failure()
    assert post(client,original).status_code == 200
    altered=failure(KINDS[1]) if change=='type' else failure()
    if change=='object_id': altered['data']['object']['id']='cs_test_another_fixture'
    before=deepcopy(db.rows)
    assert post(client,altered).status_code == 500
    assert db.rows == before
    rpc.assert_not_awaited(); email.assert_not_awaited()


@pytest.mark.parametrize('race',['committed','invisible'])
def test_insert_conflict_has_one_bounded_reread(boundary,race):
    client,db,_,_=boundary
    db.race=race
    response=post(client,failure())
    assert response.status_code == (200 if race=='committed' else 500)
    assert db.calls.count(('insert','stripe_events')) == 1
    assert db.calls.count(('select','stripe_events')) == 2


@pytest.mark.parametrize('change',['bad_id','live_session','wrong_object','missing_object'])
def test_malformed_receipt_never_writes_financial_tables(boundary,change):
    client,db,rpc,email=boundary
    event=failure()
    if change=='bad_id': event['id']='not-an-event'
    if change=='live_session': event['data']['object']['id']='cs_live_not_allowed'
    if change=='wrong_object': event['data']['object']['object']='payment_intent'
    if change=='missing_object': event['data']['object'].pop('id')
    assert post(client,event).status_code == 500
    assert not db.calls and not db.rows
    rpc.assert_not_awaited(); email.assert_not_awaited()


def test_invalid_signature_cannot_create_a_receipt(boundary):
    client,db,rpc,email=boundary
    body,_=signed_payload(failure())
    assert client.post('/api/stripe/webhook',content=body,
                       headers={'Stripe-Signature':'invalid'}).status_code == 400
    assert not db.calls
    rpc.assert_not_awaited(); email.assert_not_awaited()


def test_legacy_checkout_without_webhook_refuses_before_cart_or_provider(monkeypatch):
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='test',
        stripe_secret_key='sk_test_synthetic_not_a_credential',stripe_webhook_secret=''))
    create=AsyncMock()
    monkeypatch.setattr(server,'stripe_client',SimpleNamespace(v1=SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
    cart=AsyncMock(); monkeypatch.setattr(server,'_cart_for',cart)
    response=TestClient(server.app).post('/api/create-checkout-session',
        headers={'X-Session-Id':'synthetic_guest_checkout_guard'})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Signed Stripe webhook is not configured'
    cart.assert_not_awaited(); create.assert_not_awaited()
