"""Synthetic normalization tests only: not webhook authentication or settlement."""
from copy import deepcopy
import json
from types import MappingProxyType

import pytest

from app.commerce_refund_events import RefundEventError, normalize_test_refund_event


@pytest.fixture
def event():
    return {
        'object': 'event', 'id': 'evt_synthetic_1', 'type': 'refund.updated',
        'created': 1793091600, 'livemode': False,
        'data': {'object': {
            'object': 'refund', 'id': 're_synthetic_1', 'amount': 1200,
            'currency': 'eur', 'status': 'succeeded',
            'payment_intent': 'pi_synthetic_1', 'charge': 'ch_synthetic_1',
            'metadata': {'order_id': 'UNTRUSTED', 'email': 'private@example.test'},
            'instructions_email': 'private@example.test', 'description': 'PRIVATE',
            'destination_details': {'card': {'reference': 'PRIVATE BANK REFERENCE'}},
        }},
        'metadata': {'secret': 'PRIVATE'}, 'request': {'idempotency_key': 'PRIVATE'},
    }


def refuse(value):
    before = deepcopy(value)
    with pytest.raises(ValueError) as raised:
        normalize_test_refund_event(value)
    assert isinstance(raised.value, RefundEventError)
    assert raised.value.code == str(raised.value) == 'invalid_test_refund_event'
    assert value == before


def test_exact_redacted_projection_without_mutation(event):
    before = deepcopy(event)
    result = normalize_test_refund_event(event)
    assert result == {
        'event_id': 'evt_synthetic_1', 'event_type': 'refund.updated',
        'event_created': 1793091600, 'refund_id': 're_synthetic_1',
        'payment_intent_id': 'pi_synthetic_1', 'charge_id': 'ch_synthetic_1',
        'amount_cents': 1200, 'currency': 'eur', 'refund_status': 'succeeded',
        'charge_refunded_cents': None,
    }
    assert event == before
    assert all(secret not in json.dumps(result) for secret in ('PRIVATE', 'private@example.test', 'UNTRUSTED'))


@pytest.mark.parametrize('kind', ['refund.created', 'refund.updated', 'refund.failed'])
@pytest.mark.parametrize('status', ['pending', 'requires_action', 'succeeded', 'failed', 'canceled', None])
def test_all_documented_types_and_statuses_remain_facts_not_inferences(event, kind, status):
    event['type'] = kind
    event['data']['object']['status'] = status
    assert normalize_test_refund_event(event)['refund_status'] == status


@pytest.mark.parametrize('amount', [0, 1, 99_999_999])
def test_charge_cumulative_is_never_a_refund_delta(event, amount):
    event.update(type='charge.refunded')
    event['data']['object'] = {'object': 'charge', 'id': 'ch_synthetic_1',
                               'payment_intent': None, 'amount_refunded': amount, 'currency': 'eur'}
    assert normalize_test_refund_event(event) == {
        'event_id': 'evt_synthetic_1', 'event_type': 'charge.refunded',
        'event_created': event['created'], 'refund_id': None, 'payment_intent_id': None,
        'charge_id': 'ch_synthetic_1', 'amount_cents': None, 'currency': 'eur',
        'refund_status': None, 'charge_refunded_cents': amount,
    }


@pytest.mark.parametrize('field,prefix,kind', [('payment_intent', 'pi', 'payment_intent'), ('charge', 'ch', 'charge')])
def test_nullable_absent_and_exact_expanded_references(event, field, prefix, kind):
    resource = event['data']['object']
    resource.pop(field)
    assert normalize_test_refund_event(event)[field + '_id'] is None
    resource[field] = None
    assert normalize_test_refund_event(event)[field + '_id'] is None
    resource[field] = {'id': prefix + '_expanded', 'object': kind, 'livemode': False,
                       'metadata': {'secret': 'PRIVATE'}, 'billing_details': {'name': 'PRIVATE'}}
    before = deepcopy(event)
    result = normalize_test_refund_event(event)
    assert result[field + '_id'] == prefix + '_expanded'
    assert 'PRIVATE' not in json.dumps(result)
    assert event == before


def test_generic_readonly_mapping_input_and_output_independence(event):
    event['data']['object'] = MappingProxyType(event['data']['object'])
    event['data'] = MappingProxyType(event['data'])
    result = normalize_test_refund_event(MappingProxyType(event))
    result['amount_cents'] = 5
    assert event['data']['object']['amount'] == 1200


@pytest.mark.parametrize('value', [None, [], 1, True, 'PRIVATE'])
def test_parent_must_be_mapping(value):
    refuse(value)


@pytest.mark.parametrize('field,value', [
    ('object', None), ('object', 'refund'), ('object', []),
    ('livemode', None), ('livemode', True), ('livemode', 0), ('livemode', 'false'),
    ('id', None), ('id', 'evt_'), ('id', 'evt_live\n'), ('id', 're_wrong'),
    ('id', 'evt_é'), ('id', 'evt_' + 'a' * 241),
    ('type', None), ('type', []), ('type', 'refund.succeeded'), ('type', 'charge.updated'),
    ('created', None), ('created', 0), ('created', -1), ('created', True), ('created', 1.0), ('created', '1'),
    ('data', None), ('data', []), ('data', {'object': None}), ('data', {'object': []}),
])
def test_parent_rejections_are_fixed_and_redacted(event, field, value):
    event[field] = value
    refuse(event)


@pytest.mark.parametrize('field', ['object', 'livemode', 'id', 'type', 'created', 'data'])
def test_missing_parent_fields_refused(event, field):
    event.pop(field)
    refuse(event)


@pytest.mark.parametrize('field,value', [
    ('object', None), ('object', 'charge'), ('object', []),
    ('id', None), ('id', 're_'), ('id', 're_bad\n'), ('id', 're_é'), ('id', 're_' + 'a' * 241),
    ('amount', 0), ('amount', -1), ('amount', True), ('amount', False), ('amount', None),
    ('amount', 1.0), ('amount', '100'), ('amount', 100_000_000),
    ('currency', None), ('currency', 'EUR'), ('currency', 'eu'), ('currency', 'eur\n'), ('currency', 'éur'),
    ('status', ''), ('status', 'success'), ('status', 'cancelled'), ('status', True), ('status', []),
    ('livemode', True), ('livemode', 0), ('livemode', None), ('livemode', 'false'),
])
def test_refund_resource_rejections(event, field, value):
    event['data']['object'][field] = value
    refuse(event)


@pytest.mark.parametrize('field', ['object', 'id', 'amount', 'currency', 'status'])
def test_missing_required_refund_fields_refused(event, field):
    event['data']['object'].pop(field)
    refuse(event)


@pytest.mark.parametrize('field,prefix,kind', [('payment_intent', 'pi', 'payment_intent'), ('charge', 'ch', 'charge')])
@pytest.mark.parametrize('value', [
    '', 'bad', True, [], 123, {'id': 'PREFIX_valid'},
    {'id': 'PREFIX_valid', 'object': 'wrong'},
    {'id': 'PREFIX_valid', 'object': 'KIND', 'livemode': True},
    {'id': 'PREFIX_valid', 'object': 'KIND', 'livemode': 0},
    {'id': None, 'object': 'KIND'}, {'id': 'PREFIX_é', 'object': 'KIND'},
])
def test_invalid_or_live_expanded_references_refused(event, field, prefix, kind, value):
    if isinstance(value, dict):
        value = {key: (raw.replace('PREFIX', prefix).replace('KIND', kind) if isinstance(raw, str) else raw)
                 for key, raw in value.items()}
    event['data']['object'][field] = value
    refuse(event)


@pytest.mark.parametrize('field,value', [
    ('object', 'refund'), ('id', 're_wrong'), ('id', 'ch_'), ('id', None),
    ('amount_refunded', -1), ('amount_refunded', True), ('amount_refunded', None),
    ('amount_refunded', '1'), ('amount_refunded', 1.5), ('amount_refunded', 100_000_000),
    ('currency', 'EUR'), ('payment_intent', {'id': 'pi_valid', 'object': 'charge'}),
    ('livemode', True),
])
def test_charge_resource_rejections(event, field, value):
    event['type'] = 'charge.refunded'
    event['data']['object'] = {'object': 'charge', 'id': 'ch_synthetic_1',
                              'amount_refunded': 0, 'currency': 'eur'}
    event['data']['object'][field] = value
    refuse(event)


@pytest.mark.parametrize('amount', [1, 99_999_999])
@pytest.mark.parametrize('currency', ['eur', 'usd', 'gbp', 'cny', 'zzz'])
def test_supported_schema_bounds_without_currency_or_exchange_inference(event, amount, currency):
    event['id'] = 'evt_' + 'a' * 240
    event['data']['object'].update(id='re_' + 'a' * 240, amount=amount, currency=currency, livemode=False)
    result = normalize_test_refund_event(event)
    assert result['amount_cents'] == amount
    assert result['currency'] == currency


def test_no_status_inferred_from_refund_failed_event_type(event):
    event['type'] = 'refund.failed'
    event['data']['object']['status'] = None
    assert normalize_test_refund_event(event)['refund_status'] is None


def test_event_timestamp_is_not_current_time_or_ordering_gate(event):
    for created in (1, 99_999_999_999_999):
        event['created'] = created
        assert normalize_test_refund_event(event)['event_created'] == created
