"""All transports are injected in-memory; never SMTP/Brevo or hosted database."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.services.email_service import EmailService
from app.services.email_templates import EmailContent
from app.services.order_notification_outbox import OrderNotificationOutbox
from tests.test_email_system import settings

ORDER = '10000000-0000-4000-8000-000000000044'


class Db:
    def __init__(self):
        self.row = {'id': 'fixture-log', 'order_id': ORDER, 'recipient': 'Frozen@Example.test',
                    'email_type': 'order_processing', 'status': 'queued', 'delivery_state': 'pending',
                    'event_snapshot': {'version': 1, 'order': {'id': ORDER, 'order_number': 'FROZEN',
                        'currency': 'EUR', 'total_cents': 1000}, 'items': []}}
        self.calls = []
        self.fail_claim_response = self.fail_finish = False
        self.fail_finish_response = False
        self.claim_ready = None
        self.token = None

    async def select(self, table, *, params):
        assert table == 'email_logs'  # No mutable order/customer/catalog read.
        return [deepcopy(self.row)]

    async def rpc(self, name, data):
        self.calls.append((name, data))
        if name == 'admin_claim_order_notification':
            if self.row['delivery_state'] not in {'pending', 'blocked'}:
                return {'claimed': False, 'state': self.row['delivery_state']}
            self.claim_ready = data['p_ready']
            if not data['p_ready']:
                self.row.update(delivery_state='blocked', status='failed')
                return {'claimed': False, 'state': 'blocked'}
            self.row['delivery_state'], self.token = 'claimed', data['p_token']
            if self.fail_claim_response:
                raise TimeoutError('commit happened, response lost')
            return {'claimed': True, 'state': 'claimed'}
        assert name == 'complete_order_notification'
        if self.fail_finish:
            raise TimeoutError('database unavailable')
        assert data['p_token'] == self.token
        self.row['delivery_state'] = data['p_outcome']
        if self.fail_finish_response:
            raise TimeoutError('completion committed, response lost')
        return {'completed': True, 'state': data['p_outcome']}


def service(db, transport, **cfg):
    return OrderNotificationOutbox(EmailService(settings(**cfg), db, transport=transport))


def test_frozen_recipient_content_and_repeat_delivery():
    db, deliveries = Db(), []
    def transport(to, content):
        deliveries.append((to, content))
        return 'fixture-provider-id'
    outbox = service(db, transport)
    first = asyncio.run(outbox.deliver('fixture-log', 'admin'))
    assert first['sent'] and first['status'] == 'sent'
    assert deliveries[0][0] == 'frozen@example.test'
    assert 'FROZEN' in deliveries[0][1].text and '10,00 EUR' in deliveries[0][1].text
    assert not asyncio.run(outbox.deliver('fixture-log', 'admin'))['sent']
    assert len(deliveries) == 1 and len(db.calls) == 2


def test_two_concurrent_dispatchers_only_one_transport():
    async def run():
        db, deliveries = Db(), []
        outbox = service(db, lambda *args: deliveries.append(args))
        results = await asyncio.gather(*(outbox.deliver('fixture-log', 'admin') for _ in range(8)))
        assert sum(r['sent'] for r in results) == 1 and len(deliveries) == 1
    asyncio.run(run())


@pytest.mark.parametrize('damage', ['disabled', 'email', 'snapshot', 'version', 'kind', 'order', 'items'])
def test_invalid_configuration_or_event_never_starts_transport(damage):
    db = Db()
    if damage == 'email': db.row['recipient'] = 'invalid'
    if damage == 'snapshot': db.row['event_snapshot'] = {}
    if damage == 'version': db.row['event_snapshot']['version'] = 99
    if damage == 'kind': db.row['email_type'] = 'invented'
    if damage == 'order': db.row['order_id'] = 'other-order'
    if damage == 'items': db.row['event_snapshot']['items'] = [None]
    outbox = service(db, lambda *_: pytest.fail('Transport forbidden'), email_enabled=damage != 'disabled')
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'blocked'
    assert db.claim_ready is False


def test_missing_configuration_can_be_recovered_before_transport():
    db, deliveries = Db(), []
    assert asyncio.run(service(db, lambda *_: None, email_enabled=False).deliver('fixture-log', 'admin'))['status'] == 'blocked'
    result = asyncio.run(service(db, lambda *args: deliveries.append(args)).deliver('fixture-log', 'admin'))
    assert result['sent'] and len(deliveries) == 1


@pytest.mark.parametrize('state', ['sent', 'claimed', 'unknown'])
def test_terminal_or_abandoned_claim_never_retries(state):
    db = Db()
    db.row['delivery_state'] = state
    result = asyncio.run(service(db, lambda *_: pytest.fail('Transport forbidden')).deliver('fixture-log', 'admin'))
    assert result['status'] == state and not result['sent'] and not db.calls


def test_lost_claim_response_never_starts_or_retries_transport():
    db = Db()
    db.fail_claim_response = True
    outbox = service(db, lambda *_: pytest.fail('Transport forbidden'))
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert db.row['delivery_state'] == 'claimed'
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'claimed'


def test_provider_acceptance_then_timeout_is_unknown_not_retryable():
    db, deliveries = Db(), []
    def transport(*args):
        deliveries.append(args)
        raise TimeoutError('May have been accepted; sensitive provider response')
    outbox = service(db, transport)
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert len(deliveries) == 1 and db.row['delivery_state'] == 'unknown'


def test_successful_transport_database_completion_failure_does_not_resend():
    db, deliveries = Db(), []
    db.fail_finish = True
    outbox = service(db, lambda *args: deliveries.append(args))
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'claimed'
    assert len(deliveries) == 1


def test_lost_completion_response_after_commit_never_resends():
    db, deliveries = Db(), []
    db.fail_finish_response = True
    outbox = service(db, lambda *args: deliveries.append(args))
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert db.row['delivery_state'] == 'sent'
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'sent'
    assert len(deliveries) == 1


@pytest.mark.parametrize('status', ['queued', 'failed', 'sent'])
def test_legacy_collision_never_converts_or_sends(status):
    db = Db()
    db.row.update(event_snapshot=None, status=status)
    result = asyncio.run(service(db, lambda *_: pytest.fail('Transport forbidden')).deliver('fixture-log', 'admin'))
    assert result['status'] == ('sent' if status == 'sent' else 'legacy_review')
    assert not db.calls and not result['sent']


def test_legacy_retry_filters_out_managed_outbox():
    db = Db()
    db.update = AsyncMock(return_value=[])
    email = EmailService(settings(), db, transport=lambda *_: pytest.fail('Transport forbidden'))
    assert asyncio.run(email.retry('fixture-log', 'client@example.test', EmailContent('Subject', 'html', 'text')))['status'] == 'not_retryable'
    assert db.update.await_args.kwargs['params']['event_snapshot'] == 'is.null'
