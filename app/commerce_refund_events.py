"""Pure, redacted normalization of already-authenticated Stripe TEST events.

The HTTP caller MUST verify the raw webhook signature before invoking this
function. This module performs no authentication, deduplication, reconciliation,
settlement, SDK/network call, database write, refund creation or stock operation.
Metadata is not authority and is deliberately omitted, as is all customer data.

``charge_refunded_cents`` is a cumulative charge observation, NEVER a refund
delta. ``amount_cents`` belongs only to a single Refund identity. Nullable refund
status/financial references remain unknown: they are not inferred as succeeded.
The caller must persist and bind these observations transactionally before any
financial effect. A structurally valid event alone cannot authorize fulfillment.
"""
from collections.abc import Mapping
import re


_MAX_CENTS = 99_999_999  # Local supported policy, not a universal provider limit.
_REFUND_TYPES = frozenset({'refund.created', 'refund.updated', 'refund.failed'})
_REFUND_STATUSES = frozenset({'pending', 'requires_action', 'succeeded', 'failed', 'canceled'})


class RefundEventError(ValueError):
    """One safe fixed code, with no provider values or personal information."""

    code = 'invalid_test_refund_event'

    def __init__(self):
        super().__init__(self.code)


def _fail():
    raise RefundEventError()


def _identity(value, prefix):
    if not isinstance(value, str) or re.fullmatch(prefix + r'_[A-Za-z0-9_]{1,240}', value) is None:
        _fail()
    return value


def _test_resource(value, kind):
    if not isinstance(value, Mapping) or value.get('object') != kind:
        _fail()
    if 'livemode' in value and value['livemode'] is not False:
        _fail()
    return value


def _reference(value, prefix, kind):
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = _test_resource(value, kind).get('id')
    return _identity(value, prefix)


def _amount(value, minimum):
    if type(value) is not int or not minimum <= value <= _MAX_CENTS:
        _fail()
    return value


def normalize_test_refund_event(event):
    """Return exactly the allowlisted financial fields, without mutating input.

    Only snapshot ``event`` objects with an explicit parent ``livemode=False``
    are accepted. ``created`` is retained as evidence, NOT a sorting/dedup key.
    Refunds need an explicit status field (including documented null); nullable
    PI/charge references can be absent. Expanded references must identify their
    exact resource type. All failures expose the same fixed ValueError code.
    """
    if (not isinstance(event, Mapping) or event.get('object') != 'event'
            or event.get('livemode') is not False):
        _fail()
    event_id = _identity(event.get('id'), 'evt')
    event_type = event.get('type')
    if not isinstance(event_type, str) or event_type not in _REFUND_TYPES | {'charge.refunded'}:
        _fail()
    created = event.get('created')
    if type(created) is not int or created <= 0:
        _fail()
    data = event.get('data')
    if not isinstance(data, Mapping):
        _fail()
    resource = _test_resource(data.get('object'), 'refund' if event_type in _REFUND_TYPES else 'charge')
    currency = resource.get('currency')
    if not isinstance(currency, str) or re.fullmatch(r'[a-z]{3}', currency) is None:
        _fail()
    intent = _reference(resource.get('payment_intent'), 'pi', 'payment_intent')
    if event_type in _REFUND_TYPES:
        refund_id = _identity(resource.get('id'), 're')
        charge_id = _reference(resource.get('charge'), 'ch', 'charge')
        amount = _amount(resource.get('amount'), 1)
        if 'status' not in resource:
            _fail()
        status = resource['status']
        if status is not None and (not isinstance(status, str) or status not in _REFUND_STATUSES):
            _fail()
        charge_refunded = None
    else:
        refund_id, amount, status = None, None, None
        charge_id = _identity(resource.get('id'), 'ch')
        charge_refunded = _amount(resource.get('amount_refunded'), 0)
    return {
        'event_id': event_id,
        'event_type': event_type,
        'event_created': created,
        'refund_id': refund_id,
        'payment_intent_id': intent,
        'charge_id': charge_id,
        'amount_cents': amount,
        'currency': currency,
        'refund_status': status,
        'charge_refunded_cents': charge_refunded,
    }
