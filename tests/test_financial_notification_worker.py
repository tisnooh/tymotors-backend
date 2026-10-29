"""Dormant tick only; no scheduler, SMTP, provider or hosted database."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.services.financial_notification_worker import FinancialNotificationWorker
from tests.test_financial_notification_outbox import fixture
from tests.test_order_notification_outbox import service


def outbox(count=2):
    rows = [{'id': str(uuid4()), 'email_type': 'payment_confirmed', 'delivery_state': 'pending'} for _ in range(count)]
    return SimpleNamespace(db=SimpleNamespace(select=AsyncMock(return_value=rows)),
                           deliver_financial=AsyncMock(return_value={'sent': True, 'status': 'sent'}))


def test_disabled_by_default_has_no_database_or_transport():
    box = outbox()
    assert asyncio.run(FinancialNotificationWorker(box).run_once())['status'] == 'disabled'
    box.db.select.assert_not_awaited(); box.deliver_financial.assert_not_awaited()


@pytest.mark.parametrize('kwargs', [{'enabled': 'true'}, {'batch_size': True}, {'batch_size': 0},
    {'batch_size': 51}, {'stopped': None}])
def test_strict_configuration(kwargs):
    with pytest.raises(ValueError): FinancialNotificationWorker(outbox(), **kwargs)


def test_one_bounded_batch_and_no_scheduler():
    box = outbox()
    result = asyncio.run(FinancialNotificationWorker(box, enabled=True).run_once())
    assert result == {'status': 'completed', 'attempted': 2, 'sent': 2}
    assert box.db.select.await_count == 1 and box.deliver_financial.await_count == 2


def test_stop_between_logs_prevents_second_attempt():
    box = outbox()
    result = asyncio.run(FinancialNotificationWorker(box, enabled=True,
        stopped=lambda: box.deliver_financial.await_count != 0).run_once())
    assert result == {'status': 'stopped', 'attempted': 1, 'sent': 1}


@pytest.mark.parametrize('value', [True, None, 0, 'false'])
def test_ambiguous_stop_signal_fails_closed(value):
    box = outbox()
    assert asyncio.run(FinancialNotificationWorker(box, enabled=True, stopped=lambda: value).run_once())['status'] == 'stopped'
    box.db.select.assert_not_awaited()


def test_unknown_delivery_never_starts_next_log():
    box = outbox()
    box.deliver_financial.return_value = {'sent': False, 'status': 'unknown'}
    assert asyncio.run(FinancialNotificationWorker(box, enabled=True).run_once())['status'] == 'requires_review'
    assert box.deliver_financial.await_count == 1


def test_database_stop_gate_ends_batch():
    box = outbox()
    box.deliver_financial.return_value = {'sent': False, 'status': 'disabled'}
    assert asyncio.run(FinancialNotificationWorker(box, enabled=True).run_once())['status'] == 'disabled'
    assert box.deliver_financial.await_count == 1


def test_scope_changed_before_sql_claim_skips_without_transport_or_blocking_next_log():
    box = outbox()
    box.deliver_financial.side_effect = [{'sent': False, 'status': 'not_eligible'}, {'sent': True, 'status': 'sent'}]
    assert asyncio.run(FinancialNotificationWorker(box, enabled=True).run_once()) == {
        'status': 'completed', 'attempted': 2, 'sent': 1}


@pytest.mark.parametrize('damage', ['duplicate', 'kind', 'state', 'id', 'oversize'])
def test_invalid_batch_is_rejected_before_any_delivery(damage):
    box = outbox()
    rows = box.db.select.return_value
    if damage == 'duplicate': rows[1] = rows[0].copy()
    if damage == 'kind': rows[0]['email_type'] = 'order_processing'
    if damage == 'state': rows[0]['delivery_state'] = 'unknown'
    if damage == 'id': rows[0]['id'] = 'invalid'
    if damage == 'oversize': rows.extend(rows * 10)
    assert asyncio.run(FinancialNotificationWorker(box, enabled=True).run_once())['status'] == 'unavailable'
    box.deliver_financial.assert_not_awaited()


def test_system_entry_disabled_never_reads_database():
    db = fixture()
    db.select = AsyncMock()
    assert asyncio.run(service(db, lambda *_: pytest.fail('Transport')).deliver_financial('log'))['status'] == 'disabled'
    db.select.assert_not_awaited()


def test_system_entry_uses_separate_claim_and_never_fake_admin():
    db = fixture()
    db.row['metadata'] = {'source': 'atomic_financial_transition'}
    db.rpc = AsyncMock(return_value={'claimed': False, 'state': 'disabled'})
    result = asyncio.run(service(db, lambda *_: pytest.fail('Transport')).deliver_financial('log', enabled=True))
    assert result['status'] == 'disabled'
    name, args = db.rpc.await_args.args
    assert name == 'commerce_claim_financial_notification' and 'p_actor' not in args
