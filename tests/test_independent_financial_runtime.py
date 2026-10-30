"""Independent bounded runtime/queue checks, injected DB and transport only."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

from app.services.financial_notification_runtime import financial_notification_runtime
from app.services.financial_notification_worker import FinancialNotificationWorker


def row(number, *, state='pending', source='atomic_financial_transition', snapshot=True):
    return {'id': str(UUID(int=number)), 'email_type': 'payment_confirmed',
        'delivery_state': state, 'metadata': {'source': source},
        'event_snapshot': {} if snapshot else None}


class Queue:
    def __init__(self, rows, *, invalid=()):
        self.rows = rows
        self.invalid = set(invalid)
        self.visited = []
        self.transports = []
        self.selects = 0
        self.db = self

    async def select(self, table, *, params):
        assert table == 'email_logs'
        self.selects += 1
        eligible = list(self.rows)
        state = params.get('delivery_state')
        if state == 'eq.pending':
            eligible = [r for r in eligible if r['delivery_state'] == 'pending']
        elif state == 'in.(pending,blocked)':
            eligible = [r for r in eligible if r['delivery_state'] in {'pending', 'blocked'}]
        else:
            raise AssertionError('Unmodelled queue state filter')
        if params.get('metadata->>source') == 'eq.atomic_financial_transition':
            eligible = [r for r in eligible if r['metadata']['source'] == 'atomic_financial_transition']
        if params.get('event_snapshot') == 'not.is.null':
            eligible = [r for r in eligible if r['event_snapshot'] is not None]
        return [deepcopy({k: r[k] for k in ('id', 'email_type', 'delivery_state')})
                for r in eligible[:params['limit']]]

    async def deliver_financial(self, identity, *, enabled):
        assert enabled is True
        record = next(r for r in self.rows if r['id'] == identity)
        self.visited.append(identity)
        if record['delivery_state'] == 'blocked':
            return {'status': 'blocked', 'sent': False}
        if identity in self.invalid:
            record['delivery_state'] = 'blocked'
            return {'status': 'blocked', 'sent': False}
        record['delivery_state'] = 'sent'
        self.transports.append(identity)
        return {'status': 'sent', 'sent': True}


def test_many_old_blocked_rows_do_not_starve_new_pending_receipt():
    blocked = [row(n, state='blocked') for n in range(1, 8)]
    other = [row(8, source='historical_import'), row(9, snapshot=False)]
    valid = row(10)
    box = Queue([*blocked, *other, valid])
    worker = FinancialNotificationWorker(box, enabled=True, batch_size=3)
    async def run():
        for _ in range(3):
            await worker.run_once()
    asyncio.run(run())
    assert box.transports == [valid['id']]
    assert box.visited == [valid['id']]
    assert all(r['delivery_state'] == 'blocked' for r in blocked)


def test_invalid_pending_is_quarantined_then_next_tick_progresses():
    bad, good = row(1), row(2)
    box = Queue([bad, good], invalid={bad['id']})
    worker = FinancialNotificationWorker(box, enabled=True, batch_size=1)
    async def run():
        first = await worker.run_once()
        second = await worker.run_once()
        third = await worker.run_once()
        return first, second, third
    first, second, third = asyncio.run(run())
    assert first['sent'] == 0 and second['sent'] == 1 and third['attempted'] == 0
    assert bad['delivery_state'] == 'blocked'
    assert box.visited == [bad['id'], good['id']]
    assert box.transports == [good['id']]


def test_runtime_exits_without_retrying_claimed_unknown_or_sent():
    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = []
        async def select(*_args, **_kwargs):
            return [{'id': str(UUID(int=1)), 'email_type': 'payment_confirmed', 'delivery_state': 'pending'}]
        async def deliver(identity, **_kwargs):
            calls.append(identity)
            entered.set()
            await release.wait()
            return {'status': 'unknown', 'sent': False}
        box = SimpleNamespace(db=SimpleNamespace(select=select), deliver_financial=deliver)
        async with financial_notification_runtime(box, enabled=True) as task:
            await asyncio.wait_for(entered.wait(), timeout=1)
            release.set()
        assert task.done() and len(calls) == 1
        await asyncio.sleep(0)
        assert len(calls) == 1
    asyncio.run(run())
