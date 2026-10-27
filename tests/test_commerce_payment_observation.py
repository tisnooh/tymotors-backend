"""Adversarial sandbox observation, mocked I/O; never real Stripe payment proof."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
import stripe

from app.commerce_payment_observation import CommercePaymentObservation, PaymentObservationError
from app.commerce_payment_service import CommercePaymentError, TestStripeGateway as Gateway
from tests.test_commerce_checkout_events import event_context  # noqa: F401


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def wired(event_context):
    context = deepcopy(event_context)
    context['attempt'].update(state='unknown', first_requested_at='2026-10-24T12:00:00Z',
        params={'private': 'persisted parameters'}, idempotency_key='private-fixed-idempotency-key')
    context['order'].update(status='pending', payment_status='unpaid', refunded_amount_cents=0,
        stripe_session_id=None, stripe_payment_intent_id=None, customer_email='local-private@example.test')
    context['binding'] = {'attempt_id': context['attempt']['id'], 'session_id': context['session']['id']}
    attempt_identity, order_identity = context['attempt']['id'], context['order']['id']
    async def select(table, *, params=None):
        assert params['limit'] == 2
        if table == 'commerce_checkout_attempts':
            assert params['id'] == 'eq.' + attempt_identity
            return [deepcopy(context['attempt'])]
        if table == 'orders':
            assert params['id'] == 'eq.' + order_identity
            return [deepcopy(context['order'])]
        if table == 'commerce_test_sessions':
            assert params['attempt_id'] == 'eq.' + attempt_identity
            return [deepcopy(context['binding'])] if context['binding'] is not None else []
        raise AssertionError(table)
    db = SimpleNamespace(select=AsyncMock(side_effect=select), rpc=AsyncMock(), insert=AsyncMock(),
        update=AsyncMock(), delete=AsyncMock())
    gateway = Gateway('sk_test_synthetic_not_a_credential')
    gateway.retrieve = AsyncMock(side_effect=lambda _: deepcopy(context['session']))
    gateway.create = AsyncMock(side_effect=AssertionError('never create during observation'))
    return context, db, gateway, CommercePaymentObservation(db, gateway)


def no_mutation(db, gateway):
    gateway.create.assert_not_awaited()
    for method in ('rpc', 'insert', 'update', 'delete'):
        getattr(db, method).assert_not_awaited()


def locally_paid(c):
    c['order'].update(status='paid', payment_status='paid',
        stripe_session_id=c['session']['id'], stripe_payment_intent_id=c['session']['payment_intent'])


@pytest.mark.anyio
async def test_paid_observed_is_not_local_settlement_or_refund_proof(wired):
    c, db, gateway, service = wired
    before = deepcopy(c)
    result = await service.inspect(c['attempt']['id'])
    assert c == before
    assert result['observation_status'] == 'provider_paid_awaiting_signed_event'
    assert result['provider_financial_valid'] is True
    assert result['payment_recorded_locally'] is False
    assert result['payment_reconciliation_required'] is True
    assert result['refund_verification'] == 'not_assessed_from_checkout'
    assert result['destination_matches'] is True
    gateway.retrieve.assert_awaited_once_with(c['binding']['session_id'])
    assert db.select.await_count == 6  # recheck after provider read, without SQL locks
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_locally_recorded_payment_does_not_claim_ship_or_consume(wired):
    c, db, gateway, service = wired
    locally_paid(c)
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'payment_recorded_locally'
    assert result['payment_reconciliation_required'] is False
    assert result['fulfillment_review_required'] is True
    assert result['reservation_review_required'] is True
    assert result['mutation_performed'] is False and result['payment_creation_allowed'] is False
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('hold', [True, None, 'false', 0])
async def test_financial_review_cannot_be_cleared_by_paid_checkout(wired, hold):
    c, db, gateway, service = wired
    locally_paid(c)
    c['order']['financial_review_required'] = hold
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'refund_review_required'
    assert result['payment_reconciliation_required'] is True
    assert 'signed_financial_event_requires_review' in result['reason_codes']
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('state', ['drafting','ready','creating','unknown','session_created','cancelled'])
async def test_no_binding_means_manual_lookup_without_sdk(wired, state):
    c, db, gateway, service = wired
    c['binding'] = None
    c['attempt']['state'] = state
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'manual_provider_lookup'
    assert result['reason_codes'] == ['bound_provider_session_missing']
    assert result['provider_read_performed'] is False
    gateway.retrieve.assert_not_awaited()
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('status,expected', [
    ('open', 'provider_open_unpaid'), ('complete', 'provider_async_unpaid'),
    ('expired', 'provider_expired_requires_review'),
])
async def test_unpaid_states_never_release_or_recreate(wired, status, expected):
    c, db, gateway, service = wired
    c['session'].update(status=status, payment_status='unpaid', payment_intent=None)
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == expected
    assert result['provider_financial_valid'] is False
    assert result['payment_reconciliation_required'] is True
    assert result['reservation_review_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_late_paid_snapshot_is_not_denied_due_to_local_clock(wired):
    c, db, gateway, service = wired
    c['session']['expires_at'] = c['attempt']['expires_at'] = 1
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'provider_paid_awaiting_signed_event'
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_wrong_address_keeps_payment_observation_but_review(wired):
    c, db, gateway, service = wired
    locally_paid(c)
    c['session']['shipping_details']['address']['line1'] = 'Untrusted different address'
    result = await service.inspect(c['attempt']['id'])
    assert result['provider_financial_valid'] is True
    assert result['destination_matches'] is False
    assert result['payment_reconciliation_required'] is False
    assert 'destination_requires_review' in result['reason_codes']
    assert result['fulfillment_review_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('changes', [
    {'refunded_amount_cents': 100}, {'refunded_amount_cents': 10500, 'status': 'refunded', 'payment_status': 'refunded'},
    {'refunded_amount_cents': -1}, {'refunded_amount_cents': True}, {'refunded_amount_cents': 10501},
    {'refunded_amount_cents': None}, {'status': 'refunded'}, {'payment_status': 'refunded'},
])
async def test_refunds_require_dedicated_proof_even_if_checkout_still_paid(wired, changes):
    c, db, gateway, service = wired
    locally_paid(c)
    c['order'].update(changes)
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'refund_review_required'
    assert result['payment_reconciliation_required'] is True
    assert result['refund_verification'] == 'not_assessed_from_checkout'
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('changes', [
    {'status': 'pending', 'payment_status': 'paid', 'stripe_payment_intent_id': 'pi_synthetic_paid'},
    {'status': 'paid', 'payment_status': 'unpaid'},
    {'status': 'paid', 'payment_status': 'paid', 'stripe_payment_intent_id': None},
])
async def test_inconsistent_local_financial_states_are_reviewed(wired, changes):
    c, db, gateway, service = wired
    c['order'].update(changes)
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'local_financial_state_review'
    assert result['payment_reconciliation_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_cancelled_but_paid_does_not_authorize_fulfillment(wired):
    c, db, gateway, service = wired
    locally_paid(c)
    c['order']['status'] = 'cancelled'
    result = await service.inspect(c['attempt']['id'])
    assert result['payment_reconciliation_required'] is False
    assert 'cancelled_order_requires_review' in result['reason_codes']
    assert result['fulfillment_review_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_db_context_changed_during_remote_read_requires_another_inspection(wired):
    c, db, gateway, service = wired
    locally_paid(c)
    async def retrieve(_):
        c['order']['refunded_amount_cents'] = 100
        return deepcopy(c['session'])
    gateway.retrieve.side_effect = retrieve
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'observation_context_changed'
    assert result['provider_financial_valid'] is None
    assert result['payment_reconciliation_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_context_unavailable_after_remote_read_is_not_success(wired):
    c, db, gateway, service = wired
    calls = 0
    original = db.select.side_effect
    async def select(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > 3:
            raise RuntimeError('private database error')
        return await original(*args, **kwargs)
    db.select.side_effect = select
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'observation_context_changed'
    assert 'private database error' not in json.dumps(result)
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('changes', [
    {'id': 'cs_test_other'}, {'livemode': True}, {'currency': 'usd'}, {'amount_total': 1},
    {'amount_total': True}, {'payment_intent': 'pi_other'}, {'metadata': {}},
    {'client_reference_id': str(UUID(int=999))}, {'expires_at': 2}, {'status': 'unknown'},
    {'total_details': {}}, {'automatic_tax': {'enabled': True}},
])
async def test_common_validator_rejects_foreign_or_conflicting_provider_snapshots(wired, changes):
    c, db, gateway, service = wired
    locally_paid(c)  # pins PI to local financial history too
    c['session'].update(changes)
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'provider_snapshot_conflict'
    assert result['provider_financial_valid'] is None
    assert result['payment_reconciliation_required'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_local_paid_provider_unpaid_is_conflict_not_refund_proof(wired):
    c, db, gateway, service = wired
    locally_paid(c)
    c['session'].update(payment_status='unpaid')
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'local_financial_state_review'
    assert 'local_paid_provider_unpaid_conflict' in result['reason_codes']
    assert result['refund_verification'] == 'not_assessed_from_checkout'
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('intent', ['fake', ' pi_fake', 'pi_fake ', 'pi_fake space',
    'pi_', 'pi_' + 'x'*241, {'id': 'pi_fake'}, ['pi_fake'], 5, True, 'cs_test_fake',
    'pi_fake\n', 'pi_fake/path'])
async def test_unbound_local_pi_cannot_validate_malformed_provider_intent(wired, intent):
    c, db, gateway, service = wired
    assert c['order']['stripe_payment_intent_id'] is None
    c['session']['payment_intent'] = intent
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'provider_snapshot_conflict'
    assert result['provider_financial_valid'] is None
    assert result['payment_reconciliation_required'] is True
    assert result['payment_recorded_locally'] is False
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('error', [TimeoutError('private-api-key customer@example.test'),
    RuntimeError('https://private-url.test sk_test_PRIVATE metadata=secret'), ValueError('raw provider body')])
async def test_provider_errors_are_redacted_without_mutation(wired, error):
    c, db, gateway, service = wired
    gateway.retrieve.side_effect = error
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'provider_lookup_unavailable'
    assert str(error) not in json.dumps(result)
    assert result['reason_codes'] == ['provider_lookup_unavailable']
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_real_installed_sdk16_resource_is_converted(wired):
    c, db, gateway, service = wired
    resource = stripe.checkout.Session.construct_from(deepcopy(c['session']), None)
    assert hasattr(resource, 'to_dict') and not hasattr(resource, 'to_dict_recursive')
    gateway.retrieve.side_effect = None
    gateway.retrieve.return_value = resource
    result = await service.inspect(c['attempt']['id'])
    assert result['provider_financial_valid'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_legacy_sdk_conversion_supported_without_global_stripe_key(wired):
    c, db, gateway, service = wired
    gateway.retrieve.side_effect = None
    gateway.retrieve.return_value = SimpleNamespace(to_dict_recursive=lambda: deepcopy(c['session']))
    assert (await service.inspect(c['attempt']['id']))['provider_financial_valid'] is True
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('value', [None, [], 'raw untrusted body', {'object': 'payment_intent'}])
async def test_invalid_provider_objects_are_review_not_raw_output(wired, value):
    c, db, gateway, service = wired
    gateway.retrieve.side_effect = None
    gateway.retrieve.return_value = value
    result = await service.inspect(c['attempt']['id'])
    assert result['observation_status'] == 'provider_snapshot_conflict'
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_projection_is_exact_whitelist_and_contains_no_sensitive_values(wired):
    c, db, gateway, service = wired
    c['session']['url'] = 'https://checkout.stripe.com/private-checkout'
    result = await service.inspect(c['attempt']['id'])
    assert set(result) == {'attempt_id','order_id','is_test','scope','attempt_state',
        'local_payment_status','observation_status','provider_read_performed','provider_session_status',
        'provider_payment_status','provider_financial_valid','payment_recorded_locally','destination_matches',
        'payment_reconciliation_required','fulfillment_review_required','reservation_review_required',
        'refund_verification','mutation_performed','payment_creation_allowed','reason_codes'}
    serial = json.dumps(result)
    for forbidden in ('private@example.test', 'local-private@example.test', 'Rue de la Paix', '75001',
        'private-phone','private-checkout','private-fixed-idempotency-key','persisted parameters',
        c['session']['payment_intent'], c['session']['id'], 'shipping_details','metadata','customer_details'):
        assert forbidden not in serial
    no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('value', [None, True, 5, '', 'not-a-uuid', str(UUID(int=0))])
async def test_bad_attempt_identity_stops_before_db_or_sdk(wired, value):
    _, db, gateway, service = wired
    with pytest.raises(PaymentObservationError) as caught:
        await service.inspect(value)
    assert caught.value.code == 'invalid_attempt_id' and caught.value.status_code == 400
    db.select.assert_not_awaited(); gateway.retrieve.assert_not_awaited()
    no_mutation(db, gateway)


@pytest.mark.anyio
async def test_unknown_gateway_rejected_before_context(wired):
    c, db, gateway, _ = wired
    with pytest.raises(PaymentObservationError, match='test_gateway_required'):
        await CommercePaymentObservation(db, object()).inspect(c['attempt']['id'])
    db.select.assert_not_awaited(); no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('table,rows,code', [
    ('commerce_checkout_attempts', [], 'unknown_attempt'),
    ('commerce_checkout_attempts', None, 'observation_context_invalid'),
    ('orders', [], 'observation_order_missing'),
    ('commerce_test_sessions', [{}, {}], 'observation_context_invalid'),
])
async def test_missing_or_ambiguous_context_is_refused(wired, table, rows, code):
    c, db, gateway, service = wired
    original = db.select.side_effect
    async def select(name, **kwargs):
        return rows if name == table else await original(name, **kwargs)
    db.select.side_effect = select
    with pytest.raises(PaymentObservationError) as caught:
        await service.inspect(c['attempt']['id'])
    assert caught.value.code == code
    gateway.retrieve.assert_not_awaited(); no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('section,field,value,code', [
    ('order', 'is_test', False, 'test_observation_only'),
    ('attempt', 'is_test', False, 'test_observation_only'),
    ('order', 'id', str(UUID(int=99)), 'observation_context_invalid'),
    ('order', 'commerce_quote_id', str(UUID(int=99)), 'observation_context_invalid'),
    ('order', 'currency', 'USD', 'observation_context_invalid'),
    ('attempt', 'total_cents', 1, 'observation_context_invalid'),
    ('order', 'subtotal_cents', True, 'observation_context_invalid'),
    ('order', 'status', 'unknown', 'observation_context_invalid'),
    ('order', 'payment_status', 'unknown', 'observation_context_invalid'),
    ('binding', 'attempt_id', str(UUID(int=99)), 'observation_session_binding_invalid'),
    ('binding', 'session_id', 'cs_live_wrong', 'observation_session_binding_invalid'),
    ('binding', 'session_id', 'cs_test_', 'observation_session_binding_invalid'),
    ('binding', 'session_id', 'cs_test_space space', 'observation_session_binding_invalid'),
    ('binding', 'session_id', 'cs_test_' + 'x'*241, 'observation_session_binding_invalid'),
    ('attempt', 'state', 'ready', 'observation_session_binding_invalid'),
    ('attempt', 'first_requested_at', None, 'observation_session_binding_invalid'),
    ('order', 'stripe_session_id', 'cs_test_other', 'observation_session_binding_invalid'),
    ('order', 'stripe_payment_intent_id', 'private bad pi', 'observation_context_invalid'),
])
async def test_exact_server_context_required_before_any_provider_read(wired, section, field, value, code):
    c, db, gateway, service = wired
    c[section][field] = value
    # Original attempt's reserved session_id normally equals the binding.
    with pytest.raises(PaymentObservationError) as caught:
        await service.inspect(c['attempt']['id'])
    assert caught.value.code == code
    gateway.retrieve.assert_not_awaited(); no_mutation(db, gateway)


@pytest.mark.anyio
async def test_db_errors_do_not_escape_with_sensitive_details(wired):
    c, db, gateway, service = wired
    db.select.side_effect = RuntimeError('PRIVATE database endpoint secret')
    with pytest.raises(PaymentObservationError) as caught:
        await service.inspect(c['attempt']['id'])
    assert caught.value.code == 'observation_database_unavailable'
    assert caught.value.status_code == 503
    assert 'PRIVATE' not in str(caught.value)
    gateway.retrieve.assert_not_awaited(); no_mutation(db, gateway)


@pytest.mark.anyio
@pytest.mark.parametrize('value', [None, 4, '', 'cs_live_fake', 'cs_test_', 'cs_test_a/b', 'cs_test_a b'])
async def test_gateway_retrieve_rejects_non_test_sessions_before_sdk(value):
    gateway = Gateway('rk_test_synthetic_not_a_credential')
    method = AsyncMock()
    gateway.client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(retrieve_async=method))))
    with pytest.raises(CommercePaymentError, match='test_session_required'):
        await gateway.retrieve(value)
    method.assert_not_awaited()


@pytest.mark.anyio
async def test_gateway_uses_instance_retrieve_only():
    gateway = Gateway('rk_test_synthetic_not_a_credential')
    method = AsyncMock(return_value={'fixture': True})
    gateway.client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(retrieve_async=method))))
    assert await gateway.retrieve('cs_test_synthetic') == {'fixture': True}
    method.assert_awaited_once_with('cs_test_synthetic')


def test_gateway_optional_owned_http_client_preserves_existing_default(monkeypatch):
    sdk, transport = Mock(), object()
    monkeypatch.setattr('app.commerce_payment_service.stripe.StripeClient', sdk)
    Gateway('rk_test_synthetic_not_a_credential')
    sdk.assert_called_once_with('rk_test_synthetic_not_a_credential')
    sdk.reset_mock()
    Gateway('rk_test_synthetic_not_a_credential', http_client=transport)
    sdk.assert_called_once_with('rk_test_synthetic_not_a_credential', http_client=transport)
