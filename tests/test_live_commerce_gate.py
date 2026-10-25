"""No real provider/network: an active product cannot enable legacy live sales."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
import server


@pytest.mark.parametrize('legal_ready,expected', [(False,503),(True,409)])
def test_live_legacy_payment_stays_closed_before_cart_and_provider(monkeypatch,legal_ready,expected):
    provider=AsyncMock()
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='live'))
    monkeypatch.setattr(server,'stripe_client',SimpleNamespace(v1=SimpleNamespace(
        checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=provider)))))
    monkeypatch.setattr(server,'legal_ready',lambda:legal_ready)
    cart,rpc=AsyncMock(),AsyncMock()
    monkeypatch.setattr(server,'_cart_for',cart)
    monkeypatch.setattr(server.db,'rpc',rpc)
    response=TestClient(server.app).post('/api/create-checkout-session',headers={'X-Session-Id':'gate_guest_0123456789'})
    assert response.status_code==expected
    cart.assert_not_awaited();rpc.assert_not_awaited();provider.assert_not_awaited()


def test_existing_sandbox_path_is_not_disabled_by_live_guard(monkeypatch):
    monkeypatch.setattr(server,'settings',replace(server.settings,stripe_mode='test'))
    monkeypatch.setattr(server,'stripe_client',object())
    monkeypatch.setattr(server,'legal_ready',lambda:False)
    monkeypatch.setattr(server,'_rate_limit',lambda *_args:None)
    cart=AsyncMock(return_value=None)
    monkeypatch.setattr(server,'_cart_for',cart)
    monkeypatch.setattr(server,'_cart_response',AsyncMock(return_value={'items':[]}))
    response=TestClient(server.app).post('/api/create-checkout-session',headers={'X-Session-Id':'gate_guest_0123456789'})
    assert response.status_code==400 and response.json()['detail']=='Cart is empty'
    cart.assert_awaited_once()
