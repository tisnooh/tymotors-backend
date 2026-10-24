"""Synthetic pure session validation; never signature/auth/SQL/Stripe E2E proof."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from app.commerce_checkout_events import CheckoutEventError, validate_checkout_session


@pytest.fixture
def event_context():
    order_id, quote_id, attempt_id = str(uuid4()), str(uuid4()), str(uuid4())
    address = {'line1': '12 Rue de la Paix', 'line2': 'Appartement 3',
               'city': 'Paris', 'state': '', 'postal_code': '75001', 'country': 'FR'}
    order = {'id': order_id, 'commerce_quote_id': quote_id, 'is_test': True,
             'currency': 'EUR', 'subtotal_cents': 10000, 'shipping_amount_cents': 500,
             'tax_amount_cents': 1750, 'total_cents': 10500,
             'shipping_address': {**address, 'name': 'Synthetic recipient'}}
    attempt = {'id': attempt_id, 'order_id': order_id, 'commerce_quote_id': quote_id,
               'is_test': True, 'currency': 'EUR', 'total_cents': 10500,
               'expires_at': 1792845600, 'session_id': 'cs_test_synthetic_session'}
    session = {'object': 'checkout.session', 'id': attempt['session_id'],
               'mode': 'payment', 'livemode': False, 'currency': 'eur',
               'client_reference_id': order_id, 'expires_at': attempt['expires_at'],
               'metadata': {'order_id': order_id, 'quote_id': quote_id, 'attempt_id': attempt_id},
               'amount_subtotal': 10000, 'amount_total': 10500,
               'total_details': {'amount_discount': 0, 'amount_shipping': 500, 'amount_tax': 0},
               'automatic_tax': {'enabled': False}, 'discounts': [],
               'status': 'complete', 'payment_status': 'paid', 'payment_intent': 'pi_synthetic_paid',
               'shipping_details': {'address': deepcopy(address), 'name': 'Synthetic recipient'},
               'customer_details': {'email': 'private@example.test', 'name': 'Private name',
                                    'phone': 'private-phone', 'address': {'line1': 'BILLING ONLY'}}}
    return {'session': session, 'attempt': attempt, 'order': order}


def refuse(event_context, code, **options):
    with pytest.raises(CheckoutEventError) as raised:
        validate_checkout_session(**event_context, **options)
    assert raised.value.code == str(raised.value) == code
    assert raised.value.status_code == 409


def test_paid_session_returns_redacted_financial_and_destination_projection(event_context):
    before = deepcopy(event_context)
    result = validate_checkout_session(**event_context, require_paid=True)
    assert result == {'session_id': event_context['session']['id'],
                      'payment_intent_id': 'pi_synthetic_paid', 'payment_status': 'paid',
                      'amount_total': 10500, 'currency': 'EUR', 'financial_valid': True,
                      'destination_matches': True, 'review_reason': None}
    assert event_context == before
    serialized = json.dumps(result)
    for private in ('private@example.test', 'Private name', 'private-phone', 'Rue de la Paix', '75001'):
        assert private not in serialized


def test_created_sdk_minimal_session_needs_finances_but_no_collected_customer(event_context):
    session = event_context['session']
    session.update(status='open', payment_status='unpaid', payment_intent=None)
    for field in ('shipping_details', 'customer_details'):
        session.pop(field)
    event_context['attempt']['session_id'] = None  # Initial bind will occur elsewhere.
    result = validate_checkout_session(**event_context)
    assert result['financial_valid'] is False
    assert result['destination_matches'] is None and result['review_reason'] is None
    assert result['payment_intent_id'] is None
    refuse(event_context, 'checkout_payment_not_paid', require_paid=True)


def test_async_complete_unpaid_is_not_financial_proof_then_paid_is_checked(event_context):
    event_context['session']['payment_status'] = 'unpaid'
    result = validate_checkout_session(**event_context)
    assert result['financial_valid'] is False and result['destination_matches'] is None
    refuse(event_context, 'checkout_payment_not_paid', require_paid=True)
    event_context['session']['payment_status'] = 'paid'
    assert validate_checkout_session(**event_context, require_paid=True)['financial_valid'] is True


@pytest.mark.parametrize('status', ['open', 'expired'])
def test_unpaid_inspection_never_authorizes_payment(event_context, status):
    event_context['session'].update(status=status, payment_status='unpaid')
    assert validate_checkout_session(**event_context)['financial_valid'] is False
    refuse(event_context, 'checkout_payment_not_paid', require_paid=True)


@pytest.mark.parametrize('key', ['order_id', 'quote_id', 'attempt_id'])
@pytest.mark.parametrize('value', [None, str(uuid4()), True, ''])
def test_cross_order_or_attempt_metadata_is_never_accepted(event_context, key, value):
    event_context['session']['metadata'][key] = value
    refuse(event_context, 'checkout_event_identity_mismatch')


@pytest.mark.parametrize('field', ['order_id', 'commerce_quote_id'])
def test_server_attempt_must_belong_to_loaded_order(event_context, field):
    event_context['attempt'][field] = str(uuid4())
    refuse(event_context, 'checkout_event_identity_mismatch')


@pytest.mark.parametrize('value', [None, True, str(uuid4()), ''])
def test_client_reference_must_match_exact_order(event_context, value):
    event_context['session']['client_reference_id'] = value
    refuse(event_context, 'checkout_event_identity_mismatch')


@pytest.mark.parametrize('value', [None, [], 'not-metadata'])
def test_metadata_mapping_required(event_context, value):
    event_context['session']['metadata'] = value
    refuse(event_context, 'checkout_event_identity_mismatch')


@pytest.mark.parametrize('key', ['id', 'commerce_quote_id'])
@pytest.mark.parametrize('value', [None, True, 'not-uuid'])
def test_no_inferred_order_identity(event_context, key, value):
    event_context['order'][key] = value
    refuse(event_context, 'invalid_checkout_identity')


@pytest.mark.parametrize('value', [True, 0, None, 'false'])
def test_livemode_must_be_explicit_false(event_context, value):
    event_context['session']['livemode'] = value
    refuse(event_context, 'checkout_event_mode_mismatch')


@pytest.mark.parametrize('row', ['order', 'attempt'])
@pytest.mark.parametrize('value', [False, 1, None, 'true'])
def test_server_test_markers_are_both_required(event_context, row, value):
    event_context[row]['is_test'] = value
    refuse(event_context, 'checkout_event_mode_mismatch')


@pytest.mark.parametrize('field,value', [('object', 'payment_intent'), ('object', None),
                                        ('mode', 'subscription'), ('mode', 'setup')])
def test_payment_checkout_object_only(event_context, field, value):
    event_context['session'][field] = value
    refuse(event_context, 'checkout_event_mode_mismatch')


@pytest.mark.parametrize('value', [None, '', 'cs_live_example', 'cs_test_', 'cs_test_bad\n'])
def test_sandbox_session_identifier_required(event_context, value):
    event_context['session']['id'] = value
    refuse(event_context, 'checkout_event_session_mismatch')


def test_bound_session_cannot_be_replaced_even_with_same_metadata(event_context):
    event_context['session']['id'] = 'cs_test_other_session'
    refuse(event_context, 'checkout_event_session_mismatch')


@pytest.mark.parametrize('row', ['session', 'attempt'])
@pytest.mark.parametrize('value', [None, True, 1.0, '1792845600', 1792845601, 0])
def test_persisted_expiration_matches_strict_integer(event_context, row, value):
    event_context[row]['expires_at'] = value
    refuse(event_context, 'checkout_event_expiration_mismatch')


@pytest.mark.parametrize('row,value', [('session', 'EUR'), ('session', 'usd'),
    ('session', None), ('order', 'eur'), ('order', None), ('attempt', 'USD'), ('attempt', None)])
def test_currency_not_inferred_or_converted(event_context, row, value):
    event_context[row]['currency'] = value
    refuse(event_context, 'checkout_event_currency_mismatch')


@pytest.mark.parametrize('field', ['amount_total', 'amount_subtotal'])
@pytest.mark.parametrize('value', [True, None, '10000', 10000.0, -1, 100000000])
def test_provider_money_requires_supported_integer_cents(event_context, field, value):
    event_context['session'][field] = value
    refuse(event_context, 'invalid_checkout_amount')


@pytest.mark.parametrize('field', ['amount_total', 'amount_subtotal'])
def test_provider_totals_must_match_snapshot(event_context, field):
    event_context['session'][field] += 1
    refuse(event_context, 'checkout_event_amount_mismatch')


@pytest.mark.parametrize('field', ['subtotal_cents', 'shipping_amount_cents', 'total_cents', 'tax_amount_cents'])
def test_frozen_order_financial_components_coherent(event_context, field):
    event_context['order'][field] += 1 if field != 'tax_amount_cents' else 20000
    refuse(event_context, 'checkout_event_amount_mismatch')


def test_attempt_frozen_total_must_match(event_context):
    event_context['attempt']['total_cents'] += 1
    refuse(event_context, 'checkout_event_amount_mismatch')


@pytest.mark.parametrize('field', ['amount_discount', 'amount_shipping', 'amount_tax'])
@pytest.mark.parametrize('value', [None, True, '0', 0.0])
def test_total_detail_not_defaulted_or_coerced(event_context, field, value):
    event_context['session']['total_details'][field] = value
    refuse(event_context, 'invalid_checkout_amount')


@pytest.mark.parametrize('field', ['amount_discount', 'amount_shipping', 'amount_tax'])
def test_stripe_tax_or_discount_may_not_change_contract(event_context, field):
    event_context['session']['total_details'][field] += 1
    refuse(event_context, 'checkout_event_amount_mismatch')


@pytest.mark.parametrize('field,value', [('total_details', None), ('automatic_tax', None),
    ('discounts', [{'coupon': 'not-authorized'}]), ('automatic_tax', {'enabled': True}),
    ('automatic_tax', {'enabled': 0}), ('automatic_tax', {})])
def test_missing_or_unsupported_financial_configuration_refused(event_context, field, value):
    event_context['session'][field] = value
    refuse(event_context, 'checkout_event_amount_mismatch')


def test_shipping_cost_if_supplied_must_match_inclusive_fixed_charge(event_context):
    event_context['session']['shipping_cost'] = {'amount_subtotal': 500, 'amount_total': 500, 'amount_tax': 0}
    assert validate_checkout_session(**event_context)['financial_valid'] is True
    event_context['session']['shipping_cost']['amount_total'] = 501
    refuse(event_context, 'checkout_event_amount_mismatch')


def test_zero_no_payment_required_has_a_separate_explicit_complete_path(event_context):
    event_context['order'].update(subtotal_cents=0, shipping_amount_cents=0, tax_amount_cents=0, total_cents=0)
    event_context['attempt']['total_cents'] = 0
    event_context['session'].update(amount_subtotal=0, amount_total=0,
        total_details={'amount_discount': 0, 'amount_shipping': 0, 'amount_tax': 0},
        payment_status='no_payment_required', payment_intent=None)
    result = validate_checkout_session(**event_context, require_paid=True)
    assert result['financial_valid'] is True and result['payment_intent_id'] is None
    assert result['destination_matches'] is True
    event_context['session']['status'] = 'open'
    refuse(event_context, 'checkout_event_state_mismatch')


def test_nonzero_no_payment_required_is_not_paid(event_context):
    event_context['session']['payment_status'] = 'no_payment_required'
    refuse(event_context, 'checkout_payment_not_paid')


@pytest.mark.parametrize('value', [None, '', True, {}, 'pi_bad\n', 'pi with space'])
def test_paid_requires_nonempty_unexpanded_payment_intent_id(event_context, value):
    event_context['session']['payment_intent'] = value
    refuse(event_context, 'invalid_checkout_payment_intent')


def test_optional_bound_payment_intent_is_not_replaceable(event_context):
    event_context['attempt']['payment_intent_id'] = 'pi_other'
    refuse(event_context, 'checkout_event_payment_intent_mismatch')


@pytest.mark.parametrize('field,value', [('status', 'open'), ('status', 'expired'),
    ('status', None), ('status', 'paid'), ('payment_status', 'pending'), ('payment_status', None)])
def test_invalid_paid_state_is_rejected_even_without_require_paid(event_context, field, value):
    event_context['session'][field] = value
    refuse(event_context, 'checkout_event_state_mismatch')


def test_modern_collected_information_address_is_supported_without_legacy(event_context):
    event_context['session']['collected_information'] = {'shipping_details': event_context['session'].pop('shipping_details')}
    assert validate_checkout_session(**event_context, require_paid=True)['destination_matches'] is True


def test_unicode_casefold_whitespace_and_postal_dash_normalization_only(event_context):
    observed = event_context['session']['shipping_details']['address']
    observed.update(line1='  １２  RUE\tDE LA  PAIX ', line2='APPARTEMENT ３',
                    city=' PARIS ', state=None, postal_code='７５‐００１ ', country=' fr ')
    assert validate_checkout_session(**event_context)['destination_matches'] is True


@pytest.mark.parametrize('field,value', [('line1', '14 Rue de la Paix'), ('line2', 'Appartement 4'),
    ('city', 'Lyon'), ('state', 'OTHER'), ('postal_code', '75002'), ('country', 'BE'),
    ('line1', None), ('postal_code', []), ('country', 'FRA'), ('line1', 'Rue\x00Null')])
def test_destination_mismatch_is_review_not_denial_of_payment(event_context, field, value):
    event_context['session']['shipping_details']['address'][field] = value
    result = validate_checkout_session(**event_context, require_paid=True)
    assert result['financial_valid'] is True and result['destination_matches'] is False
    assert result['review_reason'] == 'checkout_destination_mismatch'


@pytest.mark.parametrize('value', [None, {}, [], {'address': None}, {'address': 'not-address'}])
def test_missing_or_malformed_paid_shipping_details_requires_review(event_context, value):
    event_context['session']['shipping_details'] = value
    result = validate_checkout_session(**event_context, require_paid=True)
    assert result['financial_valid'] is True and result['destination_matches'] is False


def test_names_never_replace_street_and_billing_is_not_a_shipping_fallback(event_context):
    session = event_context['session']
    session['shipping_details']['name'] = 'Different recipient name'
    assert validate_checkout_session(**event_context)['destination_matches'] is True
    correct = deepcopy(session['shipping_details']['address'])
    session['shipping_details']['address']['line1'] = session['shipping_details']['name']
    assert validate_checkout_session(**event_context)['destination_matches'] is False
    session['customer_details']['address'] = correct
    del session['shipping_details']
    assert validate_checkout_session(**event_context)['destination_matches'] is False


def test_both_shipping_representations_must_agree_not_choose_a_convenient_one(event_context):
    session = event_context['session']
    session['collected_information'] = {'shipping_details': deepcopy(session['shipping_details'])}
    assert validate_checkout_session(**event_context)['destination_matches'] is True
    session['collected_information']['shipping_details']['address']['postal_code'] = '99999'
    result = validate_checkout_session(**event_context)
    assert result['financial_valid'] is True and result['destination_matches'] is False


def test_missing_optional_line2_and_state_match_only_empty_frozen_values(event_context):
    for row in (event_context['order']['shipping_address'], event_context['session']['shipping_details']['address']):
        row.pop('line2')
        row.pop('state')
    assert validate_checkout_session(**event_context)['destination_matches'] is True


def test_street_abbreviations_are_not_guessed(event_context):
    event_context['session']['shipping_details']['address']['line1'] = '12 R. de la Paix'
    assert validate_checkout_session(**event_context)['destination_matches'] is False


def test_financial_mismatch_is_never_downgraded_to_destination_review(event_context):
    event_context['session']['shipping_details'] = None
    event_context['session']['amount_total'] = 1
    refuse(event_context, 'checkout_event_amount_mismatch', require_paid=True)


def test_repeated_pure_calls_do_not_claim_sql_idempotency_or_stock_effects(event_context):
    event_context['order']['payment_status'] = 'paid'  # An already-recorded order remains inspectable.
    before = deepcopy(event_context)
    assert validate_checkout_session(**event_context) == validate_checkout_session(**event_context)
    assert event_context == before
    # This checks determinism ONLY, not a duplicate event claim or once-only stock.


def test_nullable_initial_provider_amount_is_explicitly_refused_not_paid(event_context):
    event_context['session'].update(status='open', payment_status='unpaid', amount_total=None)
    refuse(event_context, 'invalid_checkout_amount')


@pytest.mark.parametrize('row', ['session', 'order', 'attempt'])
def test_mappings_required(event_context, row):
    event_context[row] = None
    refuse(event_context, 'invalid_checkout_event_context')
