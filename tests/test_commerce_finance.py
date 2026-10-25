"""Synthetic arithmetic only: these fixtures prove no real product or tariff."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.commerce_finance import FinanceInput, analyze_finance, group_from_evaluation
from app.commerce_pricing import quote_offer
from tests.test_commerce_pricing import case  # reuse the immutable quote contract fixture


def fact(value, provenance='CONFIRMED'):
    return {'value': value, 'provenance': provenance, 'reference': 'fixture:document'}


@pytest.fixture
def financial(case):
    evaluation = quote_offer(**case)
    group = group_from_evaluation('fixture-group', evaluation, provenance='CONFIRMED')
    return {
        'groups': [group.model_dump()],
        'payment_fixed_gross_cents': fact(25),
        'payment_variable_bps': fact(150),
        'payment_fee_base': 'GROSS_CHARGED',
        'payment_recoverable_tax_cents': fact(0),
        'extra_costs': [{'cost_id': 'fulfillment-not-in-landed', 'currency': 'EUR',
                         'gross_cents': fact(120), 'recoverable_tax_cents': fact(20),
                         'scope': 'additional_order_cost_not_in_landed'}],
        'extra_costs_complete': 'CONFIRMED', 'extra_costs_reference': 'fixture:exhaustive',
        'return_probability_bps': fact(500), 'return_loss_per_unit_net_cents': fact(10000),
        'return_loss_basis': 'incremental_including_revenue_reversal_net_of_recoveries_excluding_landed',
        'fixed_costs_period_net_cents': fact(100000), 'fixed_costs_period': 'fixture month',
        'cash_outlay_gross_cents': fact(15000),
        'outlay_precedes_customer_funds': True, 'cash_timing_reference': 'fixture:timing',
        'cash_timing_provenance': 'CONFIRMED',
        'scenarios': [
            {'name': 'PESSIMISTIC', 'reference': 'hypothesis:cost+20% returns10%',
             'landed_cost_change_bps': 2000, 'other_variable_cost_change_bps': 1000,
             'return_probability_bps': 1000, 'orders_in_period': 10},
            {'name': 'REALISTIC', 'reference': 'hypothesis:unchanged',
             'landed_cost_change_bps': 0, 'other_variable_cost_change_bps': 0,
             'return_probability_bps': 500, 'orders_in_period': 20},
            {'name': 'OPTIMISTIC', 'reference': 'hypothesis:cost-10% returns2%',
             'landed_cost_change_bps': -1000, 'other_variable_cost_change_bps': 0,
             'return_probability_bps': 200, 'orders_in_period': 30},
        ],
    }


def test_complete_analysis_reuses_quote_without_double_counting_or_mutation(financial):
    before = deepcopy(financial)
    result = analyze_finance(financial)
    assert financial == before
    assert result['status'] == 'CONFIRMED_ANALYSIS'
    row = result['baseline']
    assert row['source_components']['acquisition_net_cents'] == 10000
    assert row['source_components']['shipping_net_cents'] == 1000
    assert row['landed_cost_cents'] == 11100
    assert row['payment_fee_gross_cents'] == 394  # 25 + 24600*1.5%, once
    assert row['other_variable_costs_net_cents'] == 100
    assert row['expected_return_loss_net_cents'] == 1000  # 2 units * 5% *100 EUR
    assert row['full_variable_cost_net_cents'] == 12594
    assert row['contribution_margin_cents'] == 7906
    assert row['average_contribution_per_unit_cents'] == '3953.00'
    assert row['margin_on_net_sales_bps'] == 3857
    assert result['break_even_orders'] == 13
    assert result['cash_bridge_cents'] == 15000
    assert result['commercial_approval'] is False
    assert 'not_net_profit' in result['scope']


def test_three_scenarios_are_always_hypotheses_not_source_rewrites(financial):
    result = analyze_finance(financial)
    pessimistic, realistic, optimistic = result['scenarios']
    assert pessimistic['status'] == realistic['status'] == optimistic['status'] == 'HYPOTHETICAL'
    assert pessimistic['landed_cost_cents'] == 13320
    assert pessimistic['other_variable_costs_net_cents'] == 110
    assert pessimistic['expected_return_loss_net_cents'] == 2000
    assert pessimistic['contribution_margin_cents'] == 4676
    assert realistic['contribution_margin_cents'] == 7906
    assert optimistic['contribution_margin_cents'] == 9616
    assert pessimistic['period_contribution_less_known_fixed_costs_cents'] == -53240
    assert all(row['revenue_gross_cents'] == 24600 for row in result['scenarios'])


def test_multigroup_shipping_per_group_payment_fixed_once(financial):
    group2 = deepcopy(financial['groups'][0])
    group2.update(group_id='group2', variant_id='variant2', offer_id='offer2', shipping_rate_id='rate2')
    financial['groups'].append(group2)
    financial['return_profile_scope'] = 'UNIFORM_ACROSS_ALL_GROUP_UNITS'
    financial['cash_outlay_gross_cents'] = fact(30000)
    row = analyze_finance(financial)['baseline']
    assert row['landed_cost_cents'] == 22200
    assert row['source_components']['shipping_net_cents'] == 2000
    assert row['payment_fee_gross_cents'] == 763  # not 2*394
    assert row['other_variable_costs_net_cents'] == 100  # whole order, not per group
    assert row['expected_return_loss_net_cents'] == 2000
    assert row['per_product_contribution_after_order_adjustments'] is None
    assert len(row['groups_before_order_adjustments']) == 2


@pytest.mark.parametrize('field', [
    'payment_fixed_gross_cents', 'payment_variable_bps', 'payment_recoverable_tax_cents',
    'return_probability_bps', 'return_loss_per_unit_net_cents',
])
def test_required_unknown_is_not_free(financial, field):
    financial.pop(field)
    result = analyze_finance(financial)
    assert result['status'] == 'BLOCKED'
    assert f'{field}:unknown' in result['reasons']
    assert result['baseline'] is None and result['scenarios'] == []


@pytest.mark.parametrize('field', [
    'supplier_gross_cents', 'acquisition_net_cents', 'shipping_net_cents',
    'additional_costs_cents', 'landed_cost_cents', 'customer_total_cents',
    'revenue_net_cents', 'sales_tax_cents', 'contribution_margin_cents',
])
def test_missing_source_component_stays_blocked(financial, field):
    financial['groups'][0].pop(field)
    result = analyze_finance(financial)
    assert result['status'] == 'BLOCKED'
    assert f'group:fixture-group:{field}:unknown' in result['reasons']


@pytest.mark.parametrize('change,reason', [
    ({'source_status': 'blocked'}, 'group:fixture-group:source_blocked'),
    ({'source_reasons': ['fitment_unknown']}, 'group:fixture-group:source_blocked'),
    ({'provenance': 'UNKNOWN'}, 'group:fixture-group:provenance_unknown'),
])
def test_no_approval_of_blocked_or_unproven_quote(financial, change, reason):
    financial['groups'][0].update(change)
    result = analyze_finance(financial)
    assert result['status'] == 'BLOCKED' and reason in result['reasons']


@pytest.mark.parametrize('field', ['payment_fixed_gross_cents', 'return_probability_bps', 'cash_outlay_gross_cents'])
def test_assumptions_never_confirmed(financial, field):
    financial[field]['provenance'] = 'ASSUMPTION'
    result = analyze_finance(financial)
    assert result['status'] == 'HYPOTHETICAL'
    assert field in result['assumptions']


def test_group_and_complete_list_assumptions_identifiable(financial):
    financial['groups'][0]['provenance'] = 'ASSUMPTION'
    financial['extra_costs_complete'] = 'ASSUMPTION'
    result = analyze_finance(financial)
    assert {'group:fixture-group', 'extra_costs:completeness'} <= set(result['assumptions'])
    assert result['status'] == 'HYPOTHETICAL'


def test_absent_cash_fixed_costs_do_not_fabricate_break_even_or_funding(financial):
    for field in ('cash_outlay_gross_cents', 'cash_timing_reference', 'cash_timing_provenance', 'outlay_precedes_customer_funds',
                  'fixed_costs_period_net_cents', 'fixed_costs_period'):
        financial.pop(field)
    result = analyze_finance(financial)
    assert result['status'] == 'CONFIRMED_ANALYSIS'
    assert result['cash_bridge_cents'] is None and result['break_even_orders'] is None
    assert all(s['period_contribution_less_known_fixed_costs_cents'] is None for s in result['scenarios'])
    assert len(result['optional_unknowns']) == 2


@pytest.mark.parametrize('cash,expected', [(15000, 0), (30000, 5400)])
def test_cash_is_independent_all_in_gross_not_landed_inferred(financial, cash, expected):
    financial['cash_outlay_gross_cents'] = fact(cash)
    financial['outlay_precedes_customer_funds'] = False
    assert analyze_finance(financial)['cash_bridge_cents'] == expected


def test_contradictory_cash_or_payment_tax_rejected(financial):
    financial['cash_outlay_gross_cents'] = fact(100)
    with pytest.raises(ValueError, match='cash outlay'):
        analyze_finance(financial)
    financial['cash_outlay_gross_cents'] = fact(15000)
    financial['payment_recoverable_tax_cents'] = fact(395)
    with pytest.raises(ValueError, match='payment tax'):
        analyze_finance(financial)


def test_explicit_fee_base_and_tax_separation(financial):
    financial['payment_fee_base'] = 'NET_REVENUE'
    financial['payment_recoverable_tax_cents'] = fact(20)
    row = analyze_finance(financial)['baseline']
    assert row['payment_fee_gross_cents'] == 333  # 307.5 rounds HALF_UP
    assert row['payment_fee_net_cents'] == 313
    assert row['sales_tax_cents'] == 4100


def test_negative_contribution_and_zero_fixed_costs(financial):
    financial['return_loss_per_unit_net_cents'] = fact(1000000)
    result = analyze_finance(financial)
    assert result['baseline']['contribution_margin_cents'] < 0
    assert result['break_even_orders'] is None
    assert 'break_even:nonpositive_contribution' in result['optional_unknowns']
    financial['fixed_costs_period_net_cents'] = fact(0)
    assert analyze_finance(financial)['break_even_orders'] == 0


def test_zero_net_revenue_has_no_undefined_margin(financial):
    group = financial['groups'][0]
    group.update(customer_total_cents=0, revenue_net_cents=0, sales_tax_cents=0,
                 contribution_margin_cents=-group['landed_cost_cents'])
    row = analyze_finance(financial)['baseline']
    assert row['margin_on_net_sales_bps'] is None
    assert row['profitable_before_unmodelled_fixed_costs'] is False


def test_empty_extra_costs_requires_explicit_exhaustiveness(financial):
    financial['extra_costs'] = []
    financial['extra_costs_complete'] = 'UNKNOWN'
    result = analyze_finance(financial)
    assert result['baseline'] is None and 'extra_costs:completeness_unknown' in result['reasons']
    financial['extra_costs_complete'] = 'CONFIRMED'
    assert analyze_finance(financial)['baseline']['other_variable_costs_net_cents'] == 0


@pytest.mark.parametrize('field', ['payment_fee_base', 'return_loss_basis'])
def test_missing_bases_block(financial, field):
    financial.pop(field)
    assert f'{field}:unknown' in analyze_finance(financial)['reasons']


@pytest.mark.parametrize('path,value', [
    (('payment_fixed_gross_cents', 'value'), True),
    (('payment_fixed_gross_cents', 'value'), '25'),
    (('payment_fixed_gross_cents', 'value'), 25.0),
    (('payment_fixed_gross_cents', 'value'), -1),
    (('payment_fixed_gross_cents', 'value'), 2_000_000_001),
    (('payment_variable_bps', 'value'), 10001),
    (('return_probability_bps', 'value'), -1),
    (('return_probability_bps', 'value'), True),
    (('payment_fixed_gross_cents', 'reference'), ''),
    (('payment_fixed_gross_cents', 'provenance'), 'probably'),
])
def test_bounded_strict_evidence(financial, path, value):
    financial[path[0]][path[1]] = value
    with pytest.raises(ValidationError):
        analyze_finance(financial)


@pytest.mark.parametrize('field,value', [('currency', 'USD'), ('quantity', True), ('quantity', 0),
                                        ('quantity', 2001), ('landed_cost_cents', -1),
                                        ('landed_cost_cents', 11101), ('sales_tax_cents', 4101),
                                        ('contribution_margin_cents', 9401), ('acquisition_net_cents', 12001)])
def test_group_ambiguities_and_contradictions_rejected(financial, field, value):
    financial['groups'][0][field] = value
    with pytest.raises(ValidationError):
        analyze_finance(financial)


@pytest.mark.parametrize('mode', ['group_id', 'triple', 'cost', 'scenario'])
def test_duplicate_ids_reject_double_counting(financial, mode):
    if mode in {'group_id', 'triple'}:
        second = deepcopy(financial['groups'][0])
        if mode == 'triple':
            second['group_id'] = 'other'
        financial['groups'].append(second)
    elif mode == 'cost':
        financial['extra_costs'].append(deepcopy(financial['extra_costs'][0]))
    else:
        financial['scenarios'][1]['name'] = 'PESSIMISTIC'
    with pytest.raises(ValidationError):
        analyze_finance(financial)


@pytest.mark.parametrize('change', [
    {'payment_fixed_gross_cents': {'value': 0, 'provenance': 'UNKNOWN'}},
    {'payment_fixed_gross_cents': {'provenance': 'CONFIRMED', 'reference': 'source'}},
    {'extra_costs_reference': None}, {'fixed_costs_period': None}, {'cash_timing_reference': None},
    {'scenarios': []}, {'unexpected': 1},
])
def test_incomplete_evidence_or_model_rejected(financial, change):
    financial.update(change)
    with pytest.raises(ValidationError):
        analyze_finance(financial)


def test_extra_tax_and_missing_breakdown(financial):
    financial['extra_costs'][0]['recoverable_tax_cents'] = fact(121)
    with pytest.raises(ValidationError):
        analyze_finance(financial)
    financial['extra_costs'][0].pop('recoverable_tax_cents')
    assert 'extra:fulfillment-not-in-landed:recoverable_tax:unknown' in analyze_finance(financial)['reasons']


def test_decimal_rounding_single_final_expected_return(financial):
    financial['return_probability_bps'] = fact(2500)
    financial['return_loss_per_unit_net_cents'] = fact(1)
    assert analyze_finance(financial)['baseline']['expected_return_loss_net_cents'] == 1  # 2*.25*1


def test_model_can_be_reused_and_does_not_mutate_historical_quote(financial):
    model = FinanceInput.model_validate(financial)
    first = analyze_finance(model)
    financial['groups'][0]['landed_cost_cents'] = 999999  # caller later modifies another input
    assert analyze_finance(model) == first
    assert model.groups[0].landed_cost_cents == 11100


def test_different_products_cannot_silently_share_one_return_profile(financial):
    second = deepcopy(financial['groups'][0])
    second.update(group_id='other', variant_id='other', offer_id='other', shipping_rate_id='other')
    financial['groups'].append(second)
    result = analyze_finance(financial)
    assert result['status'] == 'BLOCKED'
    assert 'multi_group_return_profile:unconfirmed_uniformity' in result['reasons']


def test_cash_timing_must_be_known_not_merely_a_boolean(financial):
    financial.pop('cash_timing_provenance')
    result = analyze_finance(financial)
    assert result['cash_bridge_cents'] is None
    assert 'cash_outlay_or_timing:unknown' in result['optional_unknowns']
    financial['cash_timing_provenance'] = 'ASSUMPTION'
    result = analyze_finance(financial)
    assert result['status'] == 'HYPOTHETICAL'
    assert 'cash_timing' in result['assumptions']
    assert result['cash_bridge_cents'] == 15000


def test_already_constructed_model_is_revalidated_at_analysis_boundary(financial):
    model = FinanceInput.model_validate(financial)
    invalid_group = model.groups[0].model_copy(update={'quantity': 0})
    model.groups[0] = invalid_group  # nested containers are mutable in Python
    with pytest.raises(ValidationError):
        analyze_finance(model)


def test_finance_model_attributes_are_frozen(financial):
    model = FinanceInput.model_validate(financial)
    with pytest.raises(ValidationError):
        model.groups[0].quantity = 0
