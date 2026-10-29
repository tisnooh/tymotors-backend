"""Frozen financial receipts; injected local transport, no external email."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import server
from tests.test_order_notification_outbox import Db, ORDER, service


def fixture(kind='refund_confirmed'):
    db = Db()
    refunded = 500 if kind == 'refund_confirmed' else 0
    db.row['email_type'] = kind
    db.row['event_snapshot']['items'] = [{'product_name': 'Synthetic receipt item', 'sku': 'SYNTHETIC',
                                        'quantity': 1, 'unit_amount_cents': 900}]
    db.row['event_snapshot']['order'].update(is_test=False, payment_status='paid',
        subtotal_cents=900, shipping_amount_cents=100, tax_amount_cents=100,
        refunded_amount_cents=refunded, stripe_payment_intent_id='pi_SyntheticReceipt')
    db.row['event_snapshot']['financial'] = {'kind': kind, 'refunded_amount_cents': refunded,
        'total_cents': 1000, 'payment_intent_id': 'pi_SyntheticReceipt', 'occurred_at': '2026-10-29T00:00:00Z'}
    return db


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
def test_valid_frozen_financial_receipt_is_sent_once(kind):
    db, sent = fixture(kind), []
    outbox = service(db, lambda *args: sent.append(args))
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['sent']
    assert not asyncio.run(outbox.deliver('fixture-log', 'admin'))['sent']
    assert len(sent) == 1
    if kind == 'refund_confirmed':
        assert 'Montant remboursé : 5,00 EUR' in sent[0][1].text


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
@pytest.mark.parametrize('field,value', [('refunded_amount_cents', True), ('refunded_amount_cents', '500'),
    ('refunded_amount_cents', -1), ('refunded_amount_cents', None), ('total_cents', 999),
    ('payment_intent_id', 'pi_other'), ('occurred_at', '2026-10-29'), ('kind', 'invented')])
def test_damaged_financial_snapshot_is_blocked(kind, field, value):
    db = fixture(kind)
    db.row['event_snapshot']['financial'][field] = value
    result = asyncio.run(service(db, lambda *_: pytest.fail('No transport')).deliver('fixture-log', 'admin'))
    assert result['status'] == 'blocked' and db.claim_ready is False


@pytest.mark.parametrize('field,value', [('currency', 'USD'), ('is_test', True), ('total_cents', 1500),
    ('refunded_amount_cents', True), ('payment_status', 'unpaid'), ('stripe_payment_intent_id', 'pi_other')])
def test_financial_order_snapshot_mismatch_is_blocked(field, value):
    db = fixture()
    db.row['event_snapshot']['order'][field] = value
    assert asyncio.run(service(db, lambda *_: pytest.fail('No transport')).deliver('fixture-log', 'admin'))['status'] == 'blocked'


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
def test_lost_financial_delivery_completion_never_resends(kind):
    db, sent = fixture(kind), []
    db.fail_finish = True
    outbox = service(db, lambda *args: sent.append(args))
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'unknown'
    assert asyncio.run(outbox.deliver('fixture-log', 'admin'))['status'] == 'claimed'
    assert len(sent) == 1


@pytest.mark.parametrize('items', [[], [None], [{'quantity': True, 'unit_amount_cents': 900}],
    [{'quantity': 1, 'unit_amount_cents': 800}], [{'quantity': 1, 'unit_amount_cents': '900'}]])
def test_financial_receipt_items_are_consistent(items):
    db = fixture()
    db.row['event_snapshot']['items'] = items
    assert asyncio.run(service(db, lambda *_: pytest.fail('No transport')).deliver('fixture-log', 'admin'))['status'] == 'blocked'


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
@pytest.mark.parametrize('row', [None, {'event_snapshot': None}, {'event_snapshot': {}, 'delivery_state': 'pending'}])
def test_webhook_path_only_observes_durable_receipt(monkeypatch, kind, row):
    db = AsyncMock()
    db.select.return_value = [] if row is None else [deepcopy(row)]
    monkeypatch.setattr(server, 'db', db)
    sender = AsyncMock()
    monkeypatch.setattr(server, 'email_service', sender)
    result = asyncio.run(server._send_order_email(kind, ORDER, amount_cents=500))
    assert result['sent'] is False
    assert db.select.await_args.args[0] == 'email_logs'
    sender.send.assert_not_awaited()
    sender.retry.assert_not_awaited()


@pytest.mark.parametrize('kind', ['payment_confirmed', 'refund_confirmed'])
def test_internal_financial_retry_cannot_bypass_immutable_outbox(monkeypatch, kind):
    db, sender = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server, 'db', db)
    monkeypatch.setattr(server, 'email_service', sender)
    result = asyncio.run(server._send_order_email(kind, ORDER, amount_cents=500, retry_log_id='synthetic-log'))
    assert result == {'sent': False, 'status': 'financial_receipt_requires_review'}
    db.select.assert_not_awaited()
    sender.send.assert_not_awaited()
    sender.retry.assert_not_awaited()
