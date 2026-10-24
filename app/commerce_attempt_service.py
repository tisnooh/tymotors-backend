"""Durable sandbox preparation only; never invokes a payment provider.

The SQL layer owns one attempt/order and isolated test reservations. No HTTP
retry may regenerate its key/expiry/parameters or clear a possibly paid hold.
This service intentionally cannot create a Stripe session until its dedicated
webhook transaction and reconciliation path are integrated and verified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import UUID

from app.commerce_checkout_params import CheckoutParamsError, build_checkout_params
from app.supabase_rest import SupabaseError

logger = logging.getLogger(__name__)


class CheckoutAttemptError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def public_attempt(attempt: dict, now: datetime | None = None) -> dict:
    """Explicit admin projection, excluding private params, keys and snapshots."""
    now = now or datetime.now(timezone.utc)
    try:
        identity, order = str(UUID(attempt['id'])), str(UUID(attempt['order_id']))
        state = attempt['state']
        expiry = attempt['expires_at']
        if (state not in {'drafting', 'ready', 'creating', 'unknown', 'session_created', 'cancelled'}
                or type(expiry) is not int or attempt['is_test'] is not True):
            raise ValueError('Invalid attempt state')
        return {
            'attempt_id': identity, 'order_id': order, 'state': state, 'is_test': True,
            'expires_at': expiry, 'expired_locally': expiry <= now.timestamp(),
            'requires_reconciliation': state in {'creating', 'unknown', 'session_created'},
            'payment_available': False, 'scope': 'durable_test_preparation_not_checkout',
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        raise CheckoutAttemptError('invalid_checkout_attempt') from None


class CheckoutAttemptService:
    def __init__(self, db, trusted_origin):
        self.db = db
        self.trusted_origin = trusted_origin

    async def _rpc(self, function, payload):
        try:
            return await self.db.rpc(function, payload)
        except SupabaseError as error:
            if error.status_code in {400, 403, 404, 409, 422}:
                raise CheckoutAttemptError('checkout_attempt_conflict') from None
            raise

    async def prepare(self, actor_id, order_id):
        context = await self._rpc('commerce_prepare_checkout_attempt', {
            'p_actor': actor_id, 'p_order_id': str(order_id),
            'p_frontend_origin': self.trusted_origin,
        })
        try:
            attempt, order, items = context['attempt'], context['order'], context['items']
            if (str(UUID(order['id'])) != str(UUID(str(order_id)))
                    or str(UUID(attempt['order_id'])) != str(UUID(order['id']))
                    or str(UUID(attempt['commerce_quote_id'])) != str(UUID(order['commerce_quote_id']))
                    or order.get('is_test') is not True):
                raise ValueError('Mismatched order context')
            projection = public_attempt(attempt)
        except (KeyError, TypeError, ValueError):
            raise CheckoutAttemptError('invalid_checkout_context') from None
        if attempt['state'] != 'drafting':
            # A duplicate request restores state. No rebuilding old params,
            # extending expiration, changing an unknown outcome or provider call.
            return projection
        try:
            params = build_checkout_params(order, items, attempt,
                                           trusted_origin=self.trusted_origin,
                                           now=datetime.now(timezone.utc))
        except CheckoutParamsError as error:
            # This module has made NO provider call. SQL independently refuses
            # cancellation after the first remote claim, even in a racing worker.
            try:
                await self._rpc('commerce_cancel_checkout_draft', {
                    'p_actor': actor_id, 'p_attempt_id': attempt['id'],
                })
            except (CheckoutAttemptError, SupabaseError):
                logger.warning('Sandbox draft cleanup requires inspection')
            raise CheckoutAttemptError(error.code) from None
        result = await self._rpc('commerce_store_checkout_params', {
            'p_actor': actor_id, 'p_attempt_id': attempt['id'], 'p_params': params,
        })
        if (not isinstance(result, dict) or result.get('id') != attempt['id']
                or result.get('order_id') != order['id']
                or result.get('commerce_quote_id') != order['commerce_quote_id']):
            raise CheckoutAttemptError('invalid_checkout_context')
        return public_attempt(result)

    async def read(self, attempt_id):
        rows = await self.db.select('commerce_checkout_attempts', params={
            'id': f'eq.{attempt_id}', 'limit': 1,
        })
        return public_attempt(rows[0]) if rows else None

    async def cancel_draft(self, actor_id, attempt_id):
        result = await self._rpc('commerce_cancel_checkout_draft', {
            'p_actor': actor_id, 'p_attempt_id': str(attempt_id),
        })
        return public_attempt(result)
