"""Synthetic commerce fixtures only: no real supplier or catalogue validation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.commerce_models import OfferInput, QuoteInput, ShippingRateInput, VariantInput
from app.commerce_pricing import quote_offer, select_offers

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=1)).isoformat()
IDS = [str(UUID(int=n)) for n in range(1, 12)]
PRODUCT, VARIANT, OFFER, RATE, SUPPLIER, AGENT, PROFILE, RULE, OFFER2, RATE2, VARIANT2 = IDS


@pytest.fixture
def case():
    return {
        'variant_row': {'id': VARIANT, 'product_id': PRODUCT, 'sku': 'FIXTURE-BLACK', 'name': 'Fixture black',
                        'price_cents': 12000, 'stock': 10, 'status': 'active', 'is_verified': True,
                        'requires_vehicle': True, 'evidence_ref': 'fixture:variant', 'compatibility_ids': [RULE]},
        'product': {'id': PRODUCT, 'status': 'active', 'is_verified': True,
                    'compatibilities': [{'id': RULE, 'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30',
                                         'year_from': 2012, 'year_to': 2018, 'is_verified': True}]},
        'offer_row': {'id': OFFER, 'variant_id': VARIANT, 'supplier_id': SUPPLIER, 'supplier_sku': 'FIXTURE-SUP-B',
                      'supplier_variant': 'Gloss black', 'url': 'https://supplier.example.test/item',
                      'verification_state': 'verified', 'evidence_ref': 'fixture:terms',
                      'availability': 'available', 'available_quantity': 10, 'valid_until': FUTURE,
                      'unit_cost_cents': 6000, 'recoverable_tax_cents': 1000, 'currency': 'EUR',
                      'preparation_days_min': 1, 'preparation_days_max': 2, 'responsible_agent_id': AGENT},
        'rate_rows': [{'id': RATE, 'offer_id': OFFER, 'country': 'FR', 'mode': 'tracked', 'max_quantity': 5,
                       'shipping_cost_cents': 1200, 'shipping_recoverable_tax_cents': 200, 'customer_shipping_cents': 600,
                       'goods_tax_bps': 2000, 'shipping_tax_bps': 2000,
                       'agent_fee_cents': 100, 'import_duty_cents': 0, 'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0,
                       'verification_state': 'verified', 'evidence_ref': 'fixture:shipping', 'valid_until': FUTURE,
                       'delivery_days_min': 3, 'delivery_days_max': 5}],
        'agent_row': {'id': AGENT, 'profile_id': PROFILE, 'name': 'Fixture order operator', 'role': 'orders', 'is_active': True},
        'request': QuoteInput(variant_id=VARIANT, quantity=2, country='FR', postal_code='75001', mode='tracked',
                              selected_vehicle={'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30', 'year': 2016}),
        'now': NOW,
    }


def test_exact_associations_quote_and_tax_not_counted_twice(case):
    before = deepcopy(case)
    q = quote_offer(**case)
    assert q['status'] == 'ready'
    assert q['supplier_sku'] == 'FIXTURE-SUP-B'
    assert q['supplier_variant'] == 'Gloss black'
    assert q['variant_id'] == VARIANT and q['responsible_agent_id'] == AGENT
    assert q['supplier_gross_cents'] == 12000
    assert q['acquisition_net_cents'] == 10000
    assert q['landed_cost_cents'] == 11100  # shipping once for whole quantity; no supplier tax added again
    assert q['customer_total_cents'] == 24600
    assert q['revenue_net_cents'] == 20500 and q['sales_tax_cents'] == 4100
    assert q['contribution_margin_cents'] == 9400
    assert q['delivery_days_min'] == 4 and q['delivery_days_max'] == 7
    assert 'not_net_profit' in q['margin_basis']
    assert case == before  # source catalogue/offer data not rewritten by evaluation


@pytest.mark.parametrize('section,field,value,reason', [
    ('variant_row', 'product_id', VARIANT2, 'variant_product_mismatch'),
    ('offer_row', 'variant_id', VARIANT2, 'variant_offer_mismatch'),
    ('product', 'status', 'draft', 'product_not_verified_active'),
    ('variant_row', 'stock', 0, 'variant_stock_insufficient'),
    ('offer_row', 'availability', 'unknown', 'supplier_stock_unconfirmed_or_insufficient'),
    ('offer_row', 'availability', 'unavailable', 'supplier_stock_unconfirmed_or_insufficient'),
    ('offer_row', 'available_quantity', None, 'supplier_stock_unconfirmed_or_insufficient'),
    ('offer_row', 'available_quantity', 1, 'supplier_stock_unconfirmed_or_insufficient'),
    ('offer_row', 'verification_state', 'pending', 'offer_unverified'),
    ('offer_row', 'valid_until', None, 'offer_terms_missing_or_expired'),
    ('offer_row', 'valid_until', NOW.isoformat(), 'offer_terms_missing_or_expired'),
    ('offer_row', 'moq', 3, 'minimum_order_quantity'),
    ('offer_row', 'preparation_days_max', None, 'preparation_time_unknown'),
    ('offer_row', 'unit_cost_cents', None, 'supplier_cost_or_tax_basis_unknown'),
    ('offer_row', 'recoverable_tax_cents', None, 'supplier_cost_or_tax_basis_unknown'),
    ('agent_row', 'is_active', False, 'responsible_order_agent_missing_or_inactive'),
    ('agent_row', 'role', 'sourcing', 'responsible_order_agent_missing_or_inactive'),
    ('agent_row', 'id', VARIANT2, 'responsible_order_agent_missing_or_inactive'),
])
def test_incomplete_or_inconsistent_terms_block_without_guessed_amounts(case, section, field, value, reason):
    case[section][field] = value
    q = quote_offer(**case)
    assert q['status'] == 'blocked' and reason in q['reasons']
    assert 'customer_total_cents' not in q


@pytest.mark.parametrize('field', ['shipping_cost_cents', 'shipping_recoverable_tax_cents', 'customer_shipping_cents',
                                  'agent_fee_cents', 'import_duty_cents', 'nonrecoverable_tax_cents', 'other_cost_cents'])
def test_missing_logistics_cost_not_treated_as_zero(case, field):
    case['rate_rows'][0][field] = None
    q = quote_offer(**case)
    assert q['status'] == 'blocked'
    assert 'logistics_cost_breakdown_incomplete' in q['reasons']


@pytest.mark.parametrize('field', ['goods_tax_bps', 'shipping_tax_bps'])
def test_destination_tax_must_be_explicit_even_if_product_has_domestic_rate(case, field):
    case['variant_row']['sale_tax_bps'] = 2000
    case['rate_rows'][0][field] = None
    assert 'sales_tax_basis_unknown' in quote_offer(**case)['reasons']


def test_explicit_zero_exemption_and_shipping_tax_separate(case):
    case['rate_rows'][0]['shipping_tax_bps'] = 0
    assert quote_offer(**case)['revenue_net_cents'] == 20600


@pytest.mark.parametrize('field,value', [('country', 'BE'), ('mode', 'express'), ('max_quantity', 1), ('postal_prefix', '20')])
def test_rate_dimensions_must_match_exactly(case, field, value):
    case['rate_rows'][0][field] = value
    assert 'shipping_rate_missing' in quote_offer(**case)['reasons']


@pytest.mark.parametrize('field,value,reason', [
    ('valid_until', None, 'shipping_terms_unverified_or_expired'),
    ('verification_state', 'pending', 'shipping_terms_unverified_or_expired'),
    ('delivery_days_max', None, 'delivery_time_unknown'),
])
def test_shipping_evidence_and_delivery_time_required(case, field, value, reason):
    case['rate_rows'][0][field] = value
    assert reason in quote_offer(**case)['reasons']


def test_regional_override_and_ambiguity_not_silently_cheapest(case):
    regional = {**case['rate_rows'][0], 'id': RATE2, 'postal_prefix': '75', 'customer_shipping_cents': 900}
    case['rate_rows'].append(regional)
    assert quote_offer(**case)['customer_shipping_cents'] == 900
    case['rate_rows'].append({**regional, 'id': OFFER2, 'customer_shipping_cents': 100})
    assert 'shipping_rate_ambiguous' in quote_offer(**case)['reasons']


def test_unverified_regional_override_cannot_fall_back_to_generic_rule(case):
    case['rate_rows'].append({**case['rate_rows'][0], 'id': RATE2, 'postal_prefix': '75', 'verification_state': 'pending'})
    assert 'shipping_terms_unverified_or_expired' in quote_offer(**case)['reasons']


def test_invalid_regional_restriction_cannot_disappear_behind_generic_rate(case):
    case['rate_rows'].append({**case['rate_rows'][0], 'id': RATE2, 'postal_prefix': '75', 'max_quantity': None})
    result = quote_offer(**case)
    assert result['status'] == 'blocked' and 'shipping_rule_invalid' in result['reasons']
    assert 'customer_total_cents' not in result


def test_broken_unrelated_destination_or_transport_does_not_corrupt_quote(case):
    case['rate_rows'].append({**case['rate_rows'][0], 'id': RATE2, 'country': 'BE', 'max_quantity': None})
    case['rate_rows'].append({**case['rate_rows'][0], 'id': RATE2, 'mode': 'express', 'max_quantity': None})
    assert quote_offer(**case)['status'] == 'ready'


def test_another_offer_cannot_donate_a_shipping_rate(case):
    case['rate_rows'][0]['offer_id'] = OFFER2
    assert 'shipping_rate_missing' in quote_offer(**case)['reasons']


def test_fx_requires_evidence_and_expiry_and_recalculates_no_mutation(case):
    case['offer_row']['currency'] = 'USD'
    assert 'exchange_rate_unconfirmed_or_expired' in quote_offer(**case)['reasons']
    case['offer_row'].update(fx_rate='0.9', fx_evidence_ref='fixture:fx', fx_valid_until=FUTURE)
    old_quote = quote_offer(**case)
    assert old_quote['acquisition_net_cents'] == 9000
    case['offer_row']['unit_cost_cents'] = 7000
    new_quote = quote_offer(**case)
    assert new_quote['acquisition_net_cents'] == 10800
    assert old_quote['acquisition_net_cents'] == 9000
    case['offer_row']['fx_valid_until'] = NOW.isoformat()
    assert 'exchange_rate_unconfirmed_or_expired' in quote_offer(**case)['reasons']


def test_same_currency_has_no_spurious_exchange_gain(case):
    case['offer_row']['fx_rate'] = '0.8'
    assert 'same_currency_exchange_rate_invalid' in quote_offer(**case)['reasons']


@pytest.mark.parametrize('vehicle', [None, {'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'G20', 'year': 2020},
                                     {'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30'}])
def test_missing_or_wrong_vehicle_does_not_authorize_quote(case, vehicle):
    case['request'] = case['request'].model_copy(update={'selected_vehicle': None}) if vehicle is None else QuoteInput(
        **{**case['request'].model_dump(), 'selected_vehicle': vehicle})
    q = quote_offer(**case)
    assert q['status'] == 'blocked'
    assert set(q['reasons']) & {'vehicle_required', 'variant_fitment_not_confirmed'}


def test_other_variant_compatibility_not_inherited(case):
    case['variant_row']['compatibility_ids'] = [VARIANT2]
    assert 'variant_fitment_not_confirmed' in quote_offer(**case)['reasons']


def test_negative_margin_blocks_and_best_offer_only_compares_ready_quotes(case):
    first = quote_offer(**case)
    expensive = deepcopy(case)
    expensive['offer_row'].update(id=OFFER2, unit_cost_cents=50000)
    expensive['rate_rows'][0].update(id=RATE2, offer_id=OFFER2)
    second = quote_offer(**expensive)
    assert second['status'] == 'blocked' and 'negative_contribution_margin' in second['reasons']
    chosen = select_offers([first, second], [case['offer_row'], {**expensive['offer_row'], 'is_primary': True}])
    assert chosen['best_cost_offer_id'] == OFFER and chosen['primary_offer_id'] is None
    assert chosen['alternative_offer_ids'] == [OFFER]


def test_cheapest_available_alternative_need_not_be_the_primary(case):
    first = quote_offer(**case)
    alternate = deepcopy(case)
    alternate['offer_row'].update(id=OFFER2, unit_cost_cents=5500)
    alternate['rate_rows'][0].update(id=RATE2, offer_id=OFFER2)
    second = quote_offer(**alternate)
    selection = select_offers([first, second], [{**case['offer_row'], 'is_primary': True}, alternate['offer_row']])
    assert selection['primary_offer_id'] == OFFER and selection['best_cost_offer_id'] == OFFER2
    assert selection['alternative_offer_ids'] == [OFFER2]


@pytest.mark.parametrize('value', [-1, 1.2, True, '100'])
def test_money_does_not_accept_negative_float_boolean_or_coercion(case, value):
    offer = {key: item for key, item in case['offer_row'].items() if key != 'id'}
    with pytest.raises(ValidationError):
        OfferInput.model_validate({**offer, 'unit_cost_cents': value})


def test_verification_evidence_url_and_recoverable_tax_constraints(case):
    offer = {k: v for k, v in case['offer_row'].items() if k != 'id'}
    for change in ({'evidence_ref': ' '}, {'url': 'https://secret:password@example.test/a'},
                   {'url': 'javascript:bad'}, {'recoverable_tax_cents': 6001}, {'fx_rate': 'NaN'}):
        with pytest.raises(ValidationError):
            OfferInput.model_validate({**offer, **change})
    variant = {k: v for k, v in case['variant_row'].items() if k != 'id'}
    with pytest.raises(ValidationError):
        VariantInput.model_validate({**variant, 'compatibility_ids': []})
    rate = {k: v for k, v in case['rate_rows'][0].items() if k != 'id'}
    with pytest.raises(ValidationError):
        ShippingRateInput.model_validate({**rate, 'shipping_recoverable_tax_cents': 1201})


@pytest.mark.parametrize('postal', ['-', '---', ' - ', ' '])
def test_destination_cannot_be_only_punctuation_or_whitespace(case, postal):
    with pytest.raises(ValidationError):
        QuoteInput.model_validate({**case['request'].model_dump(), 'postal_code': postal})
