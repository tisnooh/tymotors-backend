"""Independent adversarial receiver/receipt checks, synthetic HMAC only.

These run the real HTTP routes and Stripe signature verification against a
recording in-memory database adapter. They make no provider or database calls.
They are not evidence of live merchant access, settlement SQL or shipping.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import server


SIGNING_SECRET = 'whsec_independent_synthetic_legacy_receiver'
GUEST = 'independent_synthetic_guest_owner'
SID = 'cs_test_IndependentSharedProviderIdentity'


def signed(event):
    raw = json.dumps(event, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(SIGNING_SECRET.encode(), stamp.encode() + b'.' + raw,
                      hashlib.sha256).hexdigest()
    return raw, {'Stripe-Signature': 't=' + stamp + ',v1=' + digest}


def configure_legacy(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings,
        stripe_mode='live', stripe_legacy_webhook_mode='test',
        stripe_webhook_secret=SIGNING_SECRET, stripe_webhook_profiles_json=''))
    for name in ('select', 'insert', 'update', 'rpc'):
        monkeypatch.setattr(server.db, name, AsyncMock(return_value=[]))
    return TestClient(server.app)


@pytest.mark.parametrize('kind,obj_type,identity', [
    ('payment_intent.payment_failed', 'payment_intent', 'pi_IndependentSynthetic'),
    ('checkout.session.expired', 'checkout.session', SID),
    ('checkout.session.async_payment_failed', 'checkout.session', SID),
])
def test_signed_old_failure_cannot_target_new_live_order_through_metadata(
        monkeypatch, kind, obj_type, identity):
    client = configure_legacy(monkeypatch)
    event = {'id': 'evt_IndependentFailure', 'object': 'event', 'livemode': False,
        'type': kind, 'data': {'object': {'id': identity, 'object': obj_type,
            'metadata': {'order_id': str(uuid4())}}}}
    raw, headers = signed(event)
    assert client.post('/api/stripe/webhook', content=raw, headers=headers).status_code == 200
    assert not any(call.args[0] == 'orders' for call in server.db.update.await_args_list)
    server.db.rpc.assert_not_awaited()
    # A receipt is still written, preserving review of late/out-of-order failure.
    assert any(call.args[0] == 'stripe_events' and
               call.args[1].get('error_message') == 'requires_payment_reconciliation'
               for call in server.db.update.await_args_list)


@pytest.mark.parametrize('delegation', [
    {'account': 'acct_IndependentForeign'}, {'account': None},
    {'context': 'acct_IndependentForeign'}, {'context': None},
])
def test_signed_delegated_event_never_enters_direct_legacy_journal(monkeypatch, delegation):
    client = configure_legacy(monkeypatch)
    event = {'id': 'evt_IndependentDelegated', 'object': 'event', 'livemode': False,
        'type': 'payment_intent.created', 'data': {'object': {
            'id': 'pi_IndependentSynthetic', 'object': 'payment_intent'}}, **delegation}
    raw, headers = signed(event)
    assert client.post('/api/stripe/webhook', content=raw, headers=headers).status_code == 400
    for name in ('select', 'insert', 'update', 'rpc'):
        getattr(server.db, name).assert_not_awaited()


def receipt_setup(monkeypatch, context_owners, legacy_owner):
    profiles, bindings, attempts, orders, quotes = [], {}, {}, {}, {}
    for index, owner in enumerate(context_owners):
        ref, account = 'audit-' + str(index), 'acct_Independent' + str(index)
        aid, oid, qid = str(uuid4()), str(uuid4()), str(uuid4())
        profiles.append({'reference': ref, 'mode': 'sandbox', 'account_id': account,
                         'signing_secret': 'whsec_independent_synthetic_' + str(index)})
        bindings[account] = {'attempt_id': aid, 'session_id': SID,
            'stripe_account_id': account, 'stripe_profile_ref': ref, 'is_test': True}
        attempts[aid] = {'id': aid, 'order_id': oid, 'commerce_quote_id': qid,
            'session_id': SID, 'stripe_account_id': account,
            'stripe_profile_ref': ref, 'is_test': True}
        orders[oid] = {'id': oid, 'commerce_quote_id': qid, 'user_id': None,
            'guest_session_id': owner, 'stripe_account_id': account,
            'stripe_profile_ref': ref, 'is_test': True, 'stripe_session_id': SID}
        quotes[qid] = {'id': qid, 'owner_user_id': None, 'owner_guest_session': owner}
    legacy = None if legacy_owner is None else {'id': str(uuid4()), 'user_id': None,
        'guest_session_id': legacy_owner, 'stripe_session_id': SID,
        'stripe_account_id': None, 'is_test': True}

    async def select(table, *, params=None):
        params = params or {}
        if table == 'commerce_payment_sessions':
            binding = bindings.get(params['stripe_account_id'].removeprefix('eq.'))
            return [deepcopy(binding)] if binding else []
        if table == 'commerce_checkout_attempts':
            return [deepcopy(attempts[params['id'].removeprefix('eq.')])]
        if table == 'orders':
            if params.get('stripe_account_id') == 'is.null':
                return [deepcopy(legacy)] if legacy is not None else []
            return [deepcopy(orders[params['id'].removeprefix('eq.')])]
        if table == 'commerce_quotes':
            return [deepcopy(quotes[params['id'].removeprefix('eq.')])]
        if table == 'commerce_test_sessions':
            return []
        raise AssertionError(table)

    monkeypatch.setattr(server, 'settings', replace(server.settings,
        stripe_mode='live', stripe_webhook_profiles_json=json.dumps(profiles),
        stripe_webhook_secret=''))
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=select))
    for name in ('insert', 'update', 'rpc'):
        monkeypatch.setattr(server.db, name, AsyncMock())
    async def response(rows):
        return [{**row, 'payment_status': 'paid', 'status': 'paid', 'order_number': 'TY-AUDIT',
            'subtotal_cents': 100, 'shipping_amount_cents': 0, 'tax_amount_cents': 0,
            'total_cents': 100, 'currency': 'EUR', 'items': []} for row in rows]
    projection = AsyncMock(side_effect=response)
    monkeypatch.setattr(server, '_orders_with_items', projection)
    return TestClient(server.app), projection


@pytest.mark.parametrize('owners,legacy_owner', [
    ([GUEST, GUEST], None), ([GUEST, GUEST], GUEST), ([GUEST], GUEST),
])
def test_confirmation_refuses_all_owned_cross_account_or_legacy_ambiguity(
        monkeypatch, owners, legacy_owner):
    client, projection = receipt_setup(monkeypatch, owners, legacy_owner)
    result = client.get('/api/checkout-session/' + SID, headers={'X-Session-Id': GUEST})
    assert result.status_code == 404
    projection.assert_not_awaited()
    for name in ('insert', 'update', 'rpc'):
        getattr(server.db, name).assert_not_awaited()


@pytest.mark.parametrize('owners,legacy_owner', [
    ([GUEST], 'different_synthetic_guest'),
    ([GUEST, 'different_synthetic_guest'], None),
    (['different_synthetic_guest'], GUEST),
])
def test_confirmation_selects_only_owner_without_current_checkout_account_guess(
        monkeypatch, owners, legacy_owner):
    client, projection = receipt_setup(monkeypatch, owners, legacy_owner)
    result = client.get('/api/checkout-session/' + SID, headers={'X-Session-Id': GUEST})
    assert result.status_code == 200
    assert result.json()['paid'] is True
    assert projection.await_args.args[0][0]['guest_session_id'] == GUEST
    for name in ('insert', 'update', 'rpc'):
        getattr(server.db, name).assert_not_awaited()
