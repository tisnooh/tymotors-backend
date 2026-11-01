import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import server
from app.services.email_templates import password_recovery
from app.supabase_rest import SupabaseError, SupabaseRest


@pytest.mark.parametrize(
    "provider_status,payload,expected",
    [
        (200, {"hashed_token": "hash-fixture"}, "hash-fixture"),
        (404, {"message": "User not found"}, None),
        (429, {"message": "rate limited"}, 429),
        (400, {"message": "private provider detail"}, 503),
        (503, {"message": "private provider detail"}, 503),
        (200, {}, 503),
    ],
)
def test_recovery_link_generation_uses_server_key_without_exposing_provider_errors(provider_status, payload, expected):
    def handler(request):
        assert request.url.path == "/auth/v1/admin/generate_link"
        assert request.headers["apikey"] == "private_fixture"
        assert request.headers["authorization"] == "Bearer private_fixture"
        assert request.headers["content-type"] == "application/json"
        assert request.read() == (
            b'{"type":"recovery","email":"owner@example.com",'
            b'"redirect_to":"https://tymotors.vercel.app/auth/confirm"}'
        )
        return httpx.Response(provider_status, json=payload)

    db = SupabaseRest("https://example.supabase.co", "private_fixture", "public_fixture")
    db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def check():
        try:
            if isinstance(expected, int):
                with pytest.raises(SupabaseError) as caught:
                    await db.generate_password_recovery_token("owner@example.com", "https://tymotors.vercel.app/auth/confirm")
                assert caught.value.status_code == expected
                assert "private provider detail" not in caught.value.detail
            else:
                token = await db.generate_password_recovery_token("owner@example.com", "https://tymotors.vercel.app/auth/confirm")
                assert token == expected
        finally:
            await db.close()

    asyncio.run(check())


def test_recovery_email_is_branded_and_html_escapes_link():
    content = password_recovery("https://tymotors.vercel.app/auth/confirm?token_hash=a&b=c")
    assert content.subject.startswith("TYMotors")
    assert "TYMOTORS" in content.html
    assert "token_hash=a&amp;b=c" in content.html
    assert "token_hash=a&b=c" in content.text


def test_forgot_route_sends_branded_link_without_returning_token(monkeypatch):
    sent = []

    async def generate(_email, _redirect):
        return "hash-fixture"

    async def deliver(**kwargs):
        sent.append(kwargs)
        return {"sent": True}

    monkeypatch.setattr(server.db, "generate_password_recovery_token", generate)
    monkeypatch.setattr(server.email_service, "send", deliver)
    server.auth_email_attempts.clear()
    response = TestClient(server.app).post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert sent[0]["email_type"] == "password_reset"
    assert "token_hash=hash-fixture&type=recovery" in sent[0]["content"].text
    assert "hash-fixture" not in str(response.json())


def test_forgot_route_does_not_claim_success_if_delivery_fails(monkeypatch):
    async def generate(_email, _redirect):
        return "hash-fixture"

    async def fail(**_kwargs):
        return {"sent": False}

    monkeypatch.setattr(server.db, "generate_password_recovery_token", generate)
    monkeypatch.setattr(server.email_service, "send", fail)
    server.auth_email_attempts.clear()
    response = TestClient(server.app).post("/api/auth/forgot-password", json={"email": "owner@example.com"})
    assert response.status_code == 503
    assert "hash-fixture" not in response.text
