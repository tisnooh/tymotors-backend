from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.supplier_inbox import create_supplier_router, normalize_phone, service_window_open, verify_meta_signature


class FakeDB:
    async def select(self, table, *, params=None):
        return []


def test_phone_normalization():
    assert normalize_phone("+33 6 12 34 56 78") == "33612345678"


def test_signature_checks_every_byte():
    secret, body = "local-secret", b'{"entry":[]}'
    valid = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_meta_signature(body, valid, secret)
    assert not verify_meta_signature(body + b" ", valid, secret)
    assert not verify_meta_signature(body, valid, "")
    assert not verify_meta_signature(body, None, secret)


def test_service_window_is_only_24h():
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert service_window_open((now - timedelta(hours=23)).isoformat(), now)
    assert not service_window_open((now - timedelta(hours=25)).isoformat(), now)
    assert not service_window_open((now + timedelta(hours=1)).isoformat(), now)
    assert not service_window_open(None, now)


def test_webhook_challenge(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    app = FastAPI()
    app.include_router(create_supplier_router(FakeDB(), lambda: {"id": "test"}), prefix="/api")
    client = TestClient(app)
    result = client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "123456",
    })
    assert result.status_code == 200
    assert result.text == "123456"
    assert client.get("/api/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123456",
    }).status_code == 403


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test-app-secret")
    app = FastAPI()
    app.include_router(create_supplier_router(FakeDB(), lambda: {"id": "test"}), prefix="/api")
    client = TestClient(app)
    assert client.post("/api/whatsapp/webhook", json={"entry": []}).status_code == 403


def test_outbound_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WHATSAPP_OUTBOUND_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(create_supplier_router(FakeDB(), lambda: {"id": "test"}), prefix="/api")
    client = TestClient(app)
    result = client.post("/api/admin/supplier-messages/1ea80166-4dc6-4f0e-9c05-f1b1be4aef16/approve-send")
    assert result.status_code == 503
