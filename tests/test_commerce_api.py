from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from tests.test_commerce_pricing import AGENT, OFFER, PRODUCT, PROFILE, RULE, VARIANT, case  # noqa: F401


@pytest.fixture
def client(monkeypatch):
    async def user(token):
        return {'id': PROFILE} if token in {'commerce-admin', 'commerce-customer'} else None

    async def select(table, *, params=None):
        if table == 'profiles':
            return [{'id': PROFILE, 'role': 'admin'}]
        return []

    monkeypatch.setattr(server.db, 'get_user', user)
    monkeypatch.setattr(server.db, 'select', select)
    return TestClient(server.app)


HEADERS = {'Authorization': 'Bearer commerce-admin'}


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/admin/commerce/variant'), ('POST', '/api/admin/commerce/variant'),
    ('PUT', '/api/admin/commerce/offer/' + OFFER), ('POST', '/api/admin/commerce/quote'),
])
def test_no_auth_never_reaches_commerce_storage(client, method, path, monkeypatch):
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    assert client.request(method, path, json={}).status_code == 401
    rpc.assert_not_awaited()


def test_customer_cannot_read_supplier_costs_or_update_records(client, monkeypatch):
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'id': PROFILE, 'role': 'customer'}]))
    for method, path in [('GET', '/api/admin/commerce/offer'), ('POST', '/api/admin/commerce/quote'),
                         ('POST', '/api/admin/commerce/agent'), ('PUT', '/api/admin/commerce/variant/' + VARIANT)]:
        assert client.request(method, path, json={}, headers=HEADERS).status_code == 403


def test_save_variant_uses_atomic_admin_rpc_not_product_write(client, monkeypatch):
    rpc = AsyncMock(return_value={'id': VARIANT, 'status': 'draft'})
    monkeypatch.setattr(server.db, 'rpc', rpc)
    product_update = AsyncMock()
    monkeypatch.setattr(server.db, 'update', product_update)
    payload = {'data': {'product_id': PRODUCT, 'sku': 'SYNTHETIC-TEST', 'name': 'Fixture variant', 'price_cents': 12000}}
    response = client.post('/api/admin/commerce/variant', json=payload, headers=HEADERS)
    assert response.status_code == 200
    data = rpc.call_args.args[1]
    assert rpc.call_args.args[0] == 'admin_save_commerce_record'
    assert data['p_actor'] == PROFILE and data['p_kind'] == 'variant'
    assert data['p_id'] is None and data['p_expected'] is None
    assert data['p_data']['status'] == 'draft' and data['p_data']['is_verified'] is False
    product_update.assert_not_awaited()
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('data', [
    {'product_id': PRODUCT, 'sku': 'F', 'name': 'Fixture', 'price_cents': 1, 'status': 'active'},
    {'product_id': PRODUCT, 'sku': 'F', 'name': 'Fixture', 'price_cents': 1, 'images': ['https://example.test/image']},
    {'product_id': PRODUCT, 'sku': 'F', 'name': 'Fixture', 'price_cents': 1.5},
])
def test_unverified_activation_and_image_changes_not_accepted(client, monkeypatch, data):
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    response = client.post('/api/admin/commerce/variant', headers=HEADERS, json={'data': data})
    assert response.status_code == 422
    assert response.json() == {'detail': 'Invalid commerce record'}
    rpc.assert_not_awaited()


def test_optimistic_version_required_and_passed_to_database(client, monkeypatch):
    rpc = AsyncMock(return_value={'id': AGENT})
    monkeypatch.setattr(server.db, 'rpc', rpc)
    payload = {'data': {'profile_id': PROFILE, 'name': 'Fixture operator', 'role': 'orders'}}
    response = client.put('/api/admin/commerce/agent/' + AGENT, headers=HEADERS, json=payload)
    assert response.status_code == 422
    rpc.assert_not_awaited()
    payload['expected_updated_at'] = '2026-10-23T12:00:00Z'
    assert client.put('/api/admin/commerce/agent/' + AGENT, headers=HEADERS, json=payload).status_code == 200
    assert rpc.call_args.args[1]['p_expected'] == '2026-10-23T12:00:00+00:00'
    rpc.reset_mock()
    assert client.post('/api/admin/commerce/agent', headers=HEADERS, json=payload).status_code == 422
    rpc.assert_not_awaited()


def test_list_paginated_with_safe_uuid_parent_and_compatibility_ids(client, monkeypatch):
    async def page_data(table, **kwargs):
        if table == 'variant_compatibilities':
            return {'items': [{'variant_id': VARIANT, 'compatibility_id': RULE}], 'total': 1}
        return {'items': [{'id': VARIANT, 'product_id': PRODUCT}], 'page': 2, 'limit': 10, 'total': 11}
    page = AsyncMock(side_effect=page_data)
    monkeypatch.setattr(server.db, 'page', page)
    original_select = server.db.select

    async def select(table, *, params=None):
        if table == 'variant_compatibilities':
            return [{'variant_id': VARIANT, 'compatibility_id': RULE}]
        return await original_select(table, params=params)

    monkeypatch.setattr(server.db, 'select', select)
    response = client.get('/api/admin/commerce/variant?page=2&limit=10&parent_id=' + PRODUCT, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['items'][0]['compatibility_ids'] == [RULE]
    assert page.call_args_list[0].args == ('product_variants',)
    assert page.call_args_list[0].kwargs['params']['product_id'] == 'eq.' + PRODUCT
    assert client.get('/api/admin/commerce/variant?parent_id=not-a-uuid', headers=HEADERS).status_code == 422


def wire_quote(monkeypatch, case, *, no_offers=False):
    fixture = deepcopy(case)
    fixture['offer_row']['valid_until'] = '2099-01-01T00:00:00Z'
    fixture['rate_rows'][0]['valid_until'] = '2099-01-01T00:00:00Z'
    async def select(table, *, params=None):
        data = {
            'profiles': [{'id': PROFILE, 'role': 'admin'}],
            'product_variants': [fixture['variant_row']],
            'supplier_offers': [] if no_offers else [fixture['offer_row']],
            'variant_compatibilities': [{'variant_id': VARIANT, 'compatibility_id': RULE}],
            'shipping_rates': fixture['rate_rows'], 'commerce_agents': [fixture['agent_row']],
        }
        return data.get(table, [])
    monkeypatch.setattr(server.db, 'select', select)
    async def page(table, *, params, page, limit):
        rows = await select(table, params=params)
        start = (page - 1) * limit
        return {'items': rows[start:start + limit], 'total': len(rows)}
    monkeypatch.setattr(server.db, 'page', page)
    monkeypatch.setattr(server.catalog, 'product_by', AsyncMock(return_value=fixture['product']))
    return fixture


def test_admin_quote_reads_real_associations_and_never_creates_order(client, monkeypatch, case):
    wire_quote(monkeypatch, case)
    rpc, insert, update = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    monkeypatch.setattr(server.db, 'insert', insert)
    monkeypatch.setattr(server.db, 'update', update)
    response = client.post('/api/admin/commerce/quote', json=case['request'].model_dump(mode='json'), headers=HEADERS)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['status'] == 'ready' and data['best_cost_offer_id'] == OFFER
    assert data['offers'][0]['landed_cost_cents'] == 11100
    assert data['offers'][0]['variant_id'] == VARIANT
    assert data['offers'][0]['supplier_sku'] == 'FIXTURE-SUP-B'
    assert 'not_checkout' in data['scope']
    rpc.assert_not_awaited(); insert.assert_not_awaited(); update.assert_not_awaited()


def test_no_supplier_no_quote_and_no_global_shipping_fallback(client, monkeypatch, case):
    wire_quote(monkeypatch, case, no_offers=True)
    response = client.post('/api/admin/commerce/quote', json=case['request'].model_dump(mode='json'), headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['status'] == 'blocked'
    assert response.json()['reasons'] == ['supplier_offer_missing']


def test_unsupported_destination_and_malicious_offer_url_rejected(client, monkeypatch, case):
    request = {**case['request'].model_dump(mode='json'), 'country': 'ZZ'}
    assert client.post('/api/admin/commerce/quote', json=request, headers=HEADERS).json()['reasons'] == ['destination_not_supported']
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    offer = {key: value for key, value in case['offer_row'].items() if key != 'id'}
    offer['url'] = 'https://user:password@private.example.test/'
    response = client.post('/api/admin/commerce/offer', json={'data': offer}, headers=HEADERS)
    assert response.status_code == 422
    assert 'password' not in response.text
    rpc.assert_not_awaited()


def test_server_row_cap_cannot_hide_a_shipping_restriction(client, monkeypatch, case):
    wire_quote(monkeypatch, case)
    original = server.db.page
    async def page(table, **kwargs):
        if table == 'shipping_rates':
            # A capped response reports more matching rows than we may evaluate.
            return {'items': case['rate_rows'], 'total': 1001}
        return await original(table, **kwargs)
    monkeypatch.setattr(server.db, 'page', page)
    response = client.post('/api/admin/commerce/quote', json=case['request'].model_dump(mode='json'), headers=HEADERS)
    assert response.status_code == 409
    assert 'exceed' in response.json()['detail']


def test_truncated_rows_even_under_bound_cannot_produce_quote(client, monkeypatch, case):
    wire_quote(monkeypatch, case)
    original = server.db.page
    async def page(table, **kwargs):
        if table == 'shipping_rates':
            return {'items': case['rate_rows'], 'total': 2}
        return await original(table, **kwargs)
    monkeypatch.setattr(server.db, 'page', page)
    response = client.post('/api/admin/commerce/quote', json=case['request'].model_dump(mode='json'), headers=HEADERS)
    assert response.status_code == 409
    assert 'Incomplete' in response.json()['detail']


def test_variant_list_does_not_hide_truncated_compatibilities(client, monkeypatch):
    async def page(table, **kwargs):
        if table == 'product_variants':
            return {'items': [{'id': VARIANT, 'product_id': PRODUCT}], 'total': 1}
        return {'items': [{'variant_id': VARIANT, 'compatibility_id': RULE}], 'total': 1001}
    monkeypatch.setattr(server.db, 'page', page)
    assert client.get('/api/admin/commerce/variant', headers=HEADERS).status_code == 409
