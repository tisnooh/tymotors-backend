"""Private sandbox payment inspection: reads only, never settlement or recovery.

The HTTP caller must authorize an administrator. All payment identities come
from server-side rows, not client-supplied session IDs. Provider reads use an
explicit test gateway and the common immutable-session validator. A Checkout
Session saying 'paid' is not evidence of a later refund, nor permission to ship.

No create call, RPC, event ID generation, SQL mutation, email, supplier action,
stock consumption or hold release exists in this module. Unknown provider
results keep their uncertainty. Signed webhooks/dedicated reviewed financial
transactions remain necessary for financial effects.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from uuid import UUID

from app.commerce_checkout_events import CheckoutEventError, validate_checkout_session
from app.commerce_payment_service import TestStripeGateway


class PaymentObservationError(ValueError):
    """Fixed safe business code, with no provider message or private record."""
    def __init__(self, code: str, status_code: int = 409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def _uuid(value):
    if not isinstance(value, (str, UUID)):
        raise ValueError
    parsed = UUID(str(value))
    if not parsed.int:
        raise ValueError
    return str(parsed)


def _integer(value, *, maximum=99_999_999):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError
    return value


class CommercePaymentObservation:
    def __init__(self, db, gateway):
        self.db, self.gateway = db, gateway

    async def _select(self, table, identity_field, identity):
        try:
            rows = await self.db.select(table, params={identity_field: 'eq.' + identity, 'limit': 2})
        except Exception:
            raise PaymentObservationError('observation_database_unavailable', 503) from None
        if not isinstance(rows, list) or len(rows) > 1 or any(not isinstance(row, Mapping) for row in rows):
            raise PaymentObservationError('observation_context_invalid')
        return rows

    async def _context(self, attempt_id):
        try:
            identity = _uuid(attempt_id)
        except (ValueError, TypeError, AttributeError):
            raise PaymentObservationError('invalid_attempt_id', 400) from None
        attempts = await self._select('commerce_checkout_attempts', 'id', identity)
        if not attempts:
            raise PaymentObservationError('unknown_attempt', 404)
        attempt = dict(attempts[0])
        try:
            if _uuid(attempt.get('id')) != identity:
                raise ValueError
            order_id, quote_id = _uuid(attempt.get('order_id')), _uuid(attempt.get('commerce_quote_id'))
        except (ValueError, TypeError, AttributeError):
            raise PaymentObservationError('observation_context_invalid') from None
        orders = await self._select('orders', 'id', order_id)
        if not orders:
            raise PaymentObservationError('observation_order_missing')
        order = dict(orders[0])
        if attempt.get('is_test') is not True or order.get('is_test') is not True:
            raise PaymentObservationError('test_observation_only')
        try:
            if _uuid(order.get('id')) != order_id or _uuid(order.get('commerce_quote_id')) != quote_id:
                raise ValueError
            if attempt.get('currency') != 'EUR' or order.get('currency') != 'EUR':
                raise ValueError
            total = _integer(order.get('total_cents'))
            if (total < 50 or _integer(attempt.get('total_cents')) != total
                    or _integer(order.get('subtotal_cents')) + _integer(order.get('shipping_amount_cents')) != total
                    or _integer(order.get('tax_amount_cents')) > total
                    or type(attempt.get('expires_at')) is not int or attempt['expires_at'] <= 0
                    or attempt.get('state') not in {'drafting','ready','creating','unknown','session_created','cancelled'}
                    or order.get('payment_status') not in {'unpaid','paid','failed','refunded'}
                    or order.get('status') not in {'pending','paid','payment_failed','cancelled','refunded'}):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise PaymentObservationError('observation_context_invalid') from None
        bindings = await self._select('commerce_test_sessions', 'attempt_id', identity)
        session_id = None
        if bindings:
            try:
                binding = bindings[0]
                session_id = binding.get('session_id')
                if (_uuid(binding.get('attempt_id')) != identity or not isinstance(session_id, str)
                        or not re.fullmatch(r'cs_test_[A-Za-z0-9_]{1,240}', session_id)
                        or attempt['state'] not in {'creating','unknown','session_created'}
                        or attempt.get('first_requested_at') is None):
                    raise ValueError
                # The attempt's legacy reserved session_id field is not the
                # binding authority, but a conflicting populated value is unsafe.
                if attempt.get('session_id') not in (None, session_id):
                    raise ValueError
                if order.get('stripe_session_id') not in (None, session_id):
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise PaymentObservationError('observation_session_binding_invalid') from None
        attempt['session_id'] = session_id
        # Pin the provider result to the financial identity already recorded on
        # the order; the common validator otherwise knows only optional attempt PI.
        recorded_intent = order.get('stripe_payment_intent_id')
        if recorded_intent is not None:
            if not isinstance(recorded_intent, str) or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,240}', recorded_intent):
                raise PaymentObservationError('observation_context_invalid')
            if attempt.get('payment_intent_id') not in (None, recorded_intent):
                raise PaymentObservationError('observation_context_invalid')
            attempt['payment_intent_id'] = recorded_intent
        return attempt, order

    async def inspect(self, attempt_id):
        if not isinstance(self.gateway, TestStripeGateway):
            raise PaymentObservationError('test_gateway_required')
        attempt, order = await self._context(attempt_id)
        # This explicit whitelist never contains provider URL, metadata, address,
        # email, payment intent, private snapshots, params or idempotency key.
        result = {
            'attempt_id': attempt['id'], 'order_id': order['id'], 'is_test': True,
            'scope': 'sandbox_observation_only_not_settlement_or_refund_verification',
            'attempt_state': attempt['state'], 'local_payment_status': order['payment_status'],
            'observation_status': 'manual_provider_lookup', 'provider_read_performed': False,
            'provider_session_status': None, 'provider_payment_status': None,
            'provider_financial_valid': None, 'payment_recorded_locally': order['payment_status'] == 'paid',
            'destination_matches': None, 'payment_reconciliation_required': True,
            'fulfillment_review_required': True, 'reservation_review_required': True,
            'refund_verification': 'not_assessed_from_checkout',
            'mutation_performed': False, 'payment_creation_allowed': False,
            'reason_codes': [],
        }
        refund_amount = order.get('refunded_amount_cents')
        refund_invalid = type(refund_amount) is not int or not 0 <= refund_amount <= order['total_cents']
        refund_present = (order['status'] == 'refunded' or order['payment_status'] == 'refunded'
                          or (type(refund_amount) is int and refund_amount > 0))
        local_conflict = (
            (order['payment_status'] == 'paid' and order['status'] not in {'paid','cancelled','refunded'})
            or (order['status'] == 'paid' and order['payment_status'] != 'paid')
            or (order['payment_status'] == 'paid' and not order.get('stripe_payment_intent_id')))
        if refund_invalid:
            result['reason_codes'].append('local_refund_state_invalid')
        if refund_present:
            result['reason_codes'].append('quoted_refund_requires_dedicated_transaction')
        if local_conflict:
            result['reason_codes'].append('local_financial_state_conflict')
        if not attempt['session_id']:
            result['reason_codes'].append('bound_provider_session_missing')
            return result
        result['provider_read_performed'] = True
        try:
            raw = await self.gateway.retrieve(attempt['session_id'])
        except Exception:
            result['observation_status'] = 'provider_lookup_unavailable'
            result['reason_codes'].append('provider_lookup_unavailable')
            return result
        # The remote read is not performed under SQL locks. If a webhook,
        # refund or operator changed the local context meanwhile, report review
        # rather than describing the stale local financial snapshot as settled.
        try:
            current_attempt, current_order = await self._context(attempt_id)
        except PaymentObservationError:
            result['observation_status'] = 'observation_context_changed'
            result['reason_codes'].append('local_context_unavailable_after_provider_read')
            return result
        if current_attempt != attempt or current_order != order:
            result['observation_status'] = 'observation_context_changed'
            result['reason_codes'].append('local_context_changed_during_provider_read')
            return result
        try:
            # SDK16 .to_dict() is recursive; retain compatibility for an older
            # resource interface without relying on deprecated global APIs.
            session = (raw.to_dict() if hasattr(raw, 'to_dict') else
                       raw.to_dict_recursive() if hasattr(raw, 'to_dict_recursive') else raw)
            intent = session.get('payment_intent') if isinstance(session, Mapping) else None
            if intent is not None and (not isinstance(intent, str)
                    or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,240}', intent)):
                raise ValueError('invalid provider payment intent identity')
            verified = validate_checkout_session(session, attempt, order)
        except (CheckoutEventError, ValueError, TypeError, AttributeError, KeyError):
            result['observation_status'] = 'provider_snapshot_conflict'
            result['reason_codes'].append('provider_snapshot_conflict')
            return result
        except Exception:
            result['observation_status'] = 'provider_snapshot_conflict'
            result['reason_codes'].append('provider_snapshot_unreadable')
            return result
        result.update(provider_session_status=session['status'],
            provider_payment_status=verified['payment_status'],
            provider_financial_valid=verified['financial_valid'],
            destination_matches=verified['destination_matches'])
        if refund_invalid or refund_present:
            result['observation_status'] = 'refund_review_required'
        elif local_conflict:
            result['observation_status'] = 'local_financial_state_review'
        elif verified['financial_valid']:
            if order['payment_status'] == 'paid':
                result['observation_status'] = 'payment_recorded_locally'
                result['payment_reconciliation_required'] = False
            else:
                result['observation_status'] = 'provider_paid_awaiting_signed_event'
                result['reason_codes'].append('signed_event_or_reviewed_settlement_required')
            if verified['destination_matches'] is False:
                result['reason_codes'].append('destination_requires_review')
        elif order['payment_status'] == 'paid':
            result['observation_status'] = 'local_financial_state_review'
            result['reason_codes'].append('local_paid_provider_unpaid_conflict')
        elif session['status'] == 'expired':
            result['observation_status'] = 'provider_expired_requires_review'
            result['reason_codes'].append('expiry_is_not_release_authorization')
        elif session['status'] == 'complete':
            result['observation_status'] = 'provider_async_unpaid'
        else:
            result['observation_status'] = 'provider_open_unpaid'
        if order['status'] == 'cancelled':
            result['reason_codes'].append('cancelled_order_requires_review')
        return result
