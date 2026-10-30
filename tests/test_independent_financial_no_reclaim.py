"""Adversarial system-entry checks; no database or provider is contacted."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.order_notification_outbox import OrderNotificationOutbox


@pytest.mark.parametrize('state', ['blocked', 'claimed', 'unknown', 'sent', None])
def test_system_entry_cannot_reclaim_nonpending_receipt(state):
    db = SimpleNamespace(select=AsyncMock(return_value=[{'delivery_state': state}]), rpc=AsyncMock())
    service = SimpleNamespace(db=db, transport=Mock())
    result = asyncio.run(OrderNotificationOutbox(service).deliver_financial('synthetic-log', enabled=True))
    assert result['sent'] is False
    assert result['status'] == (state or 'unknown')
    db.rpc.assert_not_awaited()
    service.transport.assert_not_called()
