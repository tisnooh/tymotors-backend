"""Synthetic admin preparation only; no provider SDK/hosted database call."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import server
from app.commerce_attempt_service import CheckoutAttemptError, public_attempt
from app.supabase_rest import SupabaseError
from tests.test_commerce_checkout_params import snapshot  # noqa: F401

ADMIN = '10000000-0000-4000-8000-000000000001'
HEADERS = {'Authorization': 'Bearer attempt-admin'}


@pytest.fixture
def context(snapshot):
    limit = datetime.now(timezone.utc) + timedelta(minutes=45)
    snapshot['order']['quote_expires_at'] = limit.isoformat()
    snapshot['attempt'].update(
        quote_expires_at=limit.isoformat(), expires_at=int(limit.timestamp()), state='drafting',
        params=None, idempotency_key='checkout_test_' + uuid4().hex,
        first_requested_at=None, session_id=None,
    )
    return {key: deepcopy(snapshot[key]) for key in ('order', 'items', 'attempt')}


@pytest.fixture
def wired(monkeypatch, context):
    server.checkout_attempts.clear()
    store = deepcopy(context)

    async def user(token):
        return {'id': ADMIN} if token in {'attempt-admin', 'attempt-customer'} else None

    async def select(table, *, params=None):
        if table == 'profiles':
            return [{'id': ADMIN, 'role': 'admin'}]
        if table == 'commerce_checkout_attempts' and params['id'] == 'eq.' + store['attempt']['id']:
            return [deepcopy(store['attempt'])]
        return []

    async def rpc(name, payload):
        attempt = store['attempt']
        if name == 'commerce_prepare_checkout_attempt':
            return deepcopy(store)
        if name == 'commerce_store_checkout_params':
            assert attempt['state'] == 'drafting'
            attempt.update(state='ready', params=deepcopy(payload['p_params']), params_hash='synthetic-hash')
            return deepcopy(attempt)
        if name == 'commerce_cancel_checkout_draft':
            if attempt['state'] not in {'drafting', 'ready', 'cancelled'} or attempt['first_requested_at'] is not None:
                raise SupabaseError(409, 'Reconciliation required, cannot release provider-unknown hold')
            attempt['state'] = 'cancelled'
            return deepcopy(attempt)
        raise AssertionError(name)

    monkeypatch.setattr(server.db, 'get_user', user)
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=select))
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=rpc))
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test', frontend_url='https://shop.example.com'))
    remote = AsyncMock()
    monkeypatch.setattr(server, 'stripe_client', SimpleNamespace(v1=SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=remote)))))
    return TestClient(server.app), store, remote


def prepare_url(context):
    return '/api/admin/commerce/orders/' + context['order']['id'] + '/checkout-attempt'


def attempt_url(context):
    return '/api/admin/commerce/checkout-attempts/' + context['attempt']['id']


def test_prepare_persists_builder_parameters_then_projects_no_private_data(wired, context):
    client, store, remote = wired
    response = client.post(prepare_url(context), headers=HEADERS)
    assert response.status_code == 200, response.text
    public = response.json()
    assert public['state'] == 'ready' and public['attempt_id'] == context['attempt']['id']
    assert public['payment_available'] is False and public['is_test'] is True
    assert public['requires_reconciliation'] is False
    assert response.headers['cache-control'] == 'no-store'
    for forbidden in ('idempotency_key', 'params', 'params_hash', 'frontend_origin', 'shipping_address', 'private_supplier_cost'):
        assert forbidden not in response.text
    calls = server.db.rpc.call_args_list
    assert [call.args[0] for call in calls] == ['commerce_prepare_checkout_attempt', 'commerce_store_checkout_params']
    assert calls[0].args[1] == {'p_actor': ADMIN, 'p_order_id': context['order']['id'], 'p_frontend_origin': 'https://shop.example.com'}
    assert store['attempt']['params']['metadata']['order_id'] == context['order']['id']
    assert store['attempt']['params']['expires_at'] == context['attempt']['expires_at']
    assert store['attempt']['params']['line_items'][0]['price_data']['product_data']['images'] == [context['items'][0]['image_url']]
    remote.assert_not_awaited()


def test_repeated_prepare_restores_same_attempt_and_never_rebuilds_parameters(wired, context):
    client, store, remote = wired
    first = client.post(prepare_url(context), headers=HEADERS).json()
    original_params = deepcopy(store['attempt']['params'])
    server.db.rpc.reset_mock()
    # These simulated source objects are not reinterpreted on an existing attempt.
    store['items'][0]['unit_amount_cents'] = 999
    repeated = client.post(prepare_url(context), headers=HEADERS)
    assert repeated.status_code == 200 and repeated.json() == first
    assert store['attempt']['params'] == original_params
    assert [call.args[0] for call in server.db.rpc.call_args_list] == ['commerce_prepare_checkout_attempt']
    remote.assert_not_awaited()


@pytest.mark.parametrize('state', ['creating', 'unknown', 'session_created'])
def test_unknown_or_started_attempt_restores_state_without_release_or_new_provider_call(wired, context, state):
    client, store, remote = wired
    store['attempt'].update(state=state, first_requested_at=datetime.now(timezone.utc).isoformat(), expires_at=1)
    response = client.post(prepare_url(context), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['requires_reconciliation'] is True and response.json()['expired_locally'] is True
    assert [call.args[0] for call in server.db.rpc.call_args_list] == ['commerce_prepare_checkout_attempt']
    assert store['attempt']['state'] == state
    remote.assert_not_awaited()


def test_invalid_builder_cancels_only_before_any_provider_request(wired, context):
    client, store, remote = wired
    store['items'][0]['image_url'] = 'https://www.scpautomotive.co.uk/cdn/item.jpg'
    response = client.post(prepare_url(context), headers=HEADERS)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'checkout_image_use_denied'
    assert store['attempt']['state'] == 'cancelled'
    assert [call.args[0] for call in server.db.rpc.call_args_list] == ['commerce_prepare_checkout_attempt', 'commerce_cancel_checkout_draft']
    remote.assert_not_awaited()


def test_store_timeout_does_not_cancel_an_ambiguous_database_outcome(wired, context, monkeypatch):
    client, store, remote = wired
    original = server.db.rpc.side_effect

    async def rpc(name, payload):
        result = await original(name, payload)
        if name == 'commerce_store_checkout_params':
            raise SupabaseError(502, 'Synthetic response lost after local commit')
        return result

    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=rpc))
    assert client.post(prepare_url(context), headers=HEADERS).status_code == 502
    assert store['attempt']['state'] == 'ready'
    assert not any(call.args[0] == 'commerce_cancel_checkout_draft' for call in server.db.rpc.call_args_list)
    second = client.post(prepare_url(context), headers=HEADERS)
    assert second.status_code == 200 and second.json()['state'] == 'ready'
    remote.assert_not_awaited()


def test_api_cancellation_is_idempotent_and_database_blocks_after_claim(wired, context):
    client, store, remote = wired
    client.post(prepare_url(context), headers=HEADERS)
    url = attempt_url(context) + '/cancel-draft'
    first = client.post(url, headers=HEADERS)
    assert first.status_code == 200 and first.json()['state'] == 'cancelled'
    assert client.post(url, headers=HEADERS).json() == first.json()
    store['attempt'].update(state='unknown', first_requested_at=datetime.now(timezone.utc).isoformat())
    assert client.post(url, headers=HEADERS).status_code == 409
    assert store['attempt']['state'] == 'unknown'
    remote.assert_not_awaited()


def test_read_is_admin_only_and_uses_safe_projection(wired, context, monkeypatch):
    client, _, _ = wired
    assert client.get(attempt_url(context)).status_code == 401
    assert client.get(attempt_url(context), headers=HEADERS).json()['attempt_id'] == context['attempt']['id']
    assert client.get('/api/admin/commerce/checkout-attempts/' + str(uuid4()), headers=HEADERS).status_code == 404
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'id': ADMIN, 'role': 'customer'}]))
    assert client.get(attempt_url(context), headers={'Authorization': 'Bearer attempt-customer'}).status_code == 403


def test_writes_require_admin_and_test_mode_before_database(wired, context, monkeypatch):
    client, _, remote = wired
    assert client.post(prepare_url(context)).status_code == 401
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live'))
    assert client.post(prepare_url(context), headers=HEADERS).status_code == 409
    assert client.post(attempt_url(context) + '/cancel-draft', headers=HEADERS).status_code == 409
    server.db.rpc.assert_not_awaited()
    remote.assert_not_awaited()


def test_client_body_cannot_change_origin_expiration_or_frozen_price(wired, context):
    client, store, remote = wired
    response = client.post(prepare_url(context), headers=HEADERS, json={
        'frontend_origin': 'https://attacker.example.com', 'expires_at': 1, 'total_cents': 1, 'is_test': False})
    assert response.status_code == 200
    assert store['attempt']['params']['success_url'].startswith('https://shop.example.com/')
    assert store['attempt']['total_cents'] == context['order']['total_cents']
    assert store['attempt']['is_test'] is True
    remote.assert_not_awaited()


def test_private_database_error_is_not_echoed(wired, context, monkeypatch):
    client, _, _ = wired
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=SupabaseError(409, 'SECRET-SUPPLIER-REFERENCE')))
    response = client.post(prepare_url(context), headers=HEADERS)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'checkout_attempt_conflict'
    assert 'SECRET' not in response.text


def test_malformed_or_cross_order_context_cannot_store_params(wired, context):
    client, store, _ = wired
    store['attempt']['order_id'] = str(uuid4())
    assert client.post(prepare_url(context), headers=HEADERS).status_code == 409
    assert len(server.db.rpc.call_args_list) == 1


def test_replayed_attempt_must_still_match_its_quote_and_test_order(wired, context):
    client, store, _ = wired
    store['attempt'].update(state='ready', commerce_quote_id=str(uuid4()))
    assert client.post(prepare_url(context), headers=HEADERS).status_code == 409
    assert len(server.db.rpc.call_args_list) == 1
    store['attempt']['commerce_quote_id'] = store['order']['commerce_quote_id']
    store['order']['is_test'] = False
    assert client.post(prepare_url(context), headers=HEADERS).status_code == 409


@pytest.mark.parametrize('field,value', [('state', 'paid'), ('is_test', False), ('expires_at', '123'), ('id', 'bad')])
def test_projection_fails_closed_for_malformed_internal_state(context, field, value):
    row = {**context['attempt'], field: value}
    with pytest.raises(CheckoutAttemptError, match='invalid_checkout_attempt'):
        public_attempt(row)
