"""Private operations contracts; all evidence here is explicitly synthetic."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from app.supabase_rest import SupabaseError
from tests.test_commerce_pricing import AGENT, OFFER, PRODUCT, PROFILE, VARIANT, case  # noqa: F401
from tests.test_commerce_finance import financial  # noqa: F401

HEADERS = {'Authorization': 'Bearer operations-test-admin'}
ID = '10000000-0000-4000-8000-000000000099'
ROUTES = [
    ('POST', '/images/permissions'), ('GET', '/images/permissions?product_id=' + PRODUCT),
    ('POST', '/hypersku/mappings'), ('GET', '/hypersku/mappings?offer_id=' + OFFER),
    ('POST', '/hypersku/tasks/' + ID + '/prepare'),
    ('GET', '/hypersku/preparations/' + ID), ('POST', '/finance/quotes/' + ID + '/analyze'),
]


@pytest.fixture
def operations(monkeypatch):
    async def user(token):
        return {'id': PROFILE} if token == 'operations-test-admin' else None

    async def select(table, *, params=None):
        if table == 'profiles':
            return [{'id': PROFILE, 'role': 'admin'}]
        return []

    monkeypatch.setattr(server.db, 'get_user', user)
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=select))
    monkeypatch.setattr(server.db, 'rpc', AsyncMock())
    monkeypatch.setattr(server.db, 'page', AsyncMock(return_value={'items': [], 'total': 0}))
    monkeypatch.setattr(server.db, 'update', AsyncMock())
    monkeypatch.setattr(server.db, 'insert', AsyncMock())
    return TestClient(server.app)


@pytest.mark.parametrize('method,path', ROUTES)
def test_auth_required_before_operational_storage(operations, method, path):
    response = operations.request(method, '/api/admin/commerce' + path, json={})
    assert response.status_code == 401
    server.db.rpc.assert_not_awaited()
    server.db.page.assert_not_awaited()
    server.db.select.assert_not_awaited()


@pytest.mark.parametrize('method,path', ROUTES)
def test_customer_cannot_access_operations(operations, monkeypatch, method, path):
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'id': PROFILE, 'role': 'customer'}]))
    response = operations.request(method, '/api/admin/commerce' + path, json={}, headers=HEADERS)
    assert response.status_code == 403
    server.db.rpc.assert_not_awaited()
    server.db.page.assert_not_awaited()
    assert all(call.args[0] == 'profiles' for call in server.db.select.call_args_list)


@pytest.mark.parametrize('changes', [
    {'state': 'verified'}, {'commercial_use': 'true'}, {'countries': ['fr']},
    {'countries': ['FR', 'FR']}, {'image_url': 'http://example.test/a.jpg'},
    {'image_url': 'https://user:secret@example.test/a.jpg'},
    {'image_url': 'https://example.test/a\n.jpg'}, {'verified_by': PROFILE},
])
def test_invalid_image_permission_cannot_claim_evidence(operations, changes):
    data = {'product_id': PRODUCT, 'image_url': 'https://example.test/a.jpg', **changes}
    assert operations.post('/api/admin/commerce/images/permissions', json={'data': data}, headers=HEADERS).status_code == 422
    server.db.rpc.assert_not_awaited()


def test_permission_exact_identity_and_optimistic_version_forwarded(operations):
    data = {'product_id': PRODUCT, 'image_url': 'https://example.test/a.jpg'}
    server.db.rpc.return_value = {'id': ID, 'state': 'pending'}
    response = operations.post('/api/admin/commerce/images/permissions', json={
        'data': data, 'expected_updated_at': '2026-10-24T01:00:00Z'}, headers=HEADERS)
    assert response.status_code == 200
    name, payload = server.db.rpc.call_args.args
    assert name == 'commerce_save_image_permission'
    assert payload['p_actor'] == PROFILE
    assert payload['p_data']['image_url'] == data['image_url']
    assert payload['p_expected'] == '2026-10-24T01:00:00+00:00'
    assert response.headers['cache-control'] == 'no-store'
    server.db.insert.assert_not_awaited()
    server.db.update.assert_not_awaited()


@pytest.mark.parametrize('status', [400, 403, 404, 409, 422])
def test_rpc_conflicts_do_not_leak_private_detail(operations, status):
    server.db.rpc.side_effect = SupabaseError(status, 'PRIVATE supplier cost or stale version')
    response = operations.post('/api/admin/commerce/images/permissions', headers=HEADERS,
        json={'data': {'product_id': PRODUCT, 'image_url': 'https://example.test/a.jpg'}})
    assert response.status_code == 409
    assert 'PRIVATE' not in response.text


@pytest.mark.parametrize('data', [
    {'offer_id': OFFER, 'shipping_rate_id': ID, 'state': 'verified'},
    {'offer_id': OFFER, 'shipping_rate_id': ID, 'is_test': 'true'},
    {'offer_id': OFFER, 'shipping_rate_id': ID, 'external_send_allowed': True},
])
def test_mapping_cannot_skip_evidence_or_authorize_spending(operations, data):
    assert operations.post('/api/admin/commerce/hypersku/mappings', json={'data': data}, headers=HEADERS).status_code == 422
    server.db.rpc.assert_not_awaited()


def test_preparation_forbidden_outside_test_mode(operations, monkeypatch):
    monkeypatch.setattr(server, 'settings', SimpleNamespace(stripe_test_mode=False))
    response = operations.post('/api/admin/commerce/hypersku/tasks/' + ID + '/prepare',
        json={'mapping_id': ID}, headers=HEADERS)
    assert response.status_code == 409
    server.db.rpc.assert_not_awaited()


def test_preparation_admin_projection_does_not_expose_packet(operations, monkeypatch):
    monkeypatch.setattr(server, 'settings', SimpleNamespace(stripe_test_mode=True))
    row = {'id': ID, 'order_id': ID, 'task_id': ID, 'responsible_agent_id': AGENT,
           'state': 'awaiting_human_review', 'is_test': True, 'external_send_allowed': False,
           'expenses_authorized': False, 'packet_hash': 'a' * 64, 'packet': {'private': 'snapshot'}}
    server.db.rpc.return_value = row
    response = operations.post('/api/admin/commerce/hypersku/tasks/' + ID + '/prepare',
        json={'mapping_id': ID}, headers=HEADERS)
    assert response.status_code == 200
    assert 'packet' not in response.json()
    assert response.json()['external_send_allowed'] is False
    assert server.db.rpc.call_args.args == ('commerce_prepare_hypersku_task', {
        'p_actor': PROFILE, 'p_task_id': ID, 'p_mapping_id': ID})


def test_finance_rejects_client_groups_before_reading_quote(operations):
    response = operations.post('/api/admin/commerce/finance/quotes/' + ID + '/analyze',
        json={'inputs': {'groups': []}}, headers=HEADERS)
    assert response.status_code == 422
    assert all(call.args[0] == 'profiles' for call in server.db.select.call_args_list)


def test_finance_uses_frozen_quote_without_price_writes(operations, monkeypatch, financial, case):
    from app.commerce_pricing import quote_offer
    evaluation = quote_offer(**case)
    quote = {'state': 'consumed', 'payload': {'groups': [{'variant_id': VARIANT, 'evaluation': evaluation}]}}

    async def select(table, *, params=None):
        if table == 'profiles': return [{'id': PROFILE, 'role': 'admin'}]
        assert table == 'commerce_quotes' and params['id'] == 'eq.' + ID
        return [deepcopy(quote)]

    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=select))
    options = {k: v for k, v in financial.items() if k != 'groups'}
    response = operations.post('/api/admin/commerce/finance/quotes/' + ID + '/analyze',
        json={'inputs': options}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()['commercial_approval'] is False
    assert response.json()['analysis']['status'] == 'HYPOTHETICAL'
    assert response.json()['analysis']['sources'][0]['provenance'] == 'ASSUMPTION'
    server.db.rpc.assert_not_awaited()
    server.db.update.assert_not_awaited()
    server.db.insert.assert_not_awaited()


@pytest.mark.parametrize('path', ['/hypersku/preparations/' + ID, '/finance/quotes/' + ID + '/analyze'])
def test_missing_private_resource_does_not_fallback(operations, path):
    response = operations.request('GET' if '/preparations/' in path else 'POST',
        '/api/admin/commerce' + path, json={}, headers=HEADERS)
    assert response.status_code == 404
