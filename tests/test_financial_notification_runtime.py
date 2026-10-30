"""Managed loop checks; all database/transport operations are synthetic."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.financial_notification_runtime import financial_notification_runtime
from tests.test_email_system import settings


def test_disabled_runtime_never_reads_or_sends():
    box = SimpleNamespace(db=SimpleNamespace(select=AsyncMock()), deliver_financial=AsyncMock())
    async def run():
        async with financial_notification_runtime(box) as task:
            assert task is None
    asyncio.run(run())
    box.db.select.assert_not_awaited()
    box.deliver_financial.assert_not_awaited()


@pytest.mark.parametrize('kwargs', [dict(enabled='true'), dict(interval_seconds=True),
    dict(interval_seconds=0), dict(interval_seconds=3601), dict(shutdown_seconds=0)])
def test_runtime_rejects_ambiguous_configuration(kwargs):
    async def run():
        async with financial_notification_runtime(None, **kwargs):
            pytest.fail('Invalid configuration accepted')
    with pytest.raises(ValueError):
        asyncio.run(run())


def test_lifecycle_stops_after_owned_tick_and_selects_only_pending_atomic_receipts():
    async def run():
        delivered = asyncio.Event()
        async def send(*_args, **_kwargs):
            delivered.set()
            return {'status': 'sent', 'sent': True}
        box = SimpleNamespace(db=SimpleNamespace(select=AsyncMock(return_value=[{
            'id': str(uuid4()), 'email_type': 'payment_confirmed', 'delivery_state': 'pending'}])),
            deliver_financial=AsyncMock(side_effect=send))
        async with financial_notification_runtime(box, enabled=True) as task:
            await asyncio.wait_for(delivered.wait(), timeout=1)
        assert task.done()
        box.deliver_financial.assert_awaited_once()
        query = box.db.select.await_args.kwargs['params']
        assert query['delivery_state'] == 'eq.pending'
        assert query['metadata->>source'] == 'eq.atomic_financial_transition'
        assert query['event_snapshot'] == 'not.is.null'
        calls = box.db.select.await_count
        await asyncio.sleep(0)
        assert box.db.select.await_count == calls
    asyncio.run(run())


def test_pending_tick_exception_does_not_leak_error_or_escape_shutdown(caplog):
    async def run():
        hit = asyncio.Event()
        async def broken(*_args, **_kwargs):
            hit.set()
            raise RuntimeError('PRIVATE_PROVIDER_SECRET')
        box = SimpleNamespace(db=SimpleNamespace(select=AsyncMock(side_effect=broken)))
        async with financial_notification_runtime(box, enabled=True) as task:
            await asyncio.wait_for(hit.wait(), timeout=1)
        assert task.done()
    asyncio.run(run())
    assert 'PRIVATE_PROVIDER_SECRET' not in caplog.text


def test_financial_runtime_requires_email_configuration_but_stays_disabled_by_default():
    base = settings(email_enabled=False)
    assert base.financial_notifications_enabled is False
    base.validate()
    with pytest.raises(RuntimeError, match='require configured email'):
        replace(base, financial_notifications_enabled=True).validate()
    for interval in (False, 0, 3601):
        with pytest.raises(RuntimeError, match='runtime configuration'):
            replace(base, financial_notifications_interval_seconds=interval).validate()
