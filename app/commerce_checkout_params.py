"""Pure, sandbox-only Checkout parameter construction; NOT a payment workflow.

Inputs must be server-loaded immutable quoted ``orders``/``order_items`` rows and
an attempt persisted elsewhere. The order MUST be enriched by the future service
with ``quote_expires_at`` from its related commerce_quotes.expires_at, not copied
from attempt/request data. This is a proposed input contract, NOT an existing
orders column or implemented join. Required attempt fields: id, order_id,
commerce_quote_id, is_test, currency, total_cents, expires_at (integer epoch),
quote_expires_at (aware datetime/ISO timestamp), integration_identifier and
frontend_origin. ``trusted_origin`` is server configuration, NEVER request data.
``now`` is mandatory and injected: no randomness, clocks, SDK, SQL or network.

The caller must durably retain the complete returned payload AND its idempotency
key before calling Stripe. This builder does not reconcile previous sessions or
authorize another API call, including after Stripe's >=24h idempotency retention.
A retry within the admissible creation window returns identical parameters;
outside that window it fails rather than extending the persisted expiration.

All cent amounts already include tax. Tax is checked as a recorded component,
not added again or independently certified. Adaptive pricing, promotions and
automatic tax are disabled. The conservative supported total is 50..99,999,999
EUR cents (EUR-settled/general non-card documentation); this does not certify
account settlement currency, eligibility or individual payment-method limits.
Those account-specific constraints must be checked by the future adapter.

Country collection restricts the country only: Stripe can collect a DIFFERENT
street/postcode. A signed webhook must compare the complete frozen destination
before fulfillment. This module neither reserves stock nor validates catalogue
products, photo rights, supplier terms, tax registrations or live payments.

Official references checked 2026-10-24:
https://docs.stripe.com/api/checkout/sessions/create.md?query=
  (100 payment lines; 30min..24h expiry; inclusive price/shipping tax behavior;
   fixed_amount shipping; adaptive pricing otherwise inherits dashboard policy)
https://docs.stripe.com/currencies#minimum-and-maximum-charge-amounts
https://docs.stripe.com/api/idempotent_requests
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from ipaddress import ip_address
import re
from urllib.parse import urlsplit
from uuid import UUID

from app.product_image_policy import SCP_HOSTS, permitted_image


MAX_SUPPORTED_TOTAL_CENTS = 99_999_999
MIN_SUPPORTED_TOTAL_CENTS = 50
# Checkout shipping countries from the documented API enum, not shipping proof.
_COUNTRIES = frozenset(('AC AD AE AF AG AI AL AM AO AQ AR AT AU AW AX AZ BA BB BD BE '
    'BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CD CF CG CH CI CK CL CM '
    'CN CO CR CV CW CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FO FR GA '
    'GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HN HR HT HU ID IE IL '
    'IM IN IO IQ IS IT JE JM JO JP KE KG KH KI KM KN KR KW KY KZ LA LB LC LI LK LR '
    'LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX '
    'MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS '
    'PT PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV '
    'SX SZ TA TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG US UY UZ VA VC '
    'VE VG VN VU WF WS XK YE YT ZA ZM ZW').split())
_OVERRIDES = frozenset({'success_url', 'cancel_url', 'return_url', 'line_items',
    'shipping_options', 'shipping_address_collection', 'automatic_tax', 'tax_rates',
    'discounts', 'allow_promotion_codes', 'promotion_code', 'adaptive_pricing',
    'payment_method_types', 'allowed_payment_method_types', 'payment_intent_data'})


class CheckoutParamsError(ValueError):
    """Safe, typed business refusal; contains no private source rows or address."""

    status_code = 409

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise CheckoutParamsError(code)


def _uuid(value):
    if not isinstance(value, (str, UUID)):
        _fail('invalid_checkout_identity')
    try:
        result = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        _fail('invalid_checkout_identity')
    if not result.int:
        _fail('invalid_checkout_identity')
    return str(result)


def _int(value, minimum=0, maximum=MAX_SUPPORTED_TOTAL_CENTS):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('invalid_checkout_integer')
    return value


def _aware(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
            _fail('invalid_checkout_timestamp')
        return result
    except (ValueError, TypeError, OverflowError):
        _fail('invalid_checkout_timestamp')


def _origin(value):
    if not isinstance(value, str) or not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
        _fail('invalid_checkout_origin')
    try:
        parsed = urlsplit(value)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        _fail('invalid_checkout_origin')
    if (not host or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or parsed.scheme not in ('http', 'https') or '\\' in value or '%' in value):
        _fail('invalid_checkout_origin')
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    loopback = host == 'localhost' or (address is not None and address.is_loopback)
    if not loopback:
        if parsed.scheme != 'https' or (address is not None and not address.is_global):
            _fail('invalid_checkout_origin')
        if address is None and ('.' not in host or host.endswith(('.local', '.localhost', '.internal'))
                or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
                           for part in host.split('.'))):
            _fail('invalid_checkout_origin')
    if port is not None and not 1 <= port <= 65535:
        _fail('invalid_checkout_origin')
    authority = '[' + host + ']' if ':' in host else host
    if port is not None:
        authority += ':' + str(port)
    return parsed.scheme + '://' + authority


def _image(value):
    if value is None:
        return None
    if (not isinstance(value, str) or not value or not value.isascii()
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail('invalid_checkout_image')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or '\\' in value):
            _fail('invalid_checkout_image')
        # Validate authority without changing the original path, query or URL.
        _origin('https://' + parsed.netloc)
        host = parsed.hostname
        if host == 'localhost' or host.endswith(('.localhost', '.invalid', '.test')):
            _fail('invalid_checkout_image')
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            _fail('invalid_checkout_image')
    except (ValueError, TypeError):
        _fail('invalid_checkout_image')
    if host in SCP_HOSTS or permitted_image(value) != value:
        _fail('checkout_image_use_denied')
    return value


def build_checkout_params(order: Mapping, items: Sequence, attempt: Mapping, *,
                          trusted_origin: str, now: datetime) -> dict:
    """Return only Stripe create-session params, never SDK options or a session.

    Required item fields match persisted quoted order_items: id, order_id,
    product_id, variant_id, source_cart_item_id, currency, product_name, quantity,
    unit_amount_cents. Local cart policy bounds each quantity to 20 (not a claimed
    Stripe API maximum). Product names have a local sanity cap of 250 characters,
    not a claimed SDK maximum. Items are sorted by UUID for a stable retry payload.
    A present image_url must pass HTTPS/public-authority and known-denial checks;
    it is forwarded EXACTLY, never rewritten. This is not a rights licence or DNS
    lookup: the future service must load authorized server-side image snapshots.
    The future adapter must check now again immediately before first creation;
    this pure check makes no promise about network transit time.
    """
    if not isinstance(order, Mapping) or not isinstance(attempt, Mapping):
        _fail('invalid_checkout_snapshot')
    if any(_OVERRIDES.intersection(row) for row in (order, attempt)):
        _fail('unsupported_checkout_override')
    if order.get('is_test') is not True or attempt.get('is_test') is not True:
        _fail('live_checkout_disabled')
    order_id, quote_id, attempt_id = _uuid(order.get('id')), _uuid(order.get('commerce_quote_id')), _uuid(attempt.get('id'))
    if _uuid(attempt.get('order_id')) != order_id or _uuid(attempt.get('commerce_quote_id')) != quote_id:
        _fail('checkout_attempt_mismatch')
    if order.get('status') != 'pending' or order.get('payment_status') != 'unpaid':
        _fail('checkout_order_not_pending')
    if order.get('currency') != 'EUR' or attempt.get('currency') != 'EUR':
        _fail('unsupported_checkout_currency')
    if order.get('promotion_id') is not None or _int(order.get('discount_amount_cents', 0)) != 0:
        _fail('checkout_promotion_not_supported')
    subtotal = _int(order.get('subtotal_cents'))
    shipping = _int(order.get('shipping_amount_cents'))
    tax = _int(order.get('tax_amount_cents'))
    total = _int(order.get('total_cents'), MIN_SUPPORTED_TOTAL_CENTS)
    if subtotal + shipping != total or tax > total or _int(attempt.get('total_cents')) != total:
        _fail('checkout_amount_mismatch')
    origin = _origin(trusted_origin)
    if _origin(attempt.get('frontend_origin')) != origin:
        _fail('checkout_origin_mismatch')
    identifier = attempt.get('integration_identifier')
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+_[A-Za-z]{8}', identifier) or len(identifier) > 200:
        _fail('invalid_integration_identifier')
    expires = _int(attempt.get('expires_at'), 1, 253402300799)
    remaining = expires - _aware(now).timestamp()
    if not 1800 <= remaining <= 86400:
        _fail('checkout_expiration_out_of_window')
    quote_expiration = _aware(order.get('quote_expires_at')).timestamp()
    if _aware(attempt.get('quote_expires_at')).timestamp() != quote_expiration:
        _fail('checkout_attempt_mismatch')
    if expires > quote_expiration:
        _fail('checkout_expiration_exceeds_quote')
    destination = order.get('shipping_address')
    if (not isinstance(destination, Mapping) or not isinstance(destination.get('country'), str)
            or destination['country'] not in _COUNTRIES):
        _fail('invalid_checkout_destination')
    for field in ('name', 'line1', 'city', 'postal_code'):
        value = destination.get(field)
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            _fail('invalid_checkout_destination')
    if not isinstance(items, (list, tuple)) or not 1 <= len(items) <= 100:
        _fail('checkout_line_limit')
    lines, ids, source_ids = [], set(), set()
    goods_total = 0
    for item in items:
        if not isinstance(item, Mapping):
            _fail('invalid_checkout_item')
        if _OVERRIDES.intersection(item):
            _fail('unsupported_checkout_override')
        item_id, source_id = _uuid(item.get('id')), _uuid(item.get('source_cart_item_id'))
        if item_id in ids or source_id in source_ids:
            _fail('duplicate_checkout_item')
        ids.add(item_id)
        source_ids.add(source_id)
        if _uuid(item.get('order_id')) != order_id:
            _fail('checkout_item_order_mismatch')
        product_id, variant_id = _uuid(item.get('product_id')), _uuid(item.get('variant_id'))
        if item.get('currency') != 'EUR':
            _fail('unsupported_checkout_currency')
        quantity, unit = _int(item.get('quantity'), 1, 20), _int(item.get('unit_amount_cents'))
        name = item.get('product_name')
        if not isinstance(name, str) or not name.strip() or len(name) > 250 or any(ord(c) < 32 or ord(c) == 127 for c in name):
            _fail('invalid_checkout_product_name')
        goods_total += quantity * unit
        product_data = {'name': name, 'metadata': {
            'product_id': product_id, 'variant_id': variant_id, 'order_item_id': item_id}}
        image = _image(item.get('image_url'))
        if image is not None:
            product_data['images'] = [image]
        lines.append((item_id, {'quantity': quantity, 'price_data': {
            'currency': 'eur', 'unit_amount': unit, 'tax_behavior': 'inclusive',
            'product_data': product_data}}))
    if goods_total != subtotal:
        _fail('checkout_amount_mismatch')
    metadata = {'order_id': order_id, 'quote_id': quote_id, 'attempt_id': attempt_id}
    return {
        'mode': 'payment', 'client_reference_id': order_id,
        'metadata': dict(metadata), 'payment_intent_data': {'metadata': dict(metadata)},
        'line_items': [line for _, line in sorted(lines)],
        'shipping_options': [{'shipping_rate_data': {
            'type': 'fixed_amount', 'fixed_amount': {'amount': shipping, 'currency': 'eur'},
            'display_name': 'Livraison', 'tax_behavior': 'inclusive'}}],
        'shipping_address_collection': {'allowed_countries': [destination['country']]},
        'billing_address_collection': 'required', 'automatic_tax': {'enabled': False},
        'adaptive_pricing': {'enabled': False}, 'allow_promotion_codes': False,
        'integration_identifier': identifier, 'expires_at': expires,
        'success_url': origin + '/order-success?session_id={CHECKOUT_SESSION_ID}',
        'cancel_url': origin + '/cart?checkout=cancelled',
    }
