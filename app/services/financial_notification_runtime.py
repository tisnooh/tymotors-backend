"""Owned application lifecycle for the persisted financial notification queue.

Opt-in configuration and the independent SQL gate both remain required. No
legacy backfill, provider retry after ambiguous outcome or supplier operation.
"""
import asyncio
from contextlib import asynccontextmanager
import logging

from app.services.financial_notification_worker import FinancialNotificationWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def financial_notification_runtime(outbox, *, enabled=False, interval_seconds=30,
                                         shutdown_seconds=45):
    if (type(enabled) is not bool or type(interval_seconds) is not int
            or not 5 <= interval_seconds <= 3600 or type(shutdown_seconds) is not int
            or not 1 <= shutdown_seconds <= 120):
        raise ValueError('Invalid financial notification runtime configuration')
    if not enabled:
        yield None
        return
    stopped = asyncio.Event()
    worker = FinancialNotificationWorker(outbox, enabled=True, stopped=stopped.is_set)

    async def loop():
        while not stopped.is_set():
            try:
                await worker.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # No recipient, provider error, body or credential in logs.
                logger.warning('Financial notification tick requires inspection')
            try:
                await asyncio.wait_for(stopped.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(loop(), name='tymotors-financial-notifications')
    try:
        yield task
    finally:
        stopped.set()  # No new claim after the in-flight bounded batch.
        try:
            await asyncio.wait_for(task, timeout=shutdown_seconds)
        except asyncio.TimeoutError:
            # Cancellation cannot recall a sync provider request already accepted.
            # The persisted claim remains non-retryable and must be reconciled.
            logger.warning('Financial notification shutdown requires reconciliation')
