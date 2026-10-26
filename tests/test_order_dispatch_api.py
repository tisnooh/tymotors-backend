"""The existing admin endpoint commits one complete shipment or nothing."""
from unittest.mock import AsyncMock

import pytest
from app.supabase_rest import SupabaseError
import server
from tests.test_admin_api import ADMIN, CUSTOMER, client  # noqa: F401

HEADERS = {'Authorization': 'Bearer admin-test-token'}
STAMP = '2026-10-26T08:00:00Z'


def data(**changes):
    return {'expected_updated_at': STAMP, 'fulfillment_status': 'shipped',
            'tracking_number': 'FIXTURE-123', 'carrier': 'Fixture carrier',
            'tracking_url': 'https://carrier.example.test/track/FIXTURE-123', **changes}


def test_dispatch_one_atomic_rpc_no_separate_write(client, monkeypatch):
    result = {'updated': True, 'status_changed': True, 'notification_kind': 'order_shipped', 'notification_log_id': CUSTOMER}
    rpc, update, email = AsyncMock(return_value=result), AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    monkeypatch.setattr(server.db, 'update', update)
    monkeypatch.setattr(server, '_deliver_order_notification', email)
    response = client.put('/api/admin/orders/' + CUSTOMER, json=data(), headers=HEADERS)
    assert response.status_code == 200 and response.json() == result
    rpc.assert_awaited_once_with('admin_update_order_fulfillment', {
        'p_actor': ADMIN, 'p_id': CUSTOMER, 'p_status': 'shipped', 'p_tracking': 'FIXTURE-123',
        'p_carrier': 'Fixture carrier', 'p_tracking_url': data()['tracking_url'],
        'p_expected': '2026-10-26T08:00:00+00:00'})
    update.assert_not_awaited()
    email.assert_awaited_once_with(CUSTOMER, ADMIN)


@pytest.mark.parametrize('result', [
    {'updated': False, 'status_changed': False, 'notification_kind': None},
    {'updated': True, 'status_changed': False, 'notification_kind': 'order_shipped'},
    {'updated': True, 'status_changed': True, 'notification_kind': 'invented_provider_event'},
    {'updated': True, 'status_changed': True, 'notification_kind': 'order_shipped'},
])
def test_replay_or_tracking_only_change_does_not_send_notification(client, monkeypatch, result):
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(return_value=result))
    email = AsyncMock()
    monkeypatch.setattr(server, '_deliver_order_notification', email)
    assert client.put('/api/admin/orders/' + CUSTOMER, json=data(), headers=HEADERS).status_code == 200
    email.assert_not_awaited()


@pytest.mark.parametrize('reason', [
    'Order changed. Reload before saving', 'Test orders require simulation-only fulfillment',
    'Payment required', 'Compatibility review required before dispatch',
    'Shipment tracking is locked after dispatch', 'Invalid shipment details',
    'Simulated tracking cannot represent a real shipment',
    'Quoted orders require verified multi-parcel fulfillment',
])
def test_conflict_never_writes_or_emails(client, monkeypatch, reason):
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(side_effect=SupabaseError(400, reason)))
    update, email = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, 'update', update)
    monkeypatch.setattr(server, '_deliver_order_notification', email)
    response = client.put('/api/admin/orders/' + CUSTOMER, json=data(), headers=HEADERS)
    assert response.status_code == 409
    update.assert_not_awaited()
    email.assert_not_awaited()


@pytest.mark.parametrize('changes', [
    {'expected_updated_at': None}, {'expected_updated_at': 'not-a-time'},
    {'expected_updated_at': '2026-10-26T08:00:00'},
    {'tracking_number': 'TRACK\n123'}, {'carrier': 'Carrier\x7f'},
    {'tracking_url': 'https://user:secret@carrier.example.test/'},
    {'tracking_url': 'http://carrier.example.test/'}, {'tracking_url': 'https://carrier.example.test/a b'},
    {'external_send_allowed': True}, {'is_test': False},
])
def test_invalid_dispatch_input_cannot_reach_storage(client, monkeypatch, changes):
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    assert client.put('/api/admin/orders/' + CUSTOMER, json=data(**changes), headers=HEADERS).status_code == 422
    rpc.assert_not_awaited()


def retry_fixture(monkeypatch, **changes):
    row = {'id': CUSTOMER, 'order_id': CUSTOMER, 'email_type': 'order_shipped', 'status': 'queued',
           'delivery_state': 'pending', 'event_snapshot': {'version': 1}, **changes}
    original = server.db.select
    async def select(table, *, params):
        if table == 'email_logs': return [row]
        return await original(table, params=params)
    monkeypatch.setattr(server.db, 'select', select)
    delivery = AsyncMock(return_value={'sent': False, 'status': 'blocked'})
    monkeypatch.setattr(server, '_deliver_order_notification', delivery)
    return delivery


@pytest.mark.parametrize('state,status', [('pending', 'queued'), ('blocked', 'failed')])
def test_managed_retry_uses_frozen_outbox_not_mutable_order(client, monkeypatch, state, status):
    delivery = retry_fixture(monkeypatch, delivery_state=state, status=status)
    old = AsyncMock()
    monkeypatch.setattr(server, '_send_order_email', old)
    response = client.post('/api/admin/email-logs/' + CUSTOMER + '/retry', headers=HEADERS)
    assert response.status_code == 202 and response.json() == {'accepted': False, 'delivery': 'blocked'}
    delivery.assert_awaited_once_with(CUSTOMER, ADMIN)
    old.assert_not_awaited()


@pytest.mark.parametrize('state,status,snapshot', [
    ('unknown', 'failed', {}), ('claimed', 'queued', {}), ('sent', 'sent', {}),
    (None, 'failed', None), (None, 'queued', None),
])
def test_managed_or_legacy_ambiguous_delivery_cannot_be_retried(client, monkeypatch, state, status, snapshot):
    delivery = retry_fixture(monkeypatch, delivery_state=state, status=status, event_snapshot=snapshot)
    assert client.post('/api/admin/email-logs/' + CUSTOMER + '/retry', headers=HEADERS).status_code == 409
    delivery.assert_not_awaited()
