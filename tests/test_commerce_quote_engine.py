"""Entirely synthetic RPC rows. No actual product/supplier validation or network."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.commerce_quote_engine import CartQuoteError, build_cart_quote

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=2)).isoformat()
def uid(number):
    return str(UUID(int=number))

CART, LINE, PRODUCT, VARIANT, OFFER, RATE, SUPPLIER, AGENT, PROFILE, RULE, BRAND, MODEL, GENERATION = [uid(n) for n in range(1, 14)]


@pytest.fixture
def context():
    return {
        'cart': {'id': CART, 'currency': 'EUR'}, 'country': 'FR', 'postal_code': '75001', 'mode': 'tracked',
        'cart_items': [{'id': LINE, 'cart_id': CART, 'product_id': PRODUCT, 'variant_id': VARIANT, 'quantity': 2,
                        'selected_vehicle': {'brand_slug': 'bmw', 'model': 'Fixture 3', 'chassis': 'F30', 'year': 2016,
                                             'facelift': 'lci', 'body_type': 'Berline', 'trim': 'M Sport', 'has_camera': False}}],
        'products': [{'id': PRODUCT, 'name': 'Synthetic fixture', 'slug': 'synthetic-fixture', 'status': 'active', 'is_verified': True, 'currency': 'EUR'}],
        'product_images': [{'id': uid(14), 'product_id': PRODUCT, 'url': 'https://images.example.test/fixture.jpg', 'display_order': 0}],
        'image_permissions': [{'product_id': PRODUCT,'image_url':'https://images.example.test/fixture.jpg',
            'state':'verified','commercial_use':True,'derivatives_use':True,'product_match_confirmed':True,
            'marks_clearance':'not_present','countries':['FR'],'valid_until':FUTURE,
            'evidence_ref':'SYNTHETIC IMAGE GRANT ONLY','verified_by':PROFILE,'verified_at':NOW.isoformat()}],
        'variants': [{'id': VARIANT, 'product_id': PRODUCT, 'sku': 'FIXTURE-BLACK', 'name': 'Fixture gloss black',
                      'attributes': {'finish': 'gloss black'}, 'currency': 'EUR', 'price_cents': 12000, 'stock': 100,
                      'status': 'active', 'is_verified': True, 'requires_vehicle': True, 'evidence_ref': 'fixture:variant'}],
        'offers': [{'id': OFFER, 'variant_id': VARIANT, 'supplier_id': SUPPLIER, 'supplier_sku': 'SUPPLIER-FIXTURE',
                    'supplier_variant': 'Gloss black fixture', 'url': 'https://supplier.example.test/item',
                    'verification_state': 'verified', 'evidence_ref': 'fixture:terms', 'is_primary': True,
                    'availability': 'available', 'available_quantity': 100, 'valid_until': FUTURE,
                    'unit_cost_cents': 6000, 'recoverable_tax_cents': 1000, 'currency': 'EUR',
                    'preparation_days_min': 1, 'preparation_days_max': 2, 'responsible_agent_id': AGENT}],
        'rates': [{'id': RATE, 'offer_id': OFFER, 'country': 'FR', 'mode': 'tracked', 'max_quantity': 100,
                   'shipping_cost_cents': 1200, 'shipping_recoverable_tax_cents': 200, 'customer_shipping_cents': 600,
                   'goods_tax_bps': 2000, 'shipping_tax_bps': 2000, 'agent_fee_cents': 100,
                   'import_duty_cents': 0, 'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0,
                   'verification_state': 'verified', 'evidence_ref': 'fixture:shipping', 'valid_until': FUTURE,
                   'delivery_days_min': 3, 'delivery_days_max': 5}],
        'agents': [{'id': AGENT, 'profile_id': PROFILE, 'name': 'Synthetic order operator', 'role': 'orders', 'is_active': True}],
        'suppliers': [{'id': SUPPLIER, 'name': 'Synthetic supplier'}],
        'links': [{'variant_id': VARIANT, 'compatibility_id': RULE}],
        'compatibilities': [{'id': RULE, 'product_id': PRODUCT, 'brand_id': BRAND, 'vehicle_model_id': MODEL,
                             'generation_id': GENERATION, 'chassis': 'F30', 'year_from': 2012, 'year_to': 2018,
                             'body_types': ['Berline'], 'required_trims': ['M Sport'], 'facelift': 'lci',
                             'camera_compatible': False, 'verification_state': 'verified'}],
        'brands': [{'id': BRAND, 'slug': 'bmw'}],
        'models': [{'id': MODEL, 'brand_id': BRAND, 'name': 'Fixture 3'}],
        'generations': [{'id': GENERATION, 'vehicle_model_id': MODEL, 'name': 'F30 phase 2'}],
    }


def rejected(context, code, reasons=()):
    with pytest.raises(CartQuoteError) as error:
        build_cart_quote(context, NOW)
    assert error.value.code == code and error.value.status_code == 409
    assert str(error.value) == code
    assert set(reasons).issubset(error.value.reasons)


def add_variant(context, supplier_id=SUPPLIER):
    variant, offer, rate, line = uid(21), uid(22), uid(23), uid(24)
    context['variants'].append({**deepcopy(context['variants'][0]), 'id': variant, 'sku': 'FIXTURE-SECOND'})
    context['offers'].append({**context['offers'][0], 'id': offer, 'variant_id': variant, 'supplier_id': supplier_id})
    context['rates'].append({**context['rates'][0], 'id': rate, 'offer_id': offer})
    context['links'].append({'variant_id': variant, 'compatibility_id': RULE})
    context['cart_items'].append({**deepcopy(context['cart_items'][0]), 'id': line, 'variant_id': variant})
    return variant, offer, rate


def test_one_supplier_exact_private_snapshots_tax_included_and_context_immutable(context):
    original = deepcopy(context)
    result = build_cart_quote(context, NOW)
    assert result['subtotal_cents'] == 24000 and result['shipping_cents'] == 600
    assert result['total_cents'] == 24600 and result['tax_cents'] == 4100
    assert result['currency'] == 'EUR' and result['valid_until'] == FUTURE
    group = result['groups'][0]
    assert {key: group[key] for key in ('variant_id', 'offer_id', 'shipping_rate_id', 'supplier_id', 'responsible_agent_id')} == {
        'variant_id': VARIANT, 'offer_id': OFFER, 'shipping_rate_id': RATE, 'supplier_id': SUPPLIER, 'responsible_agent_id': AGENT}
    assert group['line_ids'] == [LINE]
    line = group['lines'][0]
    assert line['cart_item_id'] == LINE and line['product_id'] == PRODUCT and line['sku'] == 'FIXTURE-BLACK'
    assert line['unit_amount_cents'] == 12000 and line['compatibility_result']['status'] == 'compatible'
    assert line['selected_vehicle']['has_camera'] is False
    assert line['image_url'] == context['product_images'][0]['url']
    assert group['evaluation']['evidence_refs'] == ['fixture:variant', 'fixture:terms', 'fixture:shipping']
    assert context == original
    line['variant_attributes']['finish'] = 'changed snapshot'
    group['evaluation']['evidence_refs'].append('not a source proof')
    assert context == original


def test_same_variant_two_vehicles_twenty_plus_twenty_uses_aggregate_moq_stock_and_one_shipping(context):
    context['cart_items'][0]['quantity'] = 20
    second = deepcopy(context['cart_items'][0])
    second.update(id=uid(25))
    second['selected_vehicle']['year'] = 2017
    context['cart_items'].append(second)
    context['variants'][0]['stock'] = 40
    context['offers'][0].update(moq=30, available_quantity=40)
    result = build_cart_quote(context, NOW)
    assert len(result['groups']) == 1
    assert result['groups'][0]['evaluation']['quantity'] == 40
    assert result['subtotal_cents'] == 480000 and result['shipping_cents'] == 600
    assert result['total_cents'] == 480600 and result['tax_cents'] == 80100
    assert [line['selected_vehicle']['year'] for line in result['groups'][0]['lines']] == [2016, 2017]
    assert all(line['compatibility_result']['status'] == 'compatible' for line in result['groups'][0]['lines'])
    context['variants'][0]['stock'] = 39
    rejected(context, 'no_valid_offer', ['variant_stock_insufficient'])


def test_second_vehicle_is_checked_independently_not_authorized_by_first(context):
    second = deepcopy(context['cart_items'][0])
    second.update(id=uid(25))
    second['selected_vehicle']['chassis'] = 'G20'
    context['cart_items'].append(second)
    rejected(context, 'no_valid_offer', ['variant_fitment_not_confirmed'])


def test_missing_vehicle_or_unknown_required_option_does_not_authorize(context):
    context['cart_items'][0]['selected_vehicle'] = None
    rejected(context, 'no_valid_offer', ['vehicle_required'])
    context['cart_items'][0]['selected_vehicle'] = {'brand_slug': 'bmw', 'model': 'Fixture 3', 'chassis': 'F30', 'year': 2016}
    rejected(context, 'no_valid_offer', ['variant_fitment_not_confirmed'])


def test_product_rule_not_explicitly_linked_to_variant_cannot_donate_fitment(context):
    context['variants'][0]['compatibility_ids'] = [RULE]  # Not a substitute for the exact raw link table.
    context['links'] = []
    rejected(context, 'no_valid_offer', ['invalid_commerce_record'])


@pytest.mark.parametrize('mutation', ['product', 'brand', 'generation'])
def test_relational_rule_mismatch_cannot_extend_model_or_chassis(context, mutation):
    if mutation == 'product':
        context['compatibilities'][0]['product_id'] = uid(90)
    elif mutation == 'brand':
        context['models'][0]['brand_id'] = uid(90)
    else:
        context['generations'][0]['vehicle_model_id'] = uid(90)
    rejected(context, 'invalid_variant_compatibility')


def test_zero_suppliers_blocks_without_invented_supply_identity(context):
    context['suppliers'] = []
    rejected(context, 'no_valid_offer', ['supplier_missing'])


def test_multiple_suppliers_add_independent_group_totals_and_minimum_validity(context):
    supplier = uid(26)
    context['suppliers'].append({'id': supplier, 'name': 'Other synthetic supplier'})
    add_variant(context, supplier)
    earliest = (NOW + timedelta(hours=1)).isoformat()
    context['rates'][1]['valid_until'] = earliest
    quote = build_cart_quote(context, NOW)
    assert len(quote['groups']) == 2
    assert quote['total_cents'] == 49200 and quote['shipping_cents'] == 1200 and quote['tax_cents'] == 8200
    assert quote['valid_until'] == earliest


def test_two_variants_same_supplier_require_explicit_independent_parcel_policy_on_each_chosen_rate(context):
    add_variant(context)
    rejected(context, 'shipping_consolidation_unconfirmed')
    context['rates'][0]['multi_variant_policy'] = 'independent_parcels'
    rejected(context, 'shipping_consolidation_unconfirmed')
    context['rates'][1]['multi_variant_policy'] = 'independent_parcels'
    assert build_cart_quote(context, NOW)['shipping_cents'] == 1200


def test_ready_primary_is_preferred_then_cheapest_verified_cost_alternative(context):
    alternative = {**context['offers'][0], 'id': uid(30), 'is_primary': False, 'unit_cost_cents': 5500}
    context['offers'].append(alternative)
    context['rates'].append({**context['rates'][0], 'id': uid(31), 'offer_id': uid(30)})
    assert build_cart_quote(context, NOW)['groups'][0]['offer_id'] == OFFER
    context['offers'][0]['availability'] = 'unavailable'
    assert build_cart_quote(context, NOW)['groups'][0]['offer_id'] == uid(30)
    alternative['verification_state'] = 'pending'
    rejected(context, 'no_valid_offer')


@pytest.mark.parametrize('table,field,value,reason', [
    ('offers', 'unit_cost_cents', None, 'supplier_cost_or_tax_basis_unknown'),
    ('offers', 'valid_until', NOW.isoformat(), 'offer_terms_missing_or_expired'),
    ('rates', 'shipping_cost_cents', None, 'logistics_cost_breakdown_incomplete'),
    ('rates', 'goods_tax_bps', None, 'sales_tax_basis_unknown'),
    ('compatibilities', 'verification_state', 'pending', 'variant_fitment_not_confirmed'),
    ('products', 'is_verified', False, 'product_not_verified_active'),
    ('variants', 'is_verified', False, 'unverified_commerce_record'),
    ('variants', 'is_verified', 'true', 'unverified_commerce_record'),
    ('agents', 'is_active', False, 'unverified_commerce_record'),
])
def test_missing_terms_and_false_verification_remain_blocked(context, table, field, value, reason):
    context[table][0][field] = value
    rejected(context, 'no_valid_offer', [reason])


def test_declined_image_is_not_returned_or_replaced_with_an_invented_picture(context):
    denied = 'https://scpautomotive.co.uk/cdn/shop/files/example.jpg'
    context['product_images'].insert(0, {'id': uid(40), 'product_id': PRODUCT, 'url': denied, 'display_order': -1})
    rejected(context, 'image_commercial_rights_unconfirmed')
    context['product_images'] = context['product_images'][:1]
    rejected(context, 'image_commercial_rights_unconfirmed')
    assert context['product_images'][0]['url'] == denied


@pytest.mark.parametrize('field,value',[
    ('state','pending'),('state','refused'),('state','revoked'),('commercial_use',False),
    ('derivatives_use',False),('product_match_confirmed',False),('marks_clearance','unknown'),
    ('countries',['DE']),('evidence_ref',''),('verified_by',None),('verified_at',FUTURE),
    ('valid_until',NOW.isoformat()),('valid_until','bad-date'),
])
def test_image_grant_scope_and_time_never_inferred(context,field,value):
    context['image_permissions'][0][field]=value
    rejected(context,'image_commercial_rights_unconfirmed')


def test_missing_image_or_permission_and_unlicensed_gallery_block(context):
    context['image_permissions']=[]
    rejected(context,'image_commercial_rights_unconfirmed')
    context['product_images']=[]
    rejected(context,'authorized_product_image_required')


def test_non_vehicle_variant_does_not_fabricate_a_positive_vehicle_fitment(context):
    context['variants'][0]['requires_vehicle'] = False
    context['links'] = []
    context['cart_items'][0]['selected_vehicle'] = None
    result = build_cart_quote(context, NOW)
    assert result['groups'][0]['lines'][0]['compatibility_result']['status'] == 'not_required'


@pytest.mark.parametrize('field', ['country', 'postal_code', 'mode'])
def test_missing_destination_blocks_instead_of_guessing(context, field):
    del context[field]
    rejected(context, 'destination_incomplete')


@pytest.mark.parametrize('quantity', [0, 21, '2', True, None])
def test_each_line_keeps_strict_twenty_unit_limit(context, quantity):
    context['cart_items'][0]['quantity'] = quantity
    rejected(context, 'invalid_cart_quantity')


def test_legacy_product_without_confirmed_variant_is_not_fallback_stock(context):
    context['cart_items'][0]['variant_id'] = None
    rejected(context, 'variant_required')


def test_one_hundred_twenty_unit_lines_can_form_a_two_thousand_unit_group(context):
    base = context['cart_items'][0]
    context['cart_items'] = [{**deepcopy(base), 'id': uid(100 + n), 'quantity': 20} for n in range(100)]
    context['variants'][0]['stock'] = 2000
    context['offers'][0].update(available_quantity=2000, moq=2000)
    context['rates'][0]['max_quantity'] = 2000
    quote = build_cart_quote(context, NOW)
    assert quote['groups'][0]['evaluation']['quantity'] == 2000 and quote['shipping_cents'] == 600
    context['cart_items'].append({**deepcopy(base), 'id': uid(500), 'quantity': 1})
    rejected(context, 'cart_too_large')


def test_empty_cart_duplicate_line_and_foreign_cart_have_typed_errors(context):
    broken = deepcopy(context)
    broken['cart_items'] = []
    rejected(broken, 'cart_empty')
    context['cart_items'].append(deepcopy(context['cart_items'][0]))
    rejected(context, 'cart_item_mismatch')
    context['cart_items'] = context['cart_items'][:1]
    context['cart_items'][0]['cart_id'] = uid(90)
    rejected(context, 'cart_item_mismatch')


def test_hydrated_client_labels_are_not_fitment_proofs_and_unknown_fields_are_rejected(context):
    context['cart_items'][0]['selected_vehicle']['compatibility_status'] = 'compatible'
    rejected(context, 'invalid_vehicle')


@pytest.mark.parametrize('table,field,value', [
    ('variants', 'price_cents', 2_000_000_000),
    ('rates', 'customer_shipping_cents', 2_000_000_000),
])
def test_group_amounts_cannot_overflow_sql_integer_safety_limit(context, table, field, value):
    context[table][0][field] = value
    rejected(context, 'quote_amount_out_of_range')


def test_multiple_valid_groups_can_still_exceed_overall_amount_limit(context):
    context['cart_items'][0]['quantity'] = 1
    context['variants'][0]['price_cents'] = 1_200_000_000
    second_supplier = uid(26)
    context['suppliers'].append({'id': second_supplier, 'name': 'Other synthetic supplier'})
    add_variant(context, second_supplier)
    rejected(context, 'quote_amount_out_of_range')


def test_exact_two_billion_total_is_allowed_without_tax_added_twice(context):
    context['cart_items'][0]['quantity'] = 1
    context['variants'][0]['price_cents'] = 1_999_999_400
    quote = build_cart_quote(context, NOW)
    assert quote['total_cents'] == 2_000_000_000
    assert quote['tax_cents'] <= quote['total_cents']


@pytest.mark.parametrize('table', ['offers', 'rates'])
def test_naive_term_expiry_is_not_fresh_verified_evidence(context, table):
    context[table][0]['valid_until'] = '2026-10-25T12:00:00'
    rejected(context, 'no_valid_offer')


def test_naive_clock_is_a_typed_business_error(context):
    with pytest.raises(CartQuoteError) as error:
        build_cart_quote(context, NOW.replace(tzinfo=None))
    assert error.value.code == 'invalid_quote_time'


def test_final_validity_is_timezone_aware_and_earliest_fx_is_retained(context):
    expiry = (NOW + timedelta(hours=1)).isoformat()
    context['offers'][0].update(currency='USD', fx_rate='0.9', fx_evidence_ref='fixture:fx', fx_valid_until=expiry)
    quote = build_cart_quote(context, NOW)
    assert quote['valid_until'] == expiry
    assert datetime.fromisoformat(quote['valid_until']).utcoffset() is not None
    assert 'fixture:fx' in quote['groups'][0]['evaluation']['evidence_refs']


@pytest.mark.parametrize('quantity', [1.0, False])
def test_quantity_float_and_false_are_not_coerced(context, quantity):
    context['cart_items'][0]['quantity'] = quantity
    rejected(context, 'invalid_cart_quantity')


def test_numeric_ids_are_not_coerced_to_uuid_hex_strings(context):
    context['cart_items'][0]['id'] = 10000000000000000000000000000000
    rejected(context, 'invalid_quote_context')


def test_untyped_truthy_requires_vehicle_cannot_bypass_per_vehicle_checks(context):
    context['variants'][0]['requires_vehicle'] = 'false'
    rejected(context, 'invalid_quote_context')


@pytest.mark.parametrize('change', [
    {'chassis': 'F30 + F35'}, {'required_trims': ['Different trim']}, {'facelift': 'pre-lci'},
    {'camera_compatible': True}, {'notes': 'Fixture additional exhaust condition'},
    {'model_name': 'Different model'},
])
def test_raw_rule_dto_mapping_does_not_extend_documented_scope(context, change):
    context['compatibilities'][0].update(change)
    if change == {'camera_compatible': True}:
        context['cart_items'][0]['selected_vehicle']['has_camera'] = None
    rejected(context, 'no_valid_offer', ['variant_fitment_not_confirmed'])


@pytest.mark.parametrize('section', ['cart', 'products', 'variants'])
@pytest.mark.parametrize('currency', ['USD', None, 'missing'])
def test_cart_product_and_variant_must_each_explicitly_confirm_eur(context, section, currency):
    row = context['cart'] if section == 'cart' else context[section][0]
    if currency == 'missing':
        del row['currency']
    else:
        row['currency'] = currency
    rejected(context, 'cart_currency_mismatch')


@pytest.mark.parametrize('expiry', ['2026-10-25T12:00:00', NOW.isoformat(), 'not-a-date'])
def test_final_validity_guard_rejects_naive_expired_or_malformed_evaluation(context, monkeypatch, expiry):
    from app.commerce_pricing import quote_offer as evaluate

    def malformed(**kwargs):
        return {**evaluate(**kwargs), 'valid_until': expiry}

    monkeypatch.setattr('app.commerce_quote_engine.quote_offer', malformed)
    rejected(context, 'invalid_quote_validity')
