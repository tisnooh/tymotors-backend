"""Synthetic structural contracts only: no SDK, account auth, SQL or payment."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from uuid import uuid4

import pytest

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_checkout_params import CheckoutParamsError, build_checkout_params
from app.commerce_checkout_events import CheckoutEventError, validate_checkout_session
from tests.test_commerce_checkout_params import snapshot  # noqa: F401
from tests.test_commerce_checkout_events import event_context  # noqa: F401

ACCOUNT = 'acct_syntheticAccountA'
OTHER = 'acct_syntheticAccountB'


def bind(data, mode):
    for row in ('order', 'attempt'):
        data[row].update(is_test=mode == 'sandbox', stripe_account_id=ACCOUNT)
    data['server_context'] = CheckoutServerContext(mode, ACCOUNT)
    if 'session' in data:
        session_id = ('cs_test_' if mode == 'sandbox' else 'cs_live_') + 'syntheticSession'
        data['attempt']['session_id'] = session_id
        data['session'].update(id=session_id, livemode=mode == 'production')
        data['provider_account_id'] = ACCOUNT
    return data


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
def test_explicit_context_keeps_params_exact_and_input_immutable(snapshot, mode):
    historical = build_checkout_params(**snapshot)
    bind(snapshot, mode)
    before = deepcopy(snapshot)
    result = build_checkout_params(**snapshot)
    assert snapshot == before
    assert result == historical
    assert ACCOUNT not in json.dumps(result)  # Not emitted as proof/metadata.
    with pytest.raises(FrozenInstanceError):
        snapshot['server_context'].mode = 'production'


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
def test_explicit_context_financial_validation_is_structural_only(event_context, mode):
    bind(event_context, mode)
    before = deepcopy(event_context)
    result = validate_checkout_session(**event_context, require_paid=True)
    assert result['financial_valid'] is True and result['destination_matches'] is True
    assert event_context == before
    assert ACCOUNT not in json.dumps(result)


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('row', ['order', 'attempt'])
@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false', 'opposite'])
def test_modes_are_strict_bools_and_mixed_snapshots_fail(request, fixture_name, call, error, mode, row, value):
    data = bind(request.getfixturevalue(fixture_name), mode)
    data[row]['is_test'] = mode == 'production' if value == 'opposite' else value
    with pytest.raises(error, match='^checkout_mode_mismatch$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
@pytest.mark.parametrize('context', [False, {}, {'mode': 'production', 'stripe_account_id': ACCOUNT},
    CheckoutServerContext('live', ACCOUNT), CheckoutServerContext(None, ACCOUNT),
    CheckoutServerContext(True, ACCOUNT)])
def test_request_json_or_ambiguous_mode_is_not_server_context(request, fixture_name, call, error, context):
    data = bind(request.getfixturevalue(fixture_name), 'production')
    data['server_context'] = context
    with pytest.raises(error, match='^invalid_checkout_server_context$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
@pytest.mark.parametrize('row', ['context', 'order', 'attempt'])
@pytest.mark.parametrize('account', [None, True, '', 'acct_', ' acct_synthetic', 'acct_bad\n', 'acct_a_b', 'PRIVATE_SENTINEL_ONLY', 'acct_' + 'a' * 241])
def test_account_shape_never_inferred_or_coerced(request, fixture_name, call, error, row, account):
    data = bind(request.getfixturevalue(fixture_name), 'production')
    if row == 'context':
        data['server_context'] = CheckoutServerContext('production', account)
    else:
        data[row]['stripe_account_id'] = account
    with pytest.raises(error, match='^invalid_checkout_account_context$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('row', ['order', 'attempt'])
def test_each_frozen_account_must_match_context(request, fixture_name, call, error, mode, row):
    data = bind(request.getfixturevalue(fixture_name), mode)
    data[row]['stripe_account_id'] = OTHER
    with pytest.raises(error, match='^checkout_account_mismatch$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
def test_bound_account_without_context_cannot_silently_take_legacy_path(request, fixture_name, call, error):
    data = bind(request.getfixturevalue(fixture_name), 'sandbox')
    data.pop('server_context')
    with pytest.raises(error, match='^checkout_server_context_required$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call', [
    ('snapshot', build_checkout_params), ('event_context', validate_checkout_session)])
@pytest.mark.parametrize('null_rows', [('order',), ('attempt',), ('order', 'attempt')])
def test_legacy_absent_or_null_accounts_are_not_an_account_validation(request, fixture_name, call, null_rows):
    data = request.getfixturevalue(fixture_name)
    before = call(**data)
    for row in null_rows:
        data[row]['stripe_account_id'] = None
    assert call(**data) == before


@pytest.mark.parametrize('fixture_name,call,error', [
    ('snapshot', build_checkout_params, CheckoutParamsError),
    ('event_context', validate_checkout_session, CheckoutEventError)])
@pytest.mark.parametrize('row', ['order', 'attempt'])
@pytest.mark.parametrize('account', [ACCOUNT, '', False, 0, {}, []])
def test_legacy_partial_or_ambiguous_accounts_are_not_unbound(request, fixture_name, call, error, row, account):
    data = request.getfixturevalue(fixture_name)
    data['order']['stripe_account_id'] = data['attempt']['stripe_account_id'] = None
    data[row]['stripe_account_id'] = account
    with pytest.raises(error, match='^checkout_server_context_required$'):
        call(**data)


@pytest.mark.parametrize('fixture_name,call,error,code', [
    ('snapshot', build_checkout_params, CheckoutParamsError, 'live_checkout_disabled'),
    ('event_context', validate_checkout_session, CheckoutEventError, 'checkout_event_mode_mismatch')])
@pytest.mark.parametrize('row', ['order', 'attempt'])
def test_legacy_null_accounts_still_cannot_enable_production(request, fixture_name, call, error, code, row):
    data = request.getfixturevalue(fixture_name)
    data['order']['stripe_account_id'] = data['attempt']['stripe_account_id'] = None
    data[row]['is_test'] = False
    with pytest.raises(error, match='^' + code + '$'):
        call(**data)


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('account', [None, True, '', OTHER])
def test_provider_account_required_and_metadata_is_not_its_source(event_context, mode, account):
    bind(event_context, mode)
    event_context['provider_account_id'] = account
    event_context['session']['metadata']['stripe_account_id'] = ACCOUNT
    event_context['session']['account'] = ACCOUNT
    code = 'checkout_provider_account_mismatch' if account == OTHER else 'invalid_checkout_account_context'
    with pytest.raises(CheckoutEventError, match='^' + code + '$'):
        validate_checkout_session(**event_context)


def test_provider_context_without_server_context_is_refused(event_context):
    event_context['provider_account_id'] = ACCOUNT
    with pytest.raises(CheckoutEventError, match='^checkout_server_context_required$'):
        validate_checkout_session(**event_context)


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('livemode', [None, 0, 1, 'true', 'false', 'opposite'])
def test_provider_mode_cross_check(event_context, mode, livemode):
    bind(event_context, mode)
    event_context['session']['livemode'] = mode == 'sandbox' if livemode == 'opposite' else livemode
    with pytest.raises(CheckoutEventError, match='^checkout_event_mode_mismatch$'):
        validate_checkout_session(**event_context)


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
def test_cross_mode_session_id_fails_even_if_both_bound_ids_are_replaced(event_context, mode):
    bind(event_context, mode)
    wrong = 'cs_live_crossed' if mode == 'sandbox' else 'cs_test_crossed'
    event_context['session']['id'] = event_context['attempt']['session_id'] = wrong
    with pytest.raises(CheckoutEventError, match='^checkout_event_session_mismatch$'):
        validate_checkout_session(**event_context)


@pytest.mark.parametrize('field', ['session', 'intent', 'order', 'amount', 'currency'])
def test_production_context_preserves_existing_identity_and_money_guards(event_context, field):
    bind(event_context, 'production')
    if field == 'session':
        event_context['session']['id'] = 'cs_live_replaced'
    elif field == 'intent':
        event_context['attempt']['payment_intent_id'] = 'pi_otherBound'
    elif field == 'order':
        event_context['session']['metadata']['order_id'] = str(uuid4())
    elif field == 'amount':
        event_context['session']['amount_total'] += 1
    else:
        event_context['session']['currency'] = 'usd'
    with pytest.raises(CheckoutEventError):
        validate_checkout_session(**event_context)


@pytest.mark.parametrize('origin', ['http://shop.example.com', 'http://localhost:3000',
    'https://localhost', 'https://127.0.0.1', 'https://[::1]', 'https://10.0.0.1',
    'https://foo.localhost', 'https://foo.internal', 'https://foo.test', 'https://foo.invalid'])
def test_production_origin_must_be_public_https(snapshot, origin):
    bind(snapshot, 'production')
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = origin
    with pytest.raises(CheckoutParamsError, match='^invalid_checkout_origin$'):
        build_checkout_params(**snapshot)


def test_historical_sandbox_loopback_still_works(snapshot):
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = 'http://localhost:3000'
    assert build_checkout_params(**snapshot)['success_url'].startswith('http://localhost:3000/')


@pytest.mark.parametrize('mode', [None, 'sandbox', 'production'])
@pytest.mark.parametrize('host', ['127.1', '127.0.1', '0177.0.0.1', '0x7f.0.0.1',
    '192.168.1', '0300.0250.0.1', '0x7f000001', '2130706433', 'example.123', 'foo.0x1',
    '127.0.0.0x', '127.0.0x', '0x7f.0.0.0x', '127.0.0.0X', '127.0.0X', '0X7f.0.0.0X',
    '0x', '0X', '127..1', '127.0..1', '127.0.0.1.', '127.0.0.0x.', '127.0.0.1..',
    '127.0.0.', '127.', '127.0.0.0X.'])
def test_browser_numeric_hosts_are_refused_including_historical_sandbox(snapshot, mode, host):
    if mode is not None:
        bind(snapshot, mode)
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = 'https://' + host
    with pytest.raises(CheckoutParamsError, match='^invalid_checkout_origin$'):
        build_checkout_params(**snapshot)


@pytest.mark.parametrize('mode', [None, 'sandbox', 'production'])
@pytest.mark.parametrize('origin', ['https://shop.example.com', 'https://shop2.example.com:8443',
    'https://8.8.8.8', 'https://[2606:4700:4700::1111]'])
def test_public_canonical_origins_remain_accepted(snapshot, mode, origin):
    if mode is not None:
        bind(snapshot, mode)
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = origin
    assert build_checkout_params(**snapshot)['success_url'].startswith(origin + '/')


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('intent', ['wrongObject', 'pi_', 'pi_' + 'a' * 241, 'pi_bad/slash'])
def test_explicit_context_requires_payment_intent_shape(event_context, mode, intent):
    bind(event_context, mode)
    event_context['session']['payment_intent'] = intent
    with pytest.raises(CheckoutEventError, match='^invalid_checkout_payment_intent$'):
        validate_checkout_session(**event_context)


@pytest.mark.parametrize('mode', ['sandbox', 'production'])
@pytest.mark.parametrize('field', ['currency', 'quantity', 'amount', 'variant'])
def test_builder_explicit_context_does_not_bypass_item_checks(snapshot, mode, field):
    bind(snapshot, mode)
    item = snapshot['items'][0]
    key, value = {'currency': ('currency', 'USD'), 'quantity': ('quantity', True),
                  'amount': ('unit_amount_cents', 5001), 'variant': ('variant_id', 'bad')}[field]
    item[key] = value
    with pytest.raises(CheckoutParamsError):
        build_checkout_params(**snapshot)
