"""Synthetic pure builder tests: no Stripe, database, real product or payment."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from app.commerce_checkout_params import (
    CheckoutParamsError, MAX_SUPPORTED_TOTAL_CENTS, build_checkout_params,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
ORIGIN = 'https://shop.example.com'


@pytest.fixture
def snapshot():
    order_id, quote_id = str(uuid4()), str(uuid4())
    limit = (NOW + timedelta(minutes=45)).isoformat()
    order = {
        'id': order_id, 'commerce_quote_id': quote_id, 'is_test': True,
        'status': 'pending', 'payment_status': 'unpaid', 'currency': 'EUR',
        'subtotal_cents': 10000, 'shipping_amount_cents': 500,
        'tax_amount_cents': 1750, 'total_cents': 10500,
        'discount_amount_cents': 0, 'promotion_id': None, 'quote_expires_at': limit,
        'shipping_address': {'name': 'Synthetic customer', 'line1': '1 Test street',
                             'city': 'Paris', 'postal_code': '75001', 'country': 'FR'},
    }
    item = {
        'id': str(uuid4()), 'order_id': order_id, 'product_id': str(uuid4()),
        'variant_id': str(uuid4()), 'source_cart_item_id': str(uuid4()),
        'currency': 'EUR', 'product_name': 'Synthetic test part',
        'quantity': 2, 'unit_amount_cents': 5000,
        'image_url': 'https://cdn.example.com/frozen-photo.jpg?v=original',
        'private_supplier_cost': 123,
    }
    attempt = {
        'id': str(uuid4()), 'order_id': order_id, 'commerce_quote_id': quote_id,
        'is_test': True, 'currency': 'EUR', 'total_cents': 10500,
        'frontend_origin': ORIGIN, 'integration_identifier': 'tymotors_quote_abcdefgh',
        'expires_at': int((NOW + timedelta(minutes=40)).timestamp()),
        'quote_expires_at': limit,
    }
    return {'order': order, 'items': [item], 'attempt': attempt,
            'trusted_origin': ORIGIN, 'now': NOW}


def refuse(snapshot, code):
    with pytest.raises(CheckoutParamsError) as raised:
        build_checkout_params(**snapshot)
    assert raised.value.code == str(raised.value) == code
    assert raised.value.status_code == 409


def test_exact_inclusive_totals_fixed_shipping_and_metadata(snapshot):
    result = build_checkout_params(**snapshot)
    order, attempt = snapshot['order'], snapshot['attempt']
    assert result['mode'] == 'payment'
    assert result['client_reference_id'] == order['id']
    assert result['metadata'] == result['payment_intent_data']['metadata'] == {
        'order_id': order['id'], 'quote_id': order['commerce_quote_id'], 'attempt_id': attempt['id']}
    assert result['line_items'][0]['price_data']['unit_amount'] == 5000
    assert result['line_items'][0]['quantity'] == 2
    rate = result['shipping_options'][0]['shipping_rate_data']
    assert rate == {'type': 'fixed_amount', 'fixed_amount': {'amount': 500, 'currency': 'eur'},
                    'display_name': 'Livraison', 'tax_behavior': 'inclusive'}
    assert result['line_items'][0]['price_data']['tax_behavior'] == 'inclusive'
    assert sum(row['quantity'] * row['price_data']['unit_amount'] for row in result['line_items']) + rate['fixed_amount']['amount'] == order['total_cents']
    assert result['shipping_address_collection'] == {'allowed_countries': ['FR']}
    assert result['automatic_tax'] == result['adaptive_pricing'] == {'enabled': False}
    assert result['allow_promotion_codes'] is False
    assert result['expires_at'] == attempt['expires_at']
    assert result['integration_identifier'] == attempt['integration_identifier']
    assert result['success_url'] == ORIGIN + '/order-success?session_id={CHECKOUT_SESSION_ID}'
    assert result['cancel_url'] == ORIGIN + '/cart?checkout=cancelled'
    for forbidden in ('payment_method_types', 'allowed_payment_method_types', 'discounts', 'tax_rates'):
        assert forbidden not in result
    serialized = json.dumps(result)
    for private in ('private_supplier_cost', '75001', '1 Test street'):
        assert private not in serialized


def test_repeat_retry_later_and_reordered_items_are_identical_and_immutable(snapshot):
    second = deepcopy(snapshot['items'][0])
    second.update(id=str(uuid4()), source_cart_item_id=str(uuid4()))
    snapshot['items'][0]['quantity'] = second['quantity'] = 1
    snapshot['items'].append(second)
    before = deepcopy(snapshot)
    first = build_checkout_params(**snapshot)
    assert snapshot == before
    snapshot['now'] += timedelta(minutes=5)
    snapshot['items'].reverse()
    assert json.dumps(first) == json.dumps(build_checkout_params(**snapshot))
    first['metadata']['order_id'] = 'changed-return-value'
    assert build_checkout_params(**snapshot)['metadata']['order_id'] == snapshot['order']['id']


@pytest.mark.parametrize('row', ['order', 'attempt'])
@pytest.mark.parametrize('value', [False, 1, 'true', None])
def test_test_marker_must_be_explicit_true(snapshot, row, value):
    snapshot[row]['is_test'] = value
    refuse(snapshot, 'live_checkout_disabled')


@pytest.mark.parametrize('field', ['id', 'commerce_quote_id'])
@pytest.mark.parametrize('value', [None, '', True, 'not-a-uuid', str(uuid4()).replace('-', '')[:12]])
def test_invalid_order_identity(snapshot, field, value):
    snapshot['order'][field] = value
    refuse(snapshot, 'invalid_checkout_identity')


@pytest.mark.parametrize('field', ['order_id', 'commerce_quote_id'])
def test_attempt_must_match_order_and_quote(snapshot, field):
    snapshot['attempt'][field] = str(uuid4())
    refuse(snapshot, 'checkout_attempt_mismatch')


@pytest.mark.parametrize('row', ['order', 'attempt', 'item'])
@pytest.mark.parametrize('currency', [None, 'eur', 'USD'])
def test_no_currency_defaults_or_conversion(snapshot, row, currency):
    target = snapshot['items'][0] if row == 'item' else snapshot[row]
    target['currency'] = currency
    refuse(snapshot, 'unsupported_checkout_currency')


@pytest.mark.parametrize('field', ['subtotal_cents', 'shipping_amount_cents', 'tax_amount_cents', 'total_cents'])
@pytest.mark.parametrize('value', [None, True, 1.0, '100', -1, MAX_SUPPORTED_TOTAL_CENTS + 1])
def test_strict_integer_money_and_supported_cap(snapshot, field, value):
    snapshot['order'][field] = value
    refuse(snapshot, 'invalid_checkout_integer')


@pytest.mark.parametrize('value', [0, 1, 49])
def test_below_supported_eur_minimum_explicitly_refused(snapshot, value):
    snapshot['order']['total_cents'] = value
    refuse(snapshot, 'invalid_checkout_integer')


@pytest.mark.parametrize('field', ['subtotal_cents', 'shipping_amount_cents', 'total_cents', 'tax_amount_cents'])
def test_exact_amounts_tax_is_not_extra(snapshot, field):
    snapshot['order'][field] += 1 if field != 'tax_amount_cents' else 20000
    refuse(snapshot, 'checkout_amount_mismatch')


def test_attempt_amount_mismatch(snapshot):
    snapshot['attempt']['total_cents'] += 1
    refuse(snapshot, 'checkout_amount_mismatch')


@pytest.mark.parametrize('quantity', [0, 21, True, '2', 2.0, None])
def test_local_cart_quantity_policy_is_strict(snapshot, quantity):
    snapshot['items'][0]['quantity'] = quantity
    refuse(snapshot, 'invalid_checkout_integer')


@pytest.mark.parametrize('field', ['id', 'source_cart_item_id'])
def test_duplicate_item_or_source_refused(snapshot, field):
    other = deepcopy(snapshot['items'][0])
    other['id'] = str(uuid4())
    other['source_cart_item_id'] = str(uuid4())
    other[field] = snapshot['items'][0][field]
    snapshot['items'].append(other)
    refuse(snapshot, 'duplicate_checkout_item')


def test_item_belongs_to_order_and_variant_is_required(snapshot):
    snapshot['items'][0]['order_id'] = str(uuid4())
    refuse(snapshot, 'checkout_item_order_mismatch')
    snapshot['items'][0]['order_id'] = snapshot['order']['id']
    snapshot['items'][0]['variant_id'] = None
    refuse(snapshot, 'invalid_checkout_identity')


@pytest.mark.parametrize('count', [0, 101])
def test_documented_goods_line_limit(snapshot, count):
    snapshot['items'] *= count
    refuse(snapshot, 'checkout_line_limit')


def test_100_goods_lines_plus_separate_fixed_shipping(snapshot):
    prototype = snapshot['items'][0]
    snapshot['items'] = [{**prototype, 'id': str(uuid4()), 'source_cart_item_id': str(uuid4()),
                          'quantity': 1, 'unit_amount_cents': 100} for _ in range(100)]
    result = build_checkout_params(**snapshot)
    assert len(result['line_items']) == 100
    assert len(result['shipping_options']) == 1


def test_zero_shipping_is_explicit_fixed_rate_not_missing(snapshot):
    snapshot['order'].update(shipping_amount_cents=0, total_cents=10000)
    snapshot['attempt']['total_cents'] = 10000
    result = build_checkout_params(**snapshot)
    assert result['shipping_options'][0]['shipping_rate_data']['fixed_amount']['amount'] == 0


@pytest.mark.parametrize('minutes', [30, 1440])
def test_documented_expiration_boundaries(snapshot, minutes):
    expiration = NOW + timedelta(minutes=minutes)
    snapshot['attempt']['expires_at'] = int(expiration.timestamp())
    snapshot['attempt']['quote_expires_at'] = snapshot['order']['quote_expires_at'] = expiration.isoformat()
    assert build_checkout_params(**snapshot)['expires_at'] == int(expiration.timestamp())


@pytest.mark.parametrize('seconds', [-1, 0, 1799, 86401])
def test_expired_or_out_of_api_window_not_extended(snapshot, seconds):
    snapshot['attempt']['expires_at'] = int(NOW.timestamp()) + seconds
    refuse(snapshot, 'checkout_expiration_out_of_window')


def test_retry_after_window_refused_not_recreated(snapshot):
    snapshot['now'] += timedelta(days=1)
    refuse(snapshot, 'checkout_expiration_out_of_window')


def test_authoritative_quote_expiration_required_and_compared(snapshot):
    del snapshot['order']['quote_expires_at']
    refuse(snapshot, 'invalid_checkout_timestamp')
    snapshot['order']['quote_expires_at'] = (NOW + timedelta(minutes=50)).isoformat()
    refuse(snapshot, 'checkout_attempt_mismatch')
    snapshot['order']['quote_expires_at'] = snapshot['attempt']['quote_expires_at'] = (NOW + timedelta(minutes=35)).isoformat()
    refuse(snapshot, 'checkout_expiration_exceeds_quote')


@pytest.mark.parametrize('value', [None, 'invalid', '2026-10-24T12:45:00', NOW.replace(tzinfo=None)])
def test_aware_timestamps_required(snapshot, value):
    snapshot['order']['quote_expires_at'] = value
    refuse(snapshot, 'invalid_checkout_timestamp')


@pytest.mark.parametrize('origin', ['https://shop.example.com', 'http://localhost:3000',
                                   'http://127.0.0.1:8765', 'http://[::1]:3000'])
def test_https_public_or_test_loopback_origin(snapshot, origin):
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = origin
    assert build_checkout_params(**snapshot)['cancel_url'] == origin + '/cart?checkout=cancelled'


@pytest.mark.parametrize('origin', ['http://shop.example.com', 'javascript:alert(1)',
    'https://user:password@shop.example.com', 'https://shop.example.com/?next=evil',
    'https://shop.example.com/#fragment', 'https://shop.example.com/override',
    'https://shop.example.com\\@evil.com', 'https://10.0.0.1', 'https://169.254.169.254',
    'http://localhost.evil.com', 'https://server.internal', 'https://intranet',
    'https://shop.example.com:99999', 'https://shop.example.com\n', None])
def test_untrusted_or_non_origin_url_rejected(snapshot, origin):
    snapshot['trusted_origin'] = snapshot['attempt']['frontend_origin'] = origin
    refuse(snapshot, 'invalid_checkout_origin')


def test_persisted_origin_cannot_be_reconfigured_on_retry(snapshot):
    snapshot['attempt']['frontend_origin'] = 'https://attacker.example.com'
    refuse(snapshot, 'checkout_origin_mismatch')


@pytest.mark.parametrize('field', ['success_url', 'cancel_url', 'automatic_tax', 'discounts',
    'allow_promotion_codes', 'payment_method_types', 'adaptive_pricing', 'shipping_options'])
def test_no_extra_parameter_overrides(snapshot, field):
    snapshot['attempt'][field] = {'enabled': True}
    refuse(snapshot, 'unsupported_checkout_override')


@pytest.mark.parametrize('identifier', [None, 'tymotors_12345678', 'tymotors_abcdefg',
    'tymotors_abcdefghi', 'tymotors_abcdefgh\n', 'x' * 192 + '_abcdefgh'])
def test_identifier_has_persisted_eight_letter_suffix_and_documented_length(snapshot, identifier):
    snapshot['attempt']['integration_identifier'] = identifier
    refuse(snapshot, 'invalid_integration_identifier')


@pytest.mark.parametrize('country', [None, 'fr', 'ZZ', [], 'USA'])
def test_valid_frozen_country_required(snapshot, country):
    snapshot['order']['shipping_address']['country'] = country
    refuse(snapshot, 'invalid_checkout_destination')


@pytest.mark.parametrize('field', ['name', 'line1', 'city', 'postal_code'])
def test_complete_destination_required_but_not_disclosed_in_metadata(snapshot, field):
    snapshot['order']['shipping_address'][field] = ' '
    refuse(snapshot, 'invalid_checkout_destination')


@pytest.mark.parametrize('field,value', [('status', 'paid'), ('payment_status', 'paid')])
def test_already_paid_order_not_eligible(snapshot, field, value):
    snapshot['order'][field] = value
    refuse(snapshot, 'checkout_order_not_pending')


@pytest.mark.parametrize('field,value', [('promotion_id', str(uuid4())), ('discount_amount_cents', 1)])
def test_promoted_order_requires_a_different_verified_contract(snapshot, field, value):
    snapshot['order'][field] = value
    refuse(snapshot, 'checkout_promotion_not_supported')


def test_min_and_max_supported_total_are_not_reduced_to_eight_digit_card_claim(snapshot):
    for total in (50, MAX_SUPPORTED_TOTAL_CENTS):
        snapshot['items'][0].update(quantity=1, unit_amount_cents=total)
        snapshot['order'].update(subtotal_cents=total, shipping_amount_cents=0,
                                 tax_amount_cents=0, total_cents=total)
        snapshot['attempt']['total_cents'] = total
        assert build_checkout_params(**snapshot)['line_items'][0]['price_data']['unit_amount'] == total


def test_frozen_image_forwarded_exactly_without_replacement_or_transform(snapshot):
    before = deepcopy(snapshot)
    source = 'https://res.cloudinary.com/example/image/upload/v1/authorized-product.webp?original=true'
    snapshot['items'][0]['image_url'] = source
    result = build_checkout_params(**snapshot)
    assert result['line_items'][0]['price_data']['product_data']['images'] == [source]
    assert snapshot['items'][0]['image_url'] == source
    assert snapshot['order'] == before['order'] and snapshot['attempt'] == before['attempt']


@pytest.mark.parametrize('present', [True, False])
def test_missing_or_null_image_is_omitted(snapshot, present):
    if present:
        snapshot['items'][0]['image_url'] = None
    else:
        del snapshot['items'][0]['image_url']
    assert 'images' not in build_checkout_params(**snapshot)['line_items'][0]['price_data']['product_data']


@pytest.mark.parametrize('source', [
    'https://scpautomotive.co.uk/cdn/shop/files/BMW.jpg',
    'https://www.scpautomotive.co.uk/product.jpg',
    'https://res.cloudinary.com/dwsyixjux/image/upload/v1/tymotors/products/hvtqoa2mfv40mn2gy1ww.png',
    'https://res.cloudinary.com/dwsyixjux/image/upload/c_scale,w_40/v1/tymotors/products/ckvfckn89wcdd9fzaegj.webp',
    'https://cdn.shopify.com/s/files/BMW-LED-Door-Projector-_Pair_-BMW-Logo-SCP-Automotive-90141840.jpg',
])
def test_scp_known_denials_are_refused_not_replaced(snapshot, source):
    snapshot['items'][0]['image_url'] = source
    refuse(snapshot, 'checkout_image_use_denied')
    assert snapshot['items'][0]['image_url'] == source


@pytest.mark.parametrize('source', ['', True, [], 'http://cdn.example.com/photo.jpg',
    'https://user:password@cdn.example.com/photo.jpg', 'https://localhost/photo.jpg',
    'https://127.0.0.1/photo.jpg', 'https://192.168.1.2/photo.jpg', 'data:image/png;base64,x',
    'https://cdn.example.com/photo.jpg#fragment', 'https://cdn.example.com/photo.jpg\n',
    'https://cdn.example.com\\@evil.example.com/photo.jpg'])
def test_invalid_or_private_images_refused(snapshot, source):
    snapshot['items'][0]['image_url'] = source
    refuse(snapshot, 'invalid_checkout_image')
