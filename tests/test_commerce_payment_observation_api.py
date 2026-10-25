"""Private observation boundary; no provider network or financial mutation."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import time

import pytest
import server
import app.commerce_payment_observation_api as api
from app.commerce_payment_service import CommercePaymentError
from app.commerce_payment_observation import PaymentObservationError
from tests.test_commerce_api import client, HEADERS  # noqa: F401
from tests.test_commerce_pricing import PROFILE

ID = '10000000-0000-4000-8000-000000000099'
PATH = '/api/admin/commerce/checkout-attempts/' + ID + '/provider-observation'


@pytest.fixture
def observation_boundary(client, monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test',
        stripe_secret_key='sk_test_synthetic_not_a_credential'))
    transport = SimpleNamespace(close_async=AsyncMock())
    factory = Mock(return_value=transport)
    monkeypatch.setattr(api.stripe, 'HTTPXClient', factory)
    gateway = Mock()
    monkeypatch.setattr(api, 'TestStripeGateway', gateway)
    inspect = AsyncMock(return_value={'scope': 'provider_observation_only', 'is_test': True})
    service = Mock(return_value=SimpleNamespace(inspect=inspect))
    monkeypatch.setattr(api, 'CommercePaymentObservation', service)
    rpc = AsyncMock()
    monkeypatch.setattr(server.db, 'rpc', rpc)
    monkeypatch.setattr(server, '_rate_limit', lambda *_args: None)
    # The router keeps the original limiter, so use a fresh per-test bucket.
    server.checkout_attempts.clear()
    return client, factory, transport, gateway, service, inspect, rpc


def test_anonymous_cannot_inspect_before_transport_or_storage(observation_boundary):
    client, factory, _, gateway, service, inspect, rpc = observation_boundary
    assert client.get(PATH).status_code == 401
    factory.assert_not_called(); gateway.assert_not_called(); service.assert_not_called()
    inspect.assert_not_awaited(); rpc.assert_not_awaited()


def test_customer_cannot_inspect_provider(observation_boundary, monkeypatch):
    client, factory, _, _, _, inspect, rpc = observation_boundary
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'id': PROFILE, 'role': 'customer'}]))
    assert client.get(PATH, headers=HEADERS).status_code == 403
    factory.assert_not_called(); inspect.assert_not_awaited(); rpc.assert_not_awaited()


@pytest.mark.parametrize('changes,status', [
    ({'stripe_mode': 'live'}, 409), ({'stripe_secret_key': ''}, 503),
])
def test_closed_mode_or_missing_configuration_before_sdk(observation_boundary, monkeypatch, changes, status):
    client, factory, _, _, _, inspect, rpc = observation_boundary
    monkeypatch.setattr(server, 'settings', replace(server.settings, **changes))
    assert client.get(PATH, headers=HEADERS).status_code == status
    factory.assert_not_called(); inspect.assert_not_awaited(); rpc.assert_not_awaited()


def test_own_transport_closed_and_only_persisted_attempt_forwarded(observation_boundary):
    client, factory, transport, gateway, service, inspect, rpc = observation_boundary
    response = client.get(PATH + '?session_id=cs_test_foreign', headers=HEADERS)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    factory.assert_called_once_with(timeout=20)
    assert gateway.call_args.kwargs == {'http_client': transport}
    assert service.call_args.args == (server.db, gateway.return_value)
    assert str(inspect.await_args.args[0]) == ID
    assert not inspect.await_args.kwargs
    transport.close_async.assert_awaited_once(); rpc.assert_not_awaited()


@pytest.mark.parametrize('error_type,status', [(CommercePaymentError,503),(TimeoutError,502)])
def test_configuration_or_timeout_detail_is_redacted_and_closed(observation_boundary,error_type,status):
    client, _, transport, _, _, inspect, rpc = observation_boundary
    inspect.side_effect = error_type('PRIVATE_PROVIDER_SECRET')
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == status
    assert 'PRIVATE' not in response.text
    transport.close_async.assert_awaited_once(); rpc.assert_not_awaited()


def test_invalid_gateway_still_closes_transport(observation_boundary):
    client, _, transport, gateway, _, inspect, _ = observation_boundary
    gateway.side_effect = CommercePaymentError('test_credentials_required')
    assert client.get(PATH, headers=HEADERS).status_code == 503
    transport.close_async.assert_awaited_once(); inspect.assert_not_awaited()


def test_invalid_attempt_id_never_constructs_sdk(observation_boundary):
    client, factory, _, _, _, _, rpc = observation_boundary
    assert client.get(PATH.replace(ID, 'invalid'), headers=HEADERS).status_code == 422
    factory.assert_not_called(); rpc.assert_not_awaited()


@pytest.mark.parametrize('code,status', [
    ('unknown_attempt',404), ('observation_context_invalid',409),
    ('observation_database_unavailable',503),
])
def test_business_error_closed_without_provider_detail(observation_boundary,code,status):
    client, _, transport, _, _, inspect, rpc = observation_boundary
    inspect.side_effect = PaymentObservationError(code,status)
    response = client.get(PATH,headers=HEADERS)
    assert response.status_code == status
    assert response.json() == {'detail': {'code':code}}
    transport.close_async.assert_awaited_once(); rpc.assert_not_awaited()


def test_rate_limit_checked_before_transport(observation_boundary):
    client, factory, _, _, _, inspect, rpc = observation_boundary
    server.checkout_attempts['payment-observe:' + PROFILE] = [time.monotonic()] * 20
    response = client.get(PATH,headers=HEADERS)
    assert response.status_code == 429
    factory.assert_not_called(); inspect.assert_not_awaited(); rpc.assert_not_awaited()


@pytest.mark.parametrize('observation_failure', [False,True])
def test_cleanup_failure_does_not_override_result_or_leak(observation_boundary,caplog,observation_failure):
    client, _, transport, _, _, inspect, rpc = observation_boundary
    transport.close_async.side_effect = RuntimeError('PRIVATE_TRANSPORT_KEY')
    if observation_failure:
        inspect.side_effect = PaymentObservationError('unknown_attempt',404)
    response = client.get(PATH,headers=HEADERS)
    assert response.status_code == (404 if observation_failure else 200)
    assert 'PRIVATE_TRANSPORT_KEY' not in response.text + caplog.text
    assert 'cleanup requires review' in caplog.text
    rpc.assert_not_awaited()


def test_cleanup_has_separate_finite_deadline(observation_boundary,monkeypatch):
    client, _, transport, _, _, _, rpc = observation_boundary
    original_wait = api.asyncio.wait_for
    deadlines = []
    async def bounded(coroutine,timeout):
        deadlines.append(timeout)
        if timeout == 3:
            coroutine.close()
            raise TimeoutError('PRIVATE_TIMEOUT_BODY')
        return await original_wait(coroutine,timeout)
    monkeypatch.setattr(api.asyncio,'wait_for',bounded)
    response = client.get(PATH,headers=HEADERS)
    assert response.status_code == 200
    assert 'PRIVATE' not in response.text
    assert 25 in deadlines and 3 in deadlines
    transport.close_async.assert_called_once(); rpc.assert_not_awaited()
