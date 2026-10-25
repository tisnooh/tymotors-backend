"""Sandbox provider adapter and signed-event consumer. No real-mode support.

The HTTP boundary must authenticate the raw event with the Stripe SDK BEFORE
calling accept_signed_event. There are no emails or external supplier operations.
"""
from uuid import UUID
import re
import stripe

from app.commerce_checkout_events import validate_checkout_session


class CommercePaymentError(ValueError):
    pass


class TestStripeGateway:
    """Cannot be constructed from a live/unknown key. Never logs credentials."""
    def __init__(self, api_key, *, http_client=None):
        # rkcs_test_ is the test-only key returned by the official CLI's
        # anonymous claimable sandbox. Its Checkout read capability was checked
        # with the real SDK; accepting it does not enable any live-mode prefix.
        if not isinstance(api_key, str) or not re.fullmatch(r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+', api_key):
            raise CommercePaymentError('test_credentials_required')
        self.client = (stripe.StripeClient(api_key) if http_client is None
                       else stripe.StripeClient(api_key, http_client=http_client))

    async def create(self, params, key):
        return await self.client.v1.checkout.sessions.create_async(params, options={'idempotency_key': key})

    async def retrieve(self, session_id):
        """Read one already-bound test session; never create/retry a payment."""
        if not isinstance(session_id, str) or not re.fullmatch(r'cs_test_[A-Za-z0-9_]{1,240}', session_id):
            raise CommercePaymentError('test_session_required')
        return await self.client.v1.checkout.sessions.retrieve_async(session_id)


class CommerceTestPayments:
    def __init__(self, db, stripe_client):
        self.db, self.client = db, stripe_client

    async def _context(self, attempt_id):
        try:
            identity = str(UUID(str(attempt_id)))
        except (ValueError, TypeError, AttributeError):
            raise CommercePaymentError('invalid_attempt_id') from None
        attempts = await self.db.select('commerce_checkout_attempts', params={'id': f'eq.{identity}', 'limit': 1})
        if not attempts:
            raise CommercePaymentError('unknown_attempt')
        attempt = attempts[0]
        orders = await self.db.select('orders', params={'id': 'eq.' + attempt['order_id'], 'limit': 1})
        if not orders or orders[0].get('is_test') is not True or attempt.get('is_test') is not True:
            raise CommercePaymentError('test_payments_only')
        sessions = await self.db.select('commerce_test_sessions', params={'attempt_id': f'eq.{identity}', 'limit': 1})
        return {**attempt, 'session_id': sessions[0]['session_id'] if sessions else None}, orders[0]

    async def create_session(self, actor_id, attempt_id):
        """One claim only; SDK timeout/crash stays ambiguous, never auto-recharged.

        Invoked explicitly by trusted backend/admin tooling, not a public route.
        Caller must supply a test-scoped StripeClient; returned session mode is
        checked again. No retry with a fresh key, including after 24h.
        """
        if not isinstance(self.client, TestStripeGateway):
            raise CommercePaymentError('test_gateway_required')
        attempt, order = await self._context(attempt_id)
        if attempt['state'] != 'ready' or attempt.get('session_id') is not None:
            raise CommercePaymentError('attempt_requires_inspection')
        claimed = await self.db.rpc('commerce_claim_checkout_attempt', {'p_actor': actor_id, 'p_attempt_id': attempt['id']})
        try:
            session = await self.client.create(claimed['params'], claimed['idempotency_key'])
            # Current Stripe SDK16 resources are not Mapping/dict. to_dict()
            # recurses by default; older SDK responses used to_dict_recursive().
            session = (session.to_dict() if hasattr(session, 'to_dict') else
                       session.to_dict_recursive() if hasattr(session, 'to_dict_recursive') else session)
            validate_checkout_session(session, claimed, order)
            await self.db.rpc('commerce_bind_test_session', {'p_attempt_id': attempt['id'], 'p_session_id': session['id']})
            # URL is never persisted as a trusted redirect or returned to a customer here.
            return {'attempt_id': attempt['id'], 'session_id': session['id'], 'is_test': True}
        except Exception:
            # Even an invalid provider response might have created a session.
            # Retain holds/key. A database error here must never cancel the order.
            try:
                await self.db.rpc('commerce_checkout_unknown', {'p_actor': actor_id, 'p_attempt_id': attempt['id'],
                                                               'p_error_code': 'provider_response_unknown'})
            except Exception:
                pass  # Claimed state also requires reconciliation; original error retained.
            raise

    async def accept_signed_event(self, event):
        if event.get('livemode') is not False:
            raise CommercePaymentError('test_events_only')
        if event.get('type') not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
            if event.get('type') in ('checkout.session.expired', 'checkout.session.async_payment_failed', 'payment_intent.payment_failed'):
                # No proof of absence of funds: retain claim/holds for review.
                return {'received': True, 'requires_reconciliation': True, 'is_test': True}
            raise CommercePaymentError('unsupported_quoted_financial_event_requires_review')
        session = event.get('data', {}).get('object', {})
        attempt, order = await self._context(session.get('metadata', {}).get('attempt_id'))
        result = validate_checkout_session(session, attempt, order)
        if not result['financial_valid']:
            return {'received': True, 'awaiting_payment': True, 'is_test': True}
        return await self.db.rpc('commerce_settle_test_checkout', {
            'p_event_id': event.get('id'), 'p_event_type': event['type'], 'p_session': session,
            'p_destination_matches': result['destination_matches'],
        })
