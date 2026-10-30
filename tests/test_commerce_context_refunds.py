"""Synthetic normalization/HTTP contract only; no provider or SQL calls."""
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_webhook_profiles import StripeWebhookProfile
from app.commerce_context_refunds import (
    normalize_context_refund_event, record_signed_context_refund, create_context_refund_router)


ACCOUNT = 'acct_ContextRefundSynthetic'


def profile(mode='sandbox'):
    return StripeWebhookProfile('refund-' + mode, CheckoutServerContext(mode, ACCOUNT),
                                'whsec_synthetic_only_context_refund')


def event(live=False):
    return {'object': 'event', 'id': 'evt_ContextRefundSynthetic', 'created': 1700000000,
            'livemode': live, 'context': ACCOUNT, 'type': 'refund.updated',
            'data': {'object': {'object': 'refund', 'id': 're_ContextRefundSynthetic',
                'livemode': live, 'payment_intent': 'pi_ContextRefundSynthetic',
                'charge': 'ch_ContextRefundSynthetic', 'amount': 100, 'currency': 'eur', 'status': 'succeeded'}}}


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
def test_scope_preserved_and_input_never_changed(mode):
    source = event(mode == 'production')
    before = deepcopy(source)
    result = normalize_context_refund_event(source, profile(mode))
    assert result['amount_cents'] == 100 and result['refund_status'] == 'succeeded'
    assert result['payment_intent_id'] == 'pi_ContextRefundSynthetic'
    assert source == before
    assert set(result) == {'event_id','event_type','event_created','refund_id','payment_intent_id',
                           'charge_id','amount_cents','currency','refund_status','charge_refunded_cents'}


@pytest.mark.parametrize('changes', [{'livemode': True}, {'livemode': 0}, {'context': 'acct_Foreign'},
                                   {'context': None}, {'account': ACCOUNT}, {'object': 'v2.core.event'}])
def test_parent_scope_rejected(changes):
    with pytest.raises(ValueError): normalize_context_refund_event({**event(), **changes}, profile())


@pytest.mark.parametrize('field', ['self', 'payment_intent', 'charge'])
def test_expanded_mode_is_not_laundered(field):
    source = event(True)
    obj = source['data']['object']
    if field == 'self': obj['livemode'] = False
    else: obj[field] = {'object': field, 'id': 'pi_Synthetic' if field == 'payment_intent' else 'ch_Synthetic', 'livemode': False}
    with pytest.raises(ValueError): normalize_context_refund_event(source, profile('production'))


@pytest.mark.parametrize('status', ['pending','failed','canceled',None])
def test_no_success_inferred(status):
    source = event(); source['data']['object']['status'] = status
    assert normalize_context_refund_event(source, profile())['refund_status'] == status


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.mark.anyio
async def test_only_explicit_server_scope_reaches_rpc():
    db = type('Db', (), {'rpc': AsyncMock(return_value={'received': True})})()
    await record_signed_context_refund(db, profile('production'), event(True))
    args = db.rpc.call_args.args
    assert args[0] == 'commerce_record_context_refund'
    assert args[1]['p_is_test'] is False and args[1]['p_stripe_account_id'] == ACCOUNT
    assert args[1]['p_profile_ref'] == 'refund-production'


def test_admin_route_requires_auth_and_forwards_cas_evidence_only():
    db = type('Db', (), {'rpc': AsyncMock(return_value={'review_released': False})})()
    async def admin(authorization: str | None = Header(default=None)):
        if authorization != 'Synthetic': raise HTTPException(401)
        return {'id': '10000000-0000-4000-8000-000000000001'}
    app = FastAPI(); app.include_router(create_context_refund_router(db, admin)); client = TestClient(app)
    oid = str(uuid4()); path = '/api/admin/commerce/context/orders/' + oid + '/refund-review'
    payload = {'expected_updated_at': datetime.now(timezone.utc).isoformat(), 'evidence_ref': 'synthetic-review'}
    assert client.post(path, json=payload).status_code == 401
    db.rpc.assert_not_awaited()
    assert client.post(path, json={**payload, 'review_released': True}, headers={'Authorization': 'Synthetic'}).status_code == 422
    assert client.post(path, json=payload, headers={'Authorization': 'Synthetic'}).json() == {'review_released': False}
    assert db.rpc.call_args.args[1]['p_order_id'] == oid
    assert db.rpc.call_args.args[1]['p_evidence_ref'] == payload['evidence_ref']
