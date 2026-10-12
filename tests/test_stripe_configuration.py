from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from tests.test_email_system import settings


@pytest.mark.parametrize("prefix", ["sk_test_", "rk_test_"])
def test_test_secret_and_restricted_keys_are_accepted(prefix):
    config = settings(email_enabled=False, stripe_secret_key=prefix + "synthetic_fixture")
    config.validate()
    assert config.stripe_test_mode is True


@pytest.mark.parametrize("prefix", ["sk_live_", "rk_live_", "invalid_"])
def test_non_test_keys_cannot_start_staging(prefix):
    config = settings(email_enabled=False, stripe_secret_key=prefix + "synthetic_fixture")
    with pytest.raises(RuntimeError, match="live Stripe key"):
        config.validate()


@pytest.mark.parametrize("livemode", [True, None])
def test_test_checkout_rejects_live_or_unspecified_webhook_before_database(monkeypatch, livemode):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_secret_key="rk_test_synthetic_fixture", stripe_webhook_secret="synthetic_signing_fixture"))
    monkeypatch.setattr(server.stripe.Webhook, "construct_event", lambda *args: {"livemode": livemode})
    database = AsyncMock()
    monkeypatch.setattr(server.db, "select", database)
    response = TestClient(server.app).post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "synthetic"})
    assert response.status_code == 400
    database.assert_not_called()


def test_test_webhook_is_processed_and_duplicate_remains_idempotent(monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, stripe_secret_key="rk_test_synthetic_fixture", stripe_webhook_secret="synthetic_signing_fixture"))
    monkeypatch.setattr(server.stripe.Webhook, "construct_event", lambda *args: {"id": "evt_synthetic", "livemode": False})
    monkeypatch.setattr(server.db, "select", AsyncMock(return_value=[{"status": "completed"}]))
    response = TestClient(server.app).post("/api/stripe/webhook", content=b"{}", headers={"Stripe-Signature": "synthetic"})
    assert response.json() == {"received": True, "duplicate": True}
