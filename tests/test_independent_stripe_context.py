"""Independent account-context checks: real SDK HMAC, synthetic bodies only.

No provider, hosted database, payment, shipping or deployed-system claim is made.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_context_payments import ContextCheckoutPayments
from app.commerce_webhook_profiles import StripeWebhookProfile
from tests.test_email_system import settings


ACCOUNT = 'acct_IndependentPinnedOriginal'
OTHER = 'acct_IndependentForeignContext'
SECRET = 'whsec_independent_context_synthetic_only'
REF = 'independent-context'
INVALID_CONTEXTS = [None, '', False, True, 0, [], {}, OTHER, 'org_Independent',
    ACCOUNT + '/acct_Connected', ' ' + ACCOUNT, ACCOUNT + ' ', ACCOUNT.lower()]


def sample(**changes):
    result = {'id': 'evt_IndependentContextSnapshot', 'object': 'event',
        'livemode': False, 'context': ACCOUNT, 'type': 'payment_intent.payment_failed',
        'data': {'object': {'id': 'pi_IndependentContext', 'object': 'payment_intent'}}}
    result.update(changes)
    return result


def sign(event, secret=SECRET):
    raw = json.dumps(event, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return raw, {'Stripe-Signature': 't=' + stamp + ',v1=' + digest}


def wire(monkeypatch, *, legacy=False, expected=ACCOUNT):
    profiles = [{'reference': REF, 'mode': 'sandbox', 'account_id': ACCOUNT,
                 'signing_secret': SECRET}]
    monkeypatch.setattr(server, 'settings', replace(server.settings,
        stripe_mode='live', stripe_legacy_webhook_mode='test',
        stripe_legacy_account_id=expected,
        stripe_webhook_secret=SECRET if legacy else '',
        stripe_webhook_profiles_json='' if legacy else json.dumps(profiles),
        stripe_checkout_profile=''))
    for name in ('select', 'insert', 'update', 'rpc'):
        monkeypatch.setattr(server.db, name, AsyncMock(return_value=[]))
    server.db.rpc.return_value = {'received': True, 'requires_reconciliation': True}
    return TestClient(server.app), '/api/stripe/webhook' + ('' if legacy else '/' + REF)


def assert_no_database():
    for name in ('select', 'insert', 'update', 'rpc'):
        getattr(server.db, name).assert_not_awaited()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('context', INVALID_CONTEXTS)
def test_signed_wrong_or_non_scalar_context_is_rejected_without_database(monkeypatch, legacy, context):
    client, route = wire(monkeypatch, legacy=legacy)
    raw, headers = sign(sample(context=context))
    assert client.post(route, content=raw, headers=headers).status_code == 400
    assert_no_database()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('account', [None, ACCOUNT, OTHER])
def test_connect_account_field_is_always_rejected_even_with_matching_context(monkeypatch, legacy, account):
    client, route = wire(monkeypatch, legacy=legacy)
    raw, headers = sign(sample(account=account))
    assert client.post(route, content=raw, headers=headers).status_code == 400
    assert_no_database()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('change', ['mode', 'invalid_signature', 'unsigned_context_change'])
def test_correct_context_cannot_bypass_signature_or_mode(monkeypatch, legacy, change):
    client, route = wire(monkeypatch, legacy=legacy)
    event = sample(livemode=True) if change == 'mode' else sample()
    raw, headers = sign(event, SECRET + 'wrong' if change == 'invalid_signature' else SECRET)
    if change == 'unsigned_context_change':
        raw = raw.replace(ACCOUNT.encode(), OTHER.encode())
    assert client.post(route, content=raw, headers=headers).status_code == 400
    assert_no_database()


@pytest.mark.parametrize('omit_context', [False, True])
def test_profile_http_records_only_its_pinned_scope(monkeypatch, omit_context):
    client, route = wire(monkeypatch)
    event = sample()
    if omit_context:
        event.pop('context')
    raw, headers = sign(event)
    response = client.post(route, content=raw, headers=headers)
    assert response.status_code == 200
    server.db.rpc.assert_awaited_once_with('commerce_record_context_event', {
        'p_event_id': event['id'], 'p_event_type': event['type'],
        'p_object_id': 'pi_IndependentContext', 'p_is_test': True,
        'p_stripe_account_id': ACCOUNT, 'p_profile_ref': REF})
    server.db.select.assert_not_awaited()
    server.db.insert.assert_not_awaited()
    server.db.update.assert_not_awaited()


@pytest.mark.parametrize('omit_context', [False, True])
def test_legacy_context_bound_to_original_account_not_current_checkout(monkeypatch, omit_context):
    client, route = wire(monkeypatch, legacy=True)
    event = sample(type='payment_intent.created')
    if omit_context:
        event.pop('context')
    raw, headers = sign(event)
    assert client.post(route, content=raw, headers=headers).status_code == 200
    # New checkout is live in wire(), while this historical receiver stays test.
    server.db.rpc.assert_not_awaited()
    assert all(call.args[0] == 'stripe_events' for call in server.db.update.await_args_list)
    assert len(server.db.insert.await_args_list) == 1


def test_legacy_unconfigured_account_is_not_inferred_from_signed_event(monkeypatch):
    client, route = wire(monkeypatch, legacy=True, expected='')
    raw, headers = sign(sample())
    assert client.post(route, content=raw, headers=headers).status_code == 400
    assert_no_database()


@pytest.mark.parametrize('signing_key', [SECRET, SECRET + 'second'])
def test_another_profile_never_accepts_first_profiles_context(monkeypatch, signing_key):
    client, _ = wire(monkeypatch)
    profiles = [{'reference': REF, 'mode': 'sandbox', 'account_id': ACCOUNT,
                 'signing_secret': SECRET},
                {'reference': 'another-profile', 'mode': 'sandbox', 'account_id': OTHER,
                 'signing_secret': SECRET + 'second'}]
    monkeypatch.setattr(server, 'settings', replace(server.settings,
        stripe_webhook_profiles_json=json.dumps(profiles)))
    raw, headers = sign(sample(), signing_key)
    response = client.post('/api/stripe/webhook/another-profile', content=raw, headers=headers)
    assert response.status_code == 400
    assert SECRET not in response.text
    assert_no_database()


@pytest.mark.parametrize('bad_account', [None, False, 0, [], {}, 'acct_bad_with_underscore', 'org_Independent', ACCOUNT + ' '])
def test_settings_reject_invalid_explicit_legacy_account(bad_account):
    config = settings(email_enabled=False, stripe_legacy_account_id=bad_account)
    with pytest.raises(RuntimeError, match='STRIPE_LEGACY_ACCOUNT_ID'):
        config.validate()


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
@pytest.mark.parametrize('context', INVALID_CONTEXTS)
async def test_service_second_boundary_rejects_context_before_database(context):
    db = type('RecordingDb', (), {})()
    for name in ('select', 'insert', 'update', 'rpc'):
        setattr(db, name, AsyncMock())
    service = ContextCheckoutPayments(db, StripeWebhookProfile(REF,
        CheckoutServerContext('sandbox', ACCOUNT), SECRET))
    with pytest.raises(ValueError):
        await service.accept_signed_event(sample(context=deepcopy(context)))
    for name in ('select', 'insert', 'update', 'rpc'):
        getattr(db, name).assert_not_awaited()
