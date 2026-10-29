"""Real SDK HMAC verification, synthetic events only; no provider calls."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from app.commerce_webhook_profiles import load_webhook_profiles, verify_profile_event, WebhookProfileError
from tests.test_email_system import settings


def records():
    return [dict(reference='sandbox-one', mode='sandbox', account_id='acct_sandboxFixture',
                 signing_secret='whsec_synthetic_sandbox_receiver'),
            dict(reference='production-one', mode='production', account_id='acct_productionFixture',
                 signing_secret='whsec_synthetic_production_receiver')]


def body(event, secret):
    raw = json.dumps(event).encode()
    now = str(int(time.time()))
    digest = hmac.new(secret.encode(), now.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return raw, {'Stripe-Signature': 't=' + now + ',v1=' + digest}


def event(*, live=False):
    return {'id': 'evt_profile_synthetic', 'object': 'event', 'livemode': live,
            'type': 'payment_intent.created', 'data': {'object': {'id': 'pi_synthetic', 'object': 'payment_intent'}}}


def configure(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings,
        stripe_webhook_profiles_json=json.dumps(records()), stripe_webhook_secret='',
        stripe_checkout_profile='', stripe_mode='live'))
    for name in ('select', 'insert', 'update', 'rpc'):
        monkeypatch.setattr(server.db, name, AsyncMock())
    return TestClient(server.app)


def test_registry_is_frozen_and_secret_not_in_repr():
    profiles = load_webhook_profiles(json.dumps(records()))
    assert profiles[0].context.mode == 'sandbox'
    assert 'whsec_' not in repr(profiles)
    with pytest.raises(AttributeError):
        profiles[0].reference = 'changed'
    assert load_webhook_profiles('') == ()


@pytest.mark.parametrize('change', [
    'duplicate_ref', 'duplicate_secret', 'legacy_secret', 'json_object', 'unknown_key',
    'no_secret', 'bad_mode', 'bad_account', 'bad_ref', 'boolean', 'empty_list', 'oversize', 'too_many'])
def test_registry_rejects_ambiguous_or_untrusted_config(change):
    data, legacy = records(), ''
    if change == 'duplicate_ref': data[1]['reference'] = data[0]['reference']
    elif change == 'duplicate_secret': data[1]['signing_secret'] = data[0]['signing_secret']
    elif change == 'legacy_secret': legacy = data[0]['signing_secret']
    elif change == 'json_object': data = data[0]
    elif change == 'unknown_key': data[0]['secret_from_client'] = 'no'
    elif change == 'no_secret': data[0].pop('signing_secret')
    elif change == 'bad_mode': data[0]['mode'] = 'test'
    elif change == 'bad_account': data[0]['account_id'] = 'acct_unsafe_with_underscores'
    elif change == 'bad_ref': data[0]['reference'] = '../legacy'
    elif change == 'boolean': data[0]['account_id'] = True
    elif change == 'empty_list': data = []
    elif change == 'oversize': data[0]['signing_secret'] = 'x' * 17000
    elif change == 'too_many': data *= 9
    with pytest.raises(WebhookProfileError) as error:
        load_webhook_profiles(json.dumps(data), legacy_secret=legacy)
    assert str(error.value) == 'invalid_server_webhook_profiles'
    assert 'whsec_' not in str(error.value)


@pytest.mark.parametrize('changes', [{'livemode': True}, {'livemode': 0}, {'livemode': 'false'},
    {'account': 'acct_sandboxFixture'}, {'account': None}, {'context': 'acct_sandboxFixture'},
    {'object': 'not_event'}, {'id': 'not_an_event'}, {'data': {}}, {'type': None}])
def test_correct_signature_still_rejects_wrong_profile_or_shape(changes):
    profile = load_webhook_profiles(json.dumps(records()))[0]
    raw, headers = body({**event(), **changes}, profile.signing_secret)
    with pytest.raises(WebhookProfileError):
        verify_profile_event(profile, raw, headers['Stripe-Signature'])


def test_signature_is_one_secret_exact_raw_body_and_aged_timestamps_rejected():
    first, second = load_webhook_profiles(json.dumps(records()))
    raw, headers = body(event(), first.signing_secret)
    assert verify_profile_event(first, raw, headers['Stripe-Signature']) == event()
    with pytest.raises(WebhookProfileError): verify_profile_event(second, raw, headers['Stripe-Signature'])
    with pytest.raises(WebhookProfileError): verify_profile_event(first, raw + b' ', headers['Stripe-Signature'])
    old = str(int(time.time()) - 1000)
    digest = hmac.new(first.signing_secret.encode(), old.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    with pytest.raises(WebhookProfileError): verify_profile_event(first, raw, 't=' + old + ',v1=' + digest)


def test_settings_profiles_are_opt_in_and_never_include_secrets_in_validation_errors():
    base = settings(email_enabled=False, stripe_webhook_profiles_json=json.dumps(records()),
                    stripe_checkout_profile='sandbox-one')
    base.validate()
    for value in ('unknown', 'production-one'):
        with pytest.raises(RuntimeError, match='match the checkout mode'):
            replace(base, stripe_checkout_profile=value).validate()
    with pytest.raises(RuntimeError, match='webhook profiles'):
        replace(base, stripe_webhook_secret=records()[0]['signing_secret']).validate()
    with pytest.raises(RuntimeError, match='LEGACY_WEBHOOK_MODE'):
        replace(base, stripe_legacy_webhook_mode='unknown').validate()


def test_unknown_profile_or_missing_signature_never_touches_database(monkeypatch):
    client = configure(monkeypatch)
    assert client.post('/api/stripe/webhook/missing', content=b'{}').status_code == 404
    assert client.post('/api/stripe/webhook/sandbox-one', content=b'{}').status_code == 400
    server.db.select.assert_not_awaited()
    server.db.rpc.assert_not_awaited()


def test_receiver_mode_independent_of_current_checkout_mode(monkeypatch):
    client = configure(monkeypatch)  # new checkout live; old account sandbox still receives
    raw, headers = body(event(), records()[0]['signing_secret'])
    assert client.post('/api/stripe/webhook/sandbox-one', content=raw, headers=headers).json() == {
        'received': True, 'ignored': True}
    assert client.post('/api/stripe/webhook/production-one', content=raw, headers=headers).status_code == 400
    raw, headers = body(event(live=True), records()[1]['signing_secret'])
    assert client.post('/api/stripe/webhook/production-one', content=raw, headers=headers).status_code == 200
    server.db.rpc.assert_not_awaited()


def test_failure_receipt_requires_successful_atomic_storage(monkeypatch):
    client = configure(monkeypatch)
    sample = event(live=True)
    sample['type'] = 'payment_intent.payment_failed'
    raw, headers = body(sample, records()[1]['signing_secret'])
    server.db.rpc.return_value = {'received': True, 'requires_reconciliation': True}
    response = client.post('/api/stripe/webhook/production-one', content=raw, headers=headers)
    assert response.status_code == 200
    assert server.db.rpc.call_args.args == ('commerce_record_context_event', {
        'p_event_id': sample['id'], 'p_event_type': sample['type'], 'p_object_id': 'pi_synthetic',
        'p_is_test': False, 'p_stripe_account_id': 'acct_productionFixture', 'p_profile_ref': 'production-one'})
    server.db.rpc.side_effect = RuntimeError('PRIVATE_TRANSPORT_DETAILS')
    response = client.post('/api/stripe/webhook/production-one', content=raw, headers=headers)
    assert response.status_code == 500
    assert 'PRIVATE' not in response.text
    server.db.update.assert_not_awaited()


def test_receiver_bounds_unsigned_body_without_db(monkeypatch):
    client = configure(monkeypatch)
    response = client.post('/api/stripe/webhook/sandbox-one', content=b'x' * 1048577,
                           headers={'Stripe-Signature': 'synthetic'})
    assert response.status_code == 413
    server.db.rpc.assert_not_awaited()


def test_legacy_receiver_keeps_its_original_mode_after_checkout_switch(monkeypatch):
    secret = 'whsec_synthetic_historical_receiver'
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live',
        stripe_legacy_webhook_mode='test', stripe_webhook_secret=secret))
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{'status': 'completed'}]))
    raw, headers = body(event(), secret)
    assert TestClient(server.app).post('/api/stripe/webhook', content=raw, headers=headers).json() == {
        'received': True, 'duplicate': True}


def test_profile_config_loaded_only_from_environment(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv('STRIPE_WEBHOOK_PROFILES_JSON', json.dumps(records()))
    monkeypatch.setenv('STRIPE_CHECKOUT_PROFILE', 'sandbox-one')
    monkeypatch.setenv('STRIPE_LEGACY_WEBHOOK_MODE', 'test')
    try:
        config = get_settings()
        assert config.stripe_checkout_profile == 'sandbox-one'
        assert 'whsec_synthetic_sandbox_receiver' not in repr(config)
    finally:
        get_settings.cache_clear()
