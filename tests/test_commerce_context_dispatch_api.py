"""Manual operation boundary and customer projections, no supplier/carrier calls."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.commerce_context_dispatch_api import (ContextDispatchInput, create_context_dispatch_router,
                                              customer_context_parcels)

ACTOR = str(uuid4())
TASK = str(uuid4())
ORDER = str(uuid4())


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.fixture
def client():
    async def admin(authorization: str | None = Header(default=None)):
        if authorization != 'Bearer synthetic-admin':
            raise HTTPException(403 if authorization else 401)
        return {'id': ACTOR}
    db = SimpleNamespace(select=AsyncMock(return_value=[]), rpc=AsyncMock(), insert=AsyncMock())
    notify = AsyncMock()
    app = FastAPI()
    app.include_router(create_context_dispatch_router(db, admin, notify))
    return TestClient(app), db, notify


def payload(**changes):
    return {'expected_updated_at': '2026-10-29T10:00:00Z', 'next': 'supplier_confirmed',
            'supplier_order_ref': 'SYNTHETIC-ONLY', 'evidence_ref': 'SYNTHETIC supplier and fitment review', **changes}


@pytest.mark.parametrize('suffix,method', [('/orders/' + ORDER + '/tasks', 'GET'),
    ('/tasks/' + TASK + '/supplier-draft', 'GET'), ('/tasks/' + TASK + '/advance', 'POST')])
@pytest.mark.parametrize('headers,status', [({}, 401), ({'Authorization': 'Bearer customer'}, 403)])
def test_no_admin_never_reads_or_mutates_fulfillment(client, suffix, method, headers, status):
    http, db, notify = client
    assert http.request(method, '/api/admin/commerce/context' + suffix, headers=headers,
                        json=payload() if method == 'POST' else None).status_code == status
    db.select.assert_not_awaited()
    db.rpc.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.parametrize('url', ['http://carrier.example.com/x', 'https://user@carrier.example.com/x',
    'https://localhost/x', 'https://127.0.0.1/x', 'https://10.0.0.1/x', 'https://127.1/x',
    'https://carrier.example.com:444/x', 'https://carrier.example.com/x\n', 'https://carrier.example.com\\x',
    'https://127.0.0.1./x', 'https://0x7f.0x0.0x0.0x1/x', 'https://carrier..example.com/x',
    'https://carrier.example.com/x\x7f'])
def test_invalid_tracking_url_cannot_be_recorded(url):
    with pytest.raises(ValidationError):
        ContextDispatchInput.model_validate(payload(next='shipped', tracking_url=url))


def test_explicit_expected_version_and_no_extra_financial_or_external_flags(client):
    http, db, _ = client
    path = '/api/admin/commerce/context/tasks/' + TASK + '/advance'
    for changes in ({'external_send_allowed': True}, {'price_cents': 1}, {'is_test': False}, {'agent_id': ACTOR}):
        assert http.post(path, json=payload(**changes), headers={'Authorization': 'Bearer synthetic-admin'}).status_code == 422
    missing = payload(); missing.pop('expected_updated_at')
    assert http.post(path, json=missing, headers={'Authorization': 'Bearer synthetic-admin'}).status_code == 422
    db.rpc.assert_not_awaited()


def test_transition_uses_actor_atomic_rpc_and_only_committed_notification(client):
    http, db, notify = client
    db.rpc.return_value = {'task_id': TASK, 'order_id': ORDER, 'status_changed': True,
        'notification_kind': 'order_shipped', 'notification_log_id': str(uuid4())}
    response = http.post('/api/admin/commerce/context/tasks/' + TASK + '/advance',
        json=payload(next='shipped', carrier='Synthetic carrier', tracking_number='SYNTHETIC-001',
                     tracking_url='https://carrier.example.com/track/SYNTHETIC-001'),
        headers={'Authorization': 'Bearer synthetic-admin'})
    assert response.status_code == 200
    name, args = db.rpc.call_args.args
    assert name == 'commerce_advance_context_task' and args['p_actor'] == ACTOR and args['p_task_id'] == TASK
    assert args['p_expected_updated_at'] == '2026-10-29T10:00:00+00:00'
    notify.assert_awaited_once_with(db.rpc.return_value['notification_log_id'], ACTOR)
    notify.reset_mock()
    db.rpc.return_value['status_changed'] = False
    assert http.post('/api/admin/commerce/context/tasks/' + TASK + '/advance', json=payload(),
                     headers={'Authorization': 'Bearer synthetic-admin'}).status_code == 200
    notify.assert_not_awaited()


@pytest.mark.anyio
async def test_customer_parcels_are_allowlisted_and_unshipped_details_hidden():
    row = {'id': TASK, 'state': 'supplier_confirmed', 'tracking_number': 'PRIVATE-PENDING',
        'carrier': 'PRIVATE', 'tracking_url': 'PRIVATE', 'shipped_at': None, 'delivered_at': None,
        'supplier_id': ACTOR, 'snapshot': {'private_cost': 123}, 'evidence_ref': 'PRIVATE-EVIDENCE'}
    db = SimpleNamespace(select=AsyncMock(return_value=[deepcopy(row)]))
    order = {'id': ORDER, 'stripe_profile_ref': 'synthetic'}
    result = await customer_context_parcels(db, order)
    assert result == [{'reference': TASK, 'state': 'supplier_confirmed', 'tracking_number': None,
                      'carrier': None, 'tracking_url': None, 'shipped_at': None, 'delivered_at': None}]
    assert 'PRIVATE' not in str(result)
    assert await customer_context_parcels(db, {'id': ORDER}) == []
    db.select.assert_awaited_once()


def test_supplier_draft_is_audited_and_explicitly_not_transmitted(client):
    http, db, notify = client
    task = {'id': TASK, 'order_id': ORDER, 'supplier_id': str(uuid4()), 'agent_id': str(uuid4()),
        'supplier_sku': 'SYNTHETIC-SKU', 'quantity': 1, 'snapshot': {'offer': {'unit_cost_cents': 123}},
        'review_reasons': ['fulfillment_approval_required']}
    order = {'id': ORDER, 'is_test': False, 'stripe_profile_ref': 'synthetic',
             'shipping_address': {'line1': 'Synthetic only'}}
    db.select.side_effect = [[task], [order]]
    response = http.get('/api/admin/commerce/context/tasks/' + TASK + '/supplier-draft',
                         headers={'Authorization': 'Bearer synthetic-admin'})
    assert response.status_code == 200
    assert response.json()['external_send_allowed'] is False
    assert response.json()['status'] == 'draft_not_transmitted'
    db.insert.assert_awaited_once()
    assert db.insert.call_args.args[1]['admin_user_id'] == ACTOR
    db.rpc.assert_not_awaited()
    notify.assert_not_awaited()
