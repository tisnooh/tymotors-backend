"""Pure validation of server-trusted, sandbox Checkout Session mappings.

NO signature verification, actor authorization, SDK, clock, SQL, network, stock,
event journal or fulfillment occurs here. The future caller MUST verify Stripe
signatures (or obtain an authenticated SDK response), load the correct immutable
order/attempt, claim the event transactionally and bind the session atomically.
This validator is not an authentication boundary and does not deduplicate events.

Order inputs: id, commerce_quote_id, is_test=True, currency='EUR', subtotal_cents,
shipping_amount_cents, tax_amount_cents (already INCLUDED), total_cents,
shipping_address. Attempt inputs: id, order_id, commerce_quote_id, is_test=True,
currency='EUR', total_cents, expires_at, optional session_id/payment_intent_id.
Only the future caller may source these records, never request JSON/metadata.

Amounts must be present integer cents; nullable provider amounts are explicitly
refused, not treated as zero. This frozen builder contract disables automatic tax
and discounts: amount_subtotal is the quoted goods amount, amount_shipping is the
quoted port, amount_discount/amount_tax are zero. The quote's own tax component
remains recorded TTC; it is neither added again nor falsely reported as Stripe-
calculated tax. The supported cap matches the current pure Checkout builder.

``financial_valid`` means a coherent paid/complete session (including an explicit
zero/no_payment_required completion), CONDITIONAL on upstream authentication. An
unpaid session can be structurally valid but financial_valid=False. For a paid
session, a missing/divergent/malformed destination returns financial_valid=True,
destination_matches=False and checkout_destination_mismatch: record the financial
truth, but HOLD fulfillment for review. It is not a payment-validation exception.

Address matching is conservative Unicode NFKC + casefold + whitespace collapse;
postcodes additionally ignore spaces and Unicode dash punctuation. No geocoding,
abbreviation expansion, transliteration, address inference, name-as-street or
billing-address fallback. Names/contact data are not needed or returned. When
both old/new shipping fields are populated, BOTH must match the frozen address.

No current-time expiry check: asynchronous funds can arrive after session expiry.
Persisted expires_at must still match exactly. Replay/parallel-event handling,
after-24h recovery, stock and the one-order-per-quote invariant belong in SQL.

Official docs checked 2026-10-24:
https://docs.stripe.com/api/checkout/sessions/object.md?query=
https://docs.stripe.com/checkout/fulfillment
https://docs.stripe.com/webhooks
"""
from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from uuid import UUID


_MAX_CENTS = 99_999_999  # Supported builder policy, NOT a universal Stripe limit.


class CheckoutEventError(ValueError):
    """Safe business code; never includes provider data, secrets or addresses."""

    status_code = 409

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _fail(code):
    raise CheckoutEventError(code)


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


def _integer(value, maximum=_MAX_CENTS):
    if type(value) is not int or not 0 <= value <= maximum:
        _fail('invalid_checkout_amount')
    return value


def _text(value):
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFKC', value)
    if any(unicodedata.category(c).startswith('C') and not c.isspace() for c in value):
        return None
    return ' '.join(value.casefold().split())


def _address(value):
    if not isinstance(value, Mapping):
        return None
    normalized = {}
    for field in ('line1', 'line2', 'city', 'state', 'postal_code', 'country'):
        raw = value.get(field)
        if raw is None and field in ('line2', 'state'):
            raw = ''
        text = _text(raw)
        if text is None or (not text and field in ('line1', 'city', 'postal_code', 'country')):
            return None
        if field == 'postal_code':
            text = ''.join(c for c in text if not c.isspace() and unicodedata.category(c) != 'Pd')
            if not text or not text.isalnum():
                return None
        elif field == 'country':
            text = text.upper()
            if not re.fullmatch(r'[A-Z]{2}', text):
                return None
        normalized[field] = text
    return normalized


def _destination_matches(session, order):
    expected = _address(order.get('shipping_address'))
    if expected is None:
        return False
    observed = []
    legacy = session.get('shipping_details')
    collected = session.get('collected_information')
    if legacy is not None:
        observed.append(_address(legacy.get('address')) if isinstance(legacy, Mapping) else None)
    if collected is not None:
        if not isinstance(collected, Mapping):
            return False
        modern = collected.get('shipping_details')
        if modern is not None:
            observed.append(_address(modern.get('address')) if isinstance(modern, Mapping) else None)
    return bool(observed) and all(address == expected for address in observed)


def _intent(value):
    if value is None:
        return None
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(c.isspace() or unicodedata.category(c).startswith('C') for c in value)):
        _fail('invalid_checkout_payment_intent')
    return value


def validate_checkout_session(session: Mapping, attempt: Mapping, order: Mapping, *,
                              require_paid: bool = False) -> dict:
    """Return a redacted verified projection, or a typed identity/money refusal.

    Unpaid/open and unpaid/complete (asynchronous processing) are inspectable when
    require_paid=False, but are never financial proof. With require_paid=True,
    only complete+paid or complete+zero/no_payment_required are accepted. A paid
    session's destination mismatch is a non-throwing review outcome, not success
    authorization for shipment. The returned dict contains no customer PII.
    """
    if (not isinstance(session, Mapping) or not isinstance(attempt, Mapping)
            or not isinstance(order, Mapping) or type(require_paid) is not bool):
        _fail('invalid_checkout_event_context')
    if order.get('is_test') is not True or attempt.get('is_test') is not True or session.get('livemode') is not False:
        _fail('checkout_event_mode_mismatch')
    if session.get('object') != 'checkout.session' or session.get('mode') != 'payment':
        _fail('checkout_event_mode_mismatch')
    order_id, quote_id = _uuid(order.get('id')), _uuid(order.get('commerce_quote_id'))
    attempt_id = _uuid(attempt.get('id'))
    if _uuid(attempt.get('order_id')) != order_id or _uuid(attempt.get('commerce_quote_id')) != quote_id:
        _fail('checkout_event_identity_mismatch')
    metadata = session.get('metadata')
    expected = {'order_id': order_id, 'quote_id': quote_id, 'attempt_id': attempt_id}
    if (not isinstance(metadata, Mapping) or any(metadata.get(k) != v for k, v in expected.items())
            or session.get('client_reference_id') != order_id):
        _fail('checkout_event_identity_mismatch')
    session_id = session.get('id')
    if not isinstance(session_id, str) or not re.fullmatch(r'cs_test_[A-Za-z0-9_]+', session_id):
        _fail('checkout_event_session_mismatch')
    bound_session = attempt.get('session_id')
    if bound_session is not None and bound_session != session_id:
        _fail('checkout_event_session_mismatch')
    # expires_at is identity, NOT a clock-based test for asynchronous settlement.
    if (type(session.get('expires_at')) is not int or type(attempt.get('expires_at')) is not int
            or session['expires_at'] <= 0 or session['expires_at'] != attempt['expires_at']):
        _fail('checkout_event_expiration_mismatch')
    if order.get('currency') != 'EUR' or attempt.get('currency') != 'EUR' or session.get('currency') != 'eur':
        _fail('checkout_event_currency_mismatch')
    subtotal = _integer(order.get('subtotal_cents'))
    shipping = _integer(order.get('shipping_amount_cents'))
    total = _integer(order.get('total_cents'))
    recorded_tax = _integer(order.get('tax_amount_cents'))
    provider_total = _integer(session.get('amount_total'))
    if (subtotal + shipping != total or recorded_tax > total
            or _integer(attempt.get('total_cents')) != total or provider_total != total
            or _integer(session.get('amount_subtotal')) != subtotal):
        _fail('checkout_event_amount_mismatch')
    details, automatic_tax = session.get('total_details'), session.get('automatic_tax')
    if not isinstance(details, Mapping) or not isinstance(automatic_tax, Mapping):
        _fail('checkout_event_amount_mismatch')
    if (_integer(details.get('amount_discount')) != 0
            or _integer(details.get('amount_shipping')) != shipping
            or _integer(details.get('amount_tax')) != 0
            or automatic_tax.get('enabled') is not False
            or session.get('discounts') not in (None, [])):
        _fail('checkout_event_amount_mismatch')
    if 'shipping_cost' in session and session['shipping_cost'] is not None:
        cost = session['shipping_cost']
        if (not isinstance(cost, Mapping) or _integer(cost.get('amount_total')) != shipping
                or _integer(cost.get('amount_subtotal')) != shipping or _integer(cost.get('amount_tax')) != 0):
            _fail('checkout_event_amount_mismatch')
    status, payment_status = session.get('status'), session.get('payment_status')
    if status not in ('open', 'complete', 'expired') or payment_status not in ('paid', 'unpaid', 'no_payment_required'):
        _fail('checkout_event_state_mismatch')
    intent = _intent(session.get('payment_intent'))
    if attempt.get('payment_intent_id') is not None and attempt['payment_intent_id'] != intent:
        _fail('checkout_event_payment_intent_mismatch')
    financial_valid = payment_status in ('paid', 'no_payment_required')
    if financial_valid:
        if status != 'complete':
            _fail('checkout_event_state_mismatch')
        if payment_status == 'no_payment_required' and total != 0:
            _fail('checkout_payment_not_paid')
        if payment_status == 'paid' and intent is None:
            _fail('invalid_checkout_payment_intent')
    elif require_paid:
        _fail('checkout_payment_not_paid')
    matches = _destination_matches(session, order) if financial_valid else None
    return {
        'session_id': session_id, 'payment_intent_id': intent,
        'payment_status': payment_status, 'amount_total': provider_total, 'currency': 'EUR',
        'financial_valid': financial_valid, 'destination_matches': matches,
        'review_reason': 'checkout_destination_mismatch' if matches is False else None,
    }
