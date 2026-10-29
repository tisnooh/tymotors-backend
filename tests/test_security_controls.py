from dataclasses import replace
from unittest.mock import AsyncMock
import httpx
import asyncio
import pytest
from fastapi.testclient import TestClient
from app.supabase_rest import SupabaseRest, SupabaseError
from tests.test_email_system import settings
import server

@pytest.mark.parametrize('url', ['https://example.supabase.co.attacker.test', 'https://example.supabase.co@attacker.test', 'https://example.supabase.co/path', 'https://example.supabase.co?redirect=1'])
def test_supabase_credentials_destination_is_strict(url):
    with pytest.raises(RuntimeError): settings(email_enabled=False, supabase_url=url).validate()

@pytest.mark.parametrize('origin', ['*', 'http://remote.test', 'https://site.test/path', 'https://user@site.test'])
def test_cors_origins_are_strict(origin):
    with pytest.raises(RuntimeError): settings(email_enabled=False, cors_origins=[origin]).validate()

def test_login_limit_cannot_be_bypassed_with_forwarded_header(monkeypatch):
    server.login_attempts.clear()
    login = AsyncMock(side_effect=SupabaseError(401, 'Identifiants invalides'))
    monkeypatch.setattr(server.db, 'sign_in_password', login)
    client = TestClient(server.app)
    for i in range(5):
        response = client.post('/api/auth/login', json={'email':f'fixture{i}@example.com','password':'synthetic'}, headers={'X-Forwarded-For':f'192.0.2.{i}'})
        assert response.status_code == 401 and response.headers['cache-control'] == 'no-store'
    response = client.post('/api/auth/login', json={'email':'next@example.com','password':'synthetic'},headers={'X-Forwarded-For':'192.0.2.99'})
    assert response.status_code == 429 and response.headers.get('retry-after')
    assert login.await_count == 5
    server.login_attempts.clear()

def test_legacy_live_checkout_does_not_mistake_missing_siret_for_technical_readiness(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live'))
    monkeypatch.setattr(server, 'stripe_client', object())
    monkeypatch.setattr(server, 'legal_ready', lambda: False)
    assert TestClient(server.app).post('/api/create-checkout-session').status_code == 409

def test_login_uses_only_publishable_key_and_returns_only_session_tokens():
    def transport(request):
        assert request.headers['apikey'] == 'public_fixture'
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'access_token':'access_fixture','refresh_token':'refresh_fixture','extra_private':'discard'})
    db = SupabaseRest('https://example.supabase.co','private_fixture','public_fixture')
    async def run():
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        try: assert await db.sign_in_password('qa@example.com','synthetic') == {'access_token':'access_fixture','refresh_token':'refresh_fixture'}
        finally: await db.close()
    asyncio.run(run())
