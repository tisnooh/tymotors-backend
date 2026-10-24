"""Synthetic quote API: auth boundaries and projection, not hosted payment QA."""
from copy import deepcopy
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import server
from app.commerce_models import CartQuoteInput, ShippingRateInput
from app.commerce_quote_engine import CartQuoteError, build_cart_quote
from app.commerce_quote_service import CartQuoteService, public_quote
from app.supabase_rest import SupabaseError
from tests.test_commerce_quote_engine import CART, PROFILE, context  # noqa: F401

GUEST = 'synthetic_quote_owner_12345678'
OTHER = 'synthetic_quote_other_12345678'
QUOTE = str(uuid4())
ORDER = str(uuid4())
ADDRESS = {'name': 'Synthetic Customer', 'line1': '1 Synthetic street', 'line2': '',
           'city': 'Paris', 'state': '', 'postal_code': '75001', 'country': 'FR', 'phone': ''}


@pytest.fixture
def request_data():
    return {'request_key': str(uuid4()), 'destination': deepcopy(ADDRESS), 'mode': 'tracked'}


@pytest.fixture
def quote_fixture(context, request_data):
    context['cart'].update(user_id=None, guest_session_id=GUEST, currency='EUR')
    for row in context['products']:
        row['currency'] = 'EUR'
    for key in ('offers', 'rates'):
        for row in context[key]:
            row['valid_until'] = '2099-01-01T00:00:00+00:00'
    payload = build_cart_quote(context)
    return {
        'id': QUOTE, 'cart_id': CART, 'owner_user_id': None, 'owner_guest_session': GUEST,
        'country': 'FR', 'mode': 'tracked', 'destination': deepcopy(ADDRESS),
        'source_context': deepcopy(context), 'payload': payload, 'currency': 'EUR',
        **{key: payload[key] for key in ('subtotal_cents', 'shipping_cents', 'tax_cents', 'total_cents')},
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat(),
        'request_key': request_data['request_key'], 'state': 'ready',
    }


@pytest.fixture
def wired(monkeypatch, context, quote_fixture):
    server.quote_attempts.clear()
    stored = []

    async def user(token):
        return {'id': PROFILE} if token in {'quote-admin', 'quote-customer'} else None

    async def select(table, *, params=None):
        params = params or {}
        if table == 'profiles':
            return [{'id': PROFILE, 'role': 'admin'}]
        if table == 'carts':
            if params.get('guest_session_id') == 'eq.' + GUEST:
                return [context['cart']]
            if params.get('user_id') == 'eq.' + PROFILE:
                return [{**context['cart'], 'user_id': PROFILE, 'guest_session_id': None}]
            return []
        if table == 'commerce_quotes':
            rows = stored
            for key, value in params.items():
                if key != 'limit':
                    rows = [row for row in rows if str(row.get(key)) == value.removeprefix('eq.')]
            return deepcopy(rows)
        return []

    async def rpc(name, data):
        if name == 'commerce_cart_context':
            return deepcopy(context)
        if name == 'commerce_save_quote':
            result = {**deepcopy(quote_fixture), 'payload': deepcopy(data['p_payload'])}
            stored.append(result)
            return deepcopy(result)
        if name == 'commerce_order_from_quote':
            return {'order_id': ORDER, 'order_number': 'SYNTHETIC-ORDER', 'is_test': True,
                    'private_supplier_cost': 12345}
        raise AssertionError(name)

    monkeypatch.setattr(server.db, 'get_user', user)
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=select))
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=rpc))
    return TestClient(server.app), stored


def test_quote_api_persists_coherent_private_sources_projects_public_only_and_retries(wired, request_data):
    client, stored = wired
    headers = {'X-Session-Id': GUEST}
    response = client.post('/api/cart/quote', json=request_data, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total_cents'] == 24600 and result['shipping_cents'] == 600
    assert result['checkout_available'] is False and result['quote_id'] == QUOTE
    assert 'not_payment_or_reservation' in result['scope']
    assert response.headers['cache-control'] == 'no-store'
    for private in ('supplier_sku', 'supplier_id', 'responsible_agent_id', 'evidence_refs',
                    'landed_cost_cents', 'owner_guest_session', 'source_context', 'destination'):
        assert private not in response.text
    calls = server.db.rpc.call_args_list
    assert [call.args[0] for call in calls] == ['commerce_cart_context', 'commerce_save_quote']
    assert calls[0].args[1]['p_postal_code'] == '75001'
    assert calls[1].args[1]['p_source']['cart']['id'] == CART
    assert calls[1].args[1]['p_payload']['groups'][0]['evaluation']['supplier_sku']
    server.db.rpc.reset_mock()
    # Catalogue movement after persistence does not rewrite a retry.
    repeated = client.post('/api/cart/quote', json=request_data, headers=headers)
    assert repeated.json() == result and len(stored) == 1
    server.db.rpc.assert_not_awaited()
    assert client.get('/api/cart/quote/' + QUOTE, headers=headers).json() == result


def test_request_key_cannot_change_destination_or_mode(wired, request_data):
    client, _ = wired
    headers = {'X-Session-Id': GUEST}
    assert client.post('/api/cart/quote', json=request_data, headers=headers).status_code == 200
    server.db.rpc.reset_mock()
    changed = deepcopy(request_data)
    changed['destination']['postal_code'] = '13001'
    assert client.post('/api/cart/quote', json=changed, headers=headers).json()['detail']['code'] == 'request_key_conflict'
    changed = {**request_data, 'mode': 'express'}
    assert client.post('/api/cart/quote', json=changed, headers=headers).status_code == 409
    server.db.rpc.assert_not_awaited()


def test_guest_cannot_read_others_quote_and_login_does_not_reuse_guest_identity(wired, request_data):
    client, _ = wired
    assert client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST}).status_code == 200
    assert client.get('/api/cart/quote/' + QUOTE, headers={'X-Session-Id': OTHER}).status_code == 404
    response = client.get('/api/cart/quote/' + QUOTE, headers={
        'X-Session-Id': GUEST, 'Authorization': 'Bearer quote-customer'})
    assert response.status_code == 409  # same synthetic cart ID, but guest ownership differs
    assert 'supplier' not in response.text and GUEST not in response.text


def test_malformed_session_and_invalid_token_cannot_reach_quote_storage(wired, request_data):
    client, _ = wired
    server.db.rpc.reset_mock()
    assert client.post('/api/cart/quote', json=request_data).status_code == 400
    assert client.get('/api/cart/quote/' + QUOTE, headers={'X-Session-Id': 'bad'}).status_code == 400
    assert client.post('/api/cart/quote', json=request_data, headers={
        'X-Session-Id': GUEST, 'Authorization': 'Bearer invalid'}).status_code == 401
    server.db.rpc.assert_not_awaited()


@pytest.mark.parametrize('field,value', [('postal_code', '---'), ('line1', ''), ('city', ''),
                                        ('country', 'fr'), ('phone', '123\u0000secret')])
def test_destination_validation_no_address_echo(wired, request_data, field, value):
    client, _ = wired
    request_data['destination'][field] = value
    response = client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST})
    assert response.status_code == 422
    assert 'Synthetic street' not in response.text and 'secret' not in response.text
    server.db.rpc.assert_not_awaited()


def test_customer_cannot_supply_costs_prices_source_context_or_unknown_properties(wired, request_data):
    client, _ = wired
    response = client.post('/api/cart/quote', headers={'X-Session-Id': GUEST},
                           json={**request_data, 'total_cents': 1, 'source_context': {}})
    assert response.status_code == 422
    server.db.rpc.assert_not_awaited()


def test_quote_requests_are_bounded_even_with_new_keys(wired, request_data):
    client, _ = wired
    for _ in range(20):
        response = client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST})
        assert response.status_code == 200
    server.db.rpc.reset_mock()
    response = client.post('/api/cart/quote', json={**request_data, 'request_key': str(uuid4())},
                           headers={'X-Session-Id': GUEST})
    assert response.status_code == 429
    server.db.rpc.assert_not_awaited()


def test_unsupported_destination_is_blocked_without_source_evaluation(wired, request_data):
    client, _ = wired
    request_data['destination']['country'] = 'ZZ'
    response = client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'destination_not_supported'
    server.db.rpc.assert_not_awaited()


def test_expired_superseded_and_consumed_quote_are_not_presented_as_ready(quote_fixture):
    row = deepcopy(quote_fixture)
    row['expires_at'] = '2000-01-01T00:00:00+00:00'
    assert public_quote(row)['status'] == 'expired'
    for state in ('superseded', 'consumed'):
        row['state'] = state
        assert public_quote(row)['status'] == state
        assert public_quote(row)['checkout_available'] is False
    row['expires_at'] = '2026-01-01T00:00:00'
    with pytest.raises(CartQuoteError, match='invalid_persisted_quote'):
        public_quote(row)


def test_changed_source_rejected_and_private_database_message_not_echoed(wired, request_data, monkeypatch):
    client, _ = wired
    original = server.db.rpc.side_effect

    async def rpc(name, payload):
        if name == 'commerce_save_quote':
            raise SupabaseError(409, 'source changed supplier_sku SECRET-SUPPLIER-REF')
        return await original(name, payload)

    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=rpc))
    response = client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST})
    assert response.status_code == 409
    assert response.json()['detail'] == {'code': 'quote_changed_or_unavailable'}
    assert 'SECRET' not in response.text


def test_admin_only_test_only_order_preparation_and_response_allowlist(wired, request_data, monkeypatch):
    client, _ = wired
    assert client.post('/api/cart/quote', json=request_data, headers={'X-Session-Id': GUEST}).status_code == 200
    url = '/api/admin/commerce/quotes/' + QUOTE + '/prepare-test-order'
    server.db.rpc.reset_mock()
    assert client.post(url).status_code == 401
    server.db.rpc.assert_not_awaited()
    response = client.post(url, headers={'Authorization': 'Bearer quote-admin'})
    assert response.status_code == 200, response.text
    assert response.json() == {'order_id': ORDER, 'order_number': 'SYNTHETIC-ORDER', 'is_test': True}
    assert server.db.rpc.call_args.args[1] == {
        'p_quote_id': QUOTE, 'p_user_id': None, 'p_guest_session': GUEST, 'p_is_test': True, 'p_actor': PROFILE}
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'id': PROFILE, 'role': 'customer'}]))
    server.db.rpc.reset_mock()
    assert client.post(url, headers={'Authorization': 'Bearer quote-customer'}).status_code == 403
    server.db.rpc.assert_not_awaited()


def test_live_mode_cannot_prepare_any_test_order(wired, monkeypatch):
    client, _ = wired
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live'))
    assert client.post('/api/admin/commerce/quotes/' + QUOTE + '/prepare-test-order',
                       headers={'Authorization': 'Bearer quote-admin'}).status_code == 409
    server.db.rpc.assert_not_awaited()


def test_anonymous_quote_projection_enforces_existing_image_rights_policy(quote_fixture):
    row = deepcopy(quote_fixture)
    row['payload']['groups'][0]['lines'][0]['image_url'] = 'https://www.scpautomotive.co.uk/cdn/shop/products/fixture.jpg'
    assert public_quote(row)['items'][0]['image_url'] is None


def test_shipping_multi_variant_policy_is_explicit_unknown_not_confirmed_by_default():
    assert ShippingRateInput(offer_id=str(uuid4()), country='FR', mode='tracked', max_quantity=20).multi_variant_policy == 'unknown'


def test_service_refuses_wrong_cart_owner_before_database(quote_fixture, request_data):
    db = AsyncMock()
    service = CartQuoteService(db, ('FR',))
    with pytest.raises(CartQuoteError, match='cart_not_accessible'):
        asyncio.run(service.create(CartQuoteInput.model_validate(request_data), {'id': CART, 'user_id': PROFILE}, None, GUEST))
    db.select.assert_not_awaited()
    db.rpc.assert_not_awaited()
