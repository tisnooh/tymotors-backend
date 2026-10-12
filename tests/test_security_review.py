"""Offline regressions: real parsers/signatures; no hosted credentials/data."""
import asyncio
import base64
import json
import hashlib
import hmac
import time
from dataclasses import replace
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient
import server
from app.request_guard import RequestGuard
from app.supabase_rest import SupabaseRest
from tests.test_stripe_configuration import SIGNING_SECRET


@pytest.fixture(autouse=True)
def clear_tracking_limiter():
    server.tracking_attempts.clear()
    yield
    server.tracking_attempts.clear()


@pytest.mark.parametrize('body', [
    {'email': {'$ne': None}, 'order_number': 'TY-TEST-123'},
    {'email': 'qa@example.com', 'order_number': {'$gt': ''}},
    {'email': 'qa@example.com', 'order_number': 'TY-TEST-123', '$where': 'true'},
])
def test_tracking_rejects_nosql_operator_objects_before_database(monkeypatch, body):
    query = AsyncMock()
    monkeypatch.setattr(server.db, 'select', query)
    assert TestClient(server.app).post('/api/order-tracking', json=body).status_code == 422
    query.assert_not_called()


def test_tracking_wrong_email_is_same_as_missing_order(monkeypatch):
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=[
        [{'customer_email': 'owner@example.com', 'id': 'private'}], []]))
    client = TestClient(server.app)
    first = client.post('/api/order-tracking', json={'email': 'other@example.com', 'order_number': 'TY-TEST-123'})
    missing = client.post('/api/order-tracking', json={'email': 'other@example.com', 'order_number': 'TY-TEST-456'})
    assert first.status_code == missing.status_code == 404 and first.json() == missing.json()
    assert 'owner' not in first.text and 'private' not in first.text


def test_tracking_rate_limit(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(server.db, 'select', query)
    client = TestClient(server.app)
    for _ in range(10):
        assert client.post('/api/order-tracking', json={'email': 'qa@example.com', 'order_number': 'TY-TEST-123'}).status_code == 404
    response = client.post('/api/order-tracking', json={'email': 'qa@example.com', 'order_number': 'TY-TEST-123'})
    assert response.status_code == 429 and response.headers.get('retry-after')
    assert query.await_count == 10


@pytest.mark.parametrize('authenticated', [True, False])
def test_order_idor_has_non_enumerating_response(monkeypatch, authenticated):
    monkeypatch.setattr(server.db, 'get_user', AsyncMock(return_value={'id': 'another-customer'}))
    query = AsyncMock(return_value=[{'user_id': 'owner', 'guest_session_id': 'owner_guest_capability'}])
    monkeypatch.setattr(server.db, 'select', query)
    headers = {'Authorization': 'Bearer fixture'} if authenticated else {'X-Session-Id': 'other_guest_capability'}
    response = TestClient(server.app).get('/api/checkout-session/cs_test_fixture', headers=headers)
    assert response.status_code == 404 and response.json() == {'detail': 'Order not found'}
    assert query.await_count == 1  # No private item/event lookup.


def test_my_orders_is_always_filtered_to_current_user(monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', AsyncMock(return_value={'id': 'current-user'}))
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(server.db, 'select', query)
    assert TestClient(server.app).get('/api/me/orders', headers={'Authorization': 'Bearer fixture'}).status_code == 200
    assert query.call_args.kwargs['params']['user_id'] == 'eq.current-user'


@pytest.mark.parametrize('case', ['missing', 'wrong', 'tampered', 'expired'])
def test_invalid_webhook_signature_has_no_database_side_effect(monkeypatch, case):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_webhook_secret=SIGNING_SECRET))
    query, insert = AsyncMock(), AsyncMock()
    monkeypatch.setattr(server.db, 'select', query)
    monkeypatch.setattr(server.db, 'insert', insert)
    timestamp = int(time.time()) - (600 if case == 'expired' else 0)
    payload = b'{"id":"evt_fixture","livemode":false}'
    digest = hmac.new(SIGNING_SECRET.encode(), f'{timestamp}.'.encode()+payload, hashlib.sha256).hexdigest()
    headers = {} if case == 'missing' else {'Stripe-Signature': f't={timestamp},v1={"0"*64 if case == "wrong" else digest}'}
    if case == 'tampered': payload += b' '
    response = TestClient(server.app).post('/api/stripe/webhook', content=payload, headers=headers)
    assert response.status_code == 400
    query.assert_not_called(); insert.assert_not_called()


def test_validation_does_not_echo_password_input():
    response = TestClient(server.app).post('/api/auth/login', json={'email': 'bad', 'password': {'private': 'never_echo_me'}})
    assert response.status_code == 422 and 'never_echo_me' not in response.text


def test_dependency_errors_are_generic_and_health_does_not_disclose_config(monkeypatch):
    monkeypatch.setattr(server.db, 'select', AsyncMock(side_effect=httpx.ConnectError('private-host-and-credential')))
    response = TestClient(server.app).get('/api/health')
    assert response.status_code == 503 and 'private' not in response.text
    assert response.headers['x-content-type-options'] == 'nosniff'
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[]))
    assert TestClient(server.app).get('/api/health').json() == {'status': 'ok'}


@pytest.mark.parametrize('content, headers', [(b'x' * (1024*1024+1), {}), (b'', {'Content-Length': '99999999'})], ids=['actual-oversized', 'declared-oversized'])
def test_request_size_limit_with_security_headers(content, headers):
    response = TestClient(server.app).post('/api/auth/login', content=content, headers=headers)
    assert response.status_code == 413 and response.headers['x-frame-options'] == 'DENY'


def test_stream_without_content_length_is_bounded():
    async def run():
        seen, output = [], []
        async def app(scope, receive, send): seen.append(True)
        chunks = iter([{'type': 'http.request', 'body': b'123', 'more_body': True}, {'type': 'http.request', 'body': b'456', 'more_body': False}])
        async def receive(): return next(chunks)
        async def send(message): output.append(message)
        await RequestGuard(app, json_limit=5)({'type': 'http', 'path': '/api/test', 'headers': []}, receive, send)
        assert not seen and output[0]['status'] == 413
    asyncio.run(run())


def test_auth_header_is_bounded_before_verification(monkeypatch):
    verify = AsyncMock()
    monkeypatch.setattr(server.db, 'get_user', verify)
    response = TestClient(server.app).get('/api/admin/verify', headers={'Authorization': 'Bearer ' + 'x' * 17000})
    assert response.status_code == 431
    verify.assert_not_called()


def test_stream_read_timeout_is_bounded():
    async def run():
        output = []
        async def app(scope, receive, send): raise AssertionError('Parser must not run')
        async def receive(): await asyncio.sleep(10)
        async def send(message): output.append(message)
        await RequestGuard(app, read_timeout=0.01)({'type': 'http', 'path': '/api/test', 'headers': []}, receive, send)
        assert output[0]['status'] == 408
    asyncio.run(run())


def test_provider_rejected_token_never_calls_privileged_session_rpc():
    async def run():
        db = SupabaseRest('https://example.supabase.co', 'private_fixture', 'public_fixture')
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401)))
        db.rpc = AsyncMock()
        try:
            assert await db.get_user('invalid.fixture.token') is None
            db.rpc.assert_not_called()
        finally: await db.close()
    asyncio.run(run())


@pytest.mark.parametrize('active', [True, False])
def test_revoked_auth_session_is_rejected_even_with_validated_jwt(active):
    user_id, session_id = '10000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002'
    claims = base64.urlsafe_b64encode(json.dumps({'sub': user_id, 'session_id': session_id}).encode()).decode().rstrip('=')
    async def run():
        db = SupabaseRest('https://example.supabase.co', 'private_fixture', 'public_fixture')
        db._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'id': user_id})))
        db.rpc = AsyncMock(return_value=active)
        try:
            assert bool(await db.get_user(f'header.{claims}.fixture')) is active
            db.rpc.assert_awaited_once_with('is_auth_session_active', {'p_session_id': session_id, 'p_user_id': user_id})
        finally: await db.close()
    asyncio.run(run())
