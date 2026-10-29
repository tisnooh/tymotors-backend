"""Injected local transports and in-process HTTP only; never SMTP/Brevo/network.

The stateful DB mock enforces the conditional PATCH atomically in one event-loop
step. It is not proof of native multi-connection PostgreSQL concurrency.
"""
import asyncio
from copy import deepcopy

import pytest
from unittest.mock import AsyncMock

import server
from app.services.email_service import EmailService
from app.services.email_templates import EmailContent
from tests.test_admin_api import ADMIN, CUSTOMER, client  # noqa: F401
from tests.test_email_system import settings


LOG = 'log-1'
RECIPIENT = 'synthetic@example.test'
CONTENT = EmailContent('Synthetic subject', '<p>Synthetic</p>', 'Synthetic')
HEADERS = {'Authorization': 'Bearer admin-test-token'}


class DB:
    def __init__(self):
        self.row = {'id': LOG, 'recipient': RECIPIENT, 'status': 'queued',
                    'error_message': None, 'event_snapshot': None}
        self.updates = []
        self.fail_sent = self.lose_sent_response = self.empty_sent_response = False
        self.lose_claim_response = self.fail_unknown_write = False

    async def insert(self, table, payload):
        assert table == 'email_logs'
        self.row.update(deepcopy(payload))
        return [deepcopy(self.row)]

    async def update(self, table, payload, *, params):
        assert table == 'email_logs'
        await asyncio.sleep(0)  # Let simultaneous callers race at the real filter.
        self.updates.append((deepcopy(payload), deepcopy(params)))
        for key, expression in params.items():
            actual = self.row.get(key)
            if expression == 'is.null':
                if actual is not None: return []
            else:
                assert expression.startswith('eq.')
                if actual != expression[3:]: return []
        if payload['status'] == 'sent' and self.fail_sent:
            raise TimeoutError('SYNTHETIC PRIVATE post-acceptance database error')
        if payload.get('error_message') == EmailService.LEGACY_OUTCOME_UNKNOWN and self.fail_unknown_write:
            raise TimeoutError('SYNTHETIC PRIVATE database unavailable')
        self.row.update(deepcopy(payload))
        if payload['status'] == 'queued' and self.lose_claim_response:
            raise TimeoutError('Claim committed; response lost')
        if payload['status'] == 'sent' and self.lose_sent_response:
            raise TimeoutError('Sent completion committed; response lost')
        if payload['status'] == 'sent' and self.empty_sent_response:
            return []
        return [deepcopy(self.row)]


def service(db, deliveries, *, enabled=True, transport=None):
    return EmailService(settings(email_enabled=enabled), db,
                        transport=transport or (lambda *args: deliveries.append(args) or 'synthetic-provider'))


def send(email):
    return email.send(recipient=RECIPIENT, email_type='payment_confirmed', content=CONTENT,
                      idempotency_key='synthetic-financial-event')


def test_disabled_delivery_is_only_safe_durable_retry_proof():
    async def run():
        db, deliveries = DB(), []
        first = await send(service(db, deliveries, enabled=False))
        assert first['status'] == 'failed' and not deliveries
        assert db.row['error_message'] == EmailService.LEGACY_NOT_ATTEMPTED
        result = await service(db, deliveries).retry(LOG, RECIPIENT, CONTENT)
        assert result['sent'] and len(deliveries) == 1 and db.row['status'] == 'sent'
        assert db.updates[1][1] == {'id': 'eq.' + LOG, 'status': 'eq.failed',
            'error_message': 'eq.' + EmailService.LEGACY_NOT_ATTEMPTED,
            'recipient': 'eq.' + RECIPIENT, 'event_snapshot': 'is.null'}
    asyncio.run(run())


def test_transport_accepted_then_completion_database_failure_cannot_resend():
    async def run():
        db, deliveries = DB(), []
        db.fail_sent = True
        email = service(db, deliveries)
        result = await send(email)
        assert result == {'status': 'unknown', 'sent': False, 'log_id': LOG}
        assert len(deliveries) == 1 and db.row['status'] == 'failed'
        assert db.row['error_message'] == EmailService.LEGACY_OUTCOME_UNKNOWN
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'not_retryable'
        assert len(deliveries) == 1
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['lost_response', 'empty_response'])
def test_sent_already_committed_is_never_downgraded_to_failed(mode):
    async def run():
        db, deliveries = DB(), []
        db.lose_sent_response = mode == 'lost_response'
        db.empty_sent_response = mode == 'empty_response'
        email = service(db, deliveries)
        assert (await send(email))['status'] == 'unknown'
        assert db.row['status'] == 'sent' and db.row['provider_message_id'] == 'synthetic-provider'
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'not_retryable'
        assert len(deliveries) == 1
        assert db.updates[-2][1]['status'] == 'eq.queued'
    asyncio.run(run())


def test_provider_timeout_after_possible_acceptance_requires_review():
    async def run():
        db, deliveries = DB(), []
        def timeout(*args):
            deliveries.append(args)
            raise TimeoutError('SYNTHETIC PRIVATE provider detail')
        email = service(db, deliveries, transport=timeout)
        result = await send(email)
        assert result['status'] == 'unknown' and not result['sent']
        assert 'PRIVATE' not in db.row['error_message']
        await email.retry(LOG, RECIPIENT, CONTENT)
        assert len(deliveries) == 1
    asyncio.run(run())


def test_even_failure_to_record_unknown_leaves_nonretryable_queued_claim():
    async def run():
        db, deliveries = DB(), []
        db.fail_sent = db.fail_unknown_write = True
        email = service(db, deliveries)
        assert (await send(email))['status'] == 'unknown'
        assert db.row['status'] == 'queued'
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'not_retryable'
        assert len(deliveries) == 1
    asyncio.run(run())


def test_simultaneous_safe_retries_have_only_one_claim_and_transport():
    async def run():
        db, deliveries = DB(), []
        db.row.update(status='failed', error_message=EmailService.LEGACY_NOT_ATTEMPTED)
        email = service(db, deliveries)
        results = await asyncio.gather(*(email.retry(LOG, RECIPIENT, CONTENT) for _ in range(8)))
        assert sum(result['sent'] for result in results) == 1 and len(deliveries) == 1
        assert db.row['status'] == 'sent'
    asyncio.run(run())


def test_lost_safe_claim_response_never_enters_transport_or_retries_queued():
    async def run():
        db, deliveries = DB(), []
        db.row.update(status='failed', error_message=EmailService.LEGACY_NOT_ATTEMPTED)
        db.lose_claim_response = True
        email = service(db, deliveries)
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'unknown'
        assert db.row['status'] == 'queued' and not deliveries
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'not_retryable'
    asyncio.run(run())


@pytest.mark.parametrize('status,error', [('queued', None), ('queued', EmailService.LEGACY_NOT_ATTEMPTED),
    ('failed', None), ('failed', 'OSError: email delivery failed'),
    ('failed', EmailService.LEGACY_OUTCOME_UNKNOWN), ('sent', EmailService.LEGACY_NOT_ATTEMPTED)])
def test_legacy_ambiguous_or_queued_never_retries_even_after_crash(status,error):
    db, deliveries = DB(), []
    db.row.update(status=status, error_message=error, created_at='2000-01-01T00:00:00Z')
    result = asyncio.run(service(db, deliveries).retry(LOG, RECIPIENT, CONTENT))
    assert result['status'] == 'not_retryable' and not deliveries


def test_safe_claim_cannot_change_frozen_recipient_or_convert_managed_snapshot():
    async def run():
        db, deliveries = DB(), []
        db.row.update(status='failed', error_message=EmailService.LEGACY_NOT_ATTEMPTED)
        email = service(db, deliveries)
        assert (await email.retry(LOG, 'other@example.test', CONTENT))['status'] == 'not_retryable'
        db.row['event_snapshot'] = {'version': 1}
        assert (await email.retry(LOG, RECIPIENT, CONTENT))['status'] == 'not_retryable'
        assert not deliveries
    asyncio.run(run())


@pytest.mark.parametrize('claimed', [[None], [{'id': 'other', 'status': 'queued'}],
                                    [{'id': LOG, 'status': 'failed'}]])
def test_malformed_claim_response_never_enters_transport(claimed):
    db, deliveries = DB(), []
    db.update = AsyncMock(return_value=claimed)
    result = asyncio.run(service(db, deliveries).retry(LOG, RECIPIENT, CONTENT))
    assert result['status'] == 'unknown' and not deliveries


def retry_route(monkeypatch, **changes):
    row = {'id': CUSTOMER, 'order_id': CUSTOMER, 'email_type': 'payment_confirmed',
        'status': 'failed', 'error_message': None, 'event_snapshot': None,
        'recipient': RECIPIENT, 'created_at': '2000-01-01T00:00:00Z', **changes}
    original = server.db.select
    async def select(table, *, params):
        return [deepcopy(row)] if table == 'email_logs' else await original(table, params=params)
    monkeypatch.setattr(server.db, 'select', select)
    legacy, outbox = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server, '_send_order_email', legacy)
    monkeypatch.setattr(server, '_deliver_order_notification', outbox)
    monkeypatch.setattr(server, '_audit', AsyncMock())
    return legacy, outbox


@pytest.mark.parametrize('kind', ['order_confirmation', 'payment_confirmed', 'refund_confirmed', 'withdrawal_received'])
@pytest.mark.parametrize('status,error', [('failed', 'OSError: email delivery failed'),
    ('failed', EmailService.LEGACY_OUTCOME_UNKNOWN), ('queued', None)])
def test_admin_retry_refuses_ambiguous_financial_and_old_queued_rows(client,monkeypatch,kind,status,error):
    legacy, outbox = retry_route(monkeypatch, email_type=kind, status=status, error_message=error)
    response = client.post('/api/admin/email-logs/' + CUSTOMER + '/retry', headers=HEADERS)
    assert response.status_code == 409 and 'manual provider review' in response.json()['detail']
    legacy.assert_not_awaited(); outbox.assert_not_awaited()


@pytest.mark.parametrize('result,accepted', [
    ({'status': 'sent', 'sent': True}, True), ({'status': 'failed', 'sent': False}, False),
    ({'status': 'unknown', 'sent': False}, False), ({'status': 'not_retryable', 'sent': False}, False),
    (None, False),
])
def test_admin_proven_unattempted_retry_reports_actual_sent_flag(client,monkeypatch,result,accepted):
    legacy, outbox = retry_route(monkeypatch, email_type='order_confirmation', error_message=EmailService.LEGACY_NOT_ATTEMPTED)
    legacy.return_value = result
    response = client.post('/api/admin/email-logs/' + CUSTOMER + '/retry', headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {'accepted': accepted, 'delivery': result['status'] if result else 'failed'}
    legacy.assert_awaited_once_with('order_confirmation', CUSTOMER, amount_cents=None, retry_log_id=CUSTOMER)
    outbox.assert_not_awaited()


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
def test_legacy_financial_receipt_never_reconstructed_even_if_transport_was_disabled(client,monkeypatch,kind):
    legacy, outbox = retry_route(monkeypatch, email_type=kind, error_message=EmailService.LEGACY_NOT_ATTEMPTED)
    response = client.post('/api/admin/email-logs/' + CUSTOMER + '/retry', headers=HEADERS)
    assert response.status_code == 409
    legacy.assert_not_awaited(); outbox.assert_not_awaited()


def test_withdrawal_retry_renders_the_saved_receipt_safely(client,monkeypatch):
    receipt='Commande TY-FIXTURE\n<script>untrusted</script>'
    legacy,outbox=retry_route(monkeypatch,email_type='withdrawal_received',
        error_message=EmailService.LEGACY_NOT_ATTEMPTED,metadata={'receipt_text':receipt})
    retry=AsyncMock(return_value={'status':'sent','sent':True})
    monkeypatch.setattr(server.email_service,'retry',retry)
    response=client.post('/api/admin/email-logs/'+CUSTOMER+'/retry',headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {'accepted':True,'delivery':'sent'}
    content=retry.await_args.args[2]
    assert receipt in content.text
    assert '<script>' not in content.html and '&lt;script&gt;' in content.html
    assert '<br>' in content.html
    legacy.assert_not_awaited();outbox.assert_not_awaited()
