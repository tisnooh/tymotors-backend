"""Account/profile-bound checkout execution over immutable database snapshots.

No provider write occurs without the atomic database claim. A possibly-created
session is never cancelled/retried with a different key. Signed callbacks do not
depend on the flag that stops NEW checkouts. No supplier order is transmitted.
"""
from datetime import datetime, timezone
import re
from uuid import UUID

from app.commerce_checkout_events import validate_checkout_session
from app.commerce_checkout_mode import checkout_mode
from app.commerce_checkout_params import build_checkout_params
from app.commerce_customer_checkout import CustomerCheckoutError
from app.commerce_quote_service import CartQuoteService
from app.commerce_webhook_profiles import StripeWebhookProfile

_ORDER_SNAPSHOT_FIELDS = ('id', 'commerce_quote_id', 'cart_id', 'user_id', 'guest_session_id',
    'order_number', 'is_test', 'stripe_account_id', 'stripe_profile_ref', 'currency',
    'subtotal_cents', 'shipping_amount_cents', 'tax_amount_cents', 'total_cents', 'shipping_address',
    'discount_amount_cents', 'promotion_id')


def _same_snapshot(first, second):
    # SQL adds quote_expires_at for the builder; binding/settlement may update
    # session IDs/status/timestamps without changing this financial snapshot.
    return all(first.get(key) == second.get(key) for key in _ORDER_SNAPSHOT_FIELDS)


def _id(value):
    result = UUID(str(value))
    if not result.int:
        raise ValueError('Invalid checkout identity')
    return str(result)


class ContextCheckoutPayments:
    def __init__(self, db, profile):
        if type(profile) is not StripeWebhookProfile:
            raise ValueError('Server webhook profile required')
        self.db, self.profile = db, profile

    @property
    def scope(self):
        return {'p_stripe_account_id': self.profile.context.stripe_account_id,
                'p_profile_ref': self.profile.reference}

    async def context(self, attempt_id):
        attempt_id = _id(attempt_id)
        rows = await self.db.select('commerce_checkout_attempts', params={
            'id': 'eq.' + attempt_id, 'limit': 2})
        if len(rows) != 1 or rows[0].get('id') != attempt_id:
            raise CustomerCheckoutError('checkout_requires_inspection')
        attempt = rows[0]
        orders = await self.db.select('orders', params={'id': 'eq.' + _id(attempt['order_id']), 'limit': 2})
        if (len(orders) != 1 or orders[0].get('id') != attempt['order_id']
                or orders[0].get('commerce_quote_id') != attempt.get('commerce_quote_id')):
            raise CustomerCheckoutError('checkout_requires_inspection')
        order = orders[0]
        checkout_mode(order, attempt, self.profile.context)
        if any(row.get('stripe_profile_ref') != self.profile.reference for row in (attempt, order)):
            raise CustomerCheckoutError('checkout_profile_mismatch')
        return attempt, order

    def validate(self, session, attempt, order):
        return validate_checkout_session(session, attempt, order,
            server_context=self.profile.context,
            provider_account_id=self.profile.context.stripe_account_id)

    async def create_session(self, attempt, order, owner, gateway):
        from app.commerce_stripe_gateway import AuthenticatedStripeGateway
        if (type(gateway) is not AuthenticatedStripeGateway
                or gateway.server_context != self.profile.context):
            raise CustomerCheckoutError('checkout_gateway_mismatch')
        if attempt['state'] != 'ready' or attempt.get('session_id') is not None:
            raise CustomerCheckoutError('checkout_requires_inspection')
        # Verify credentials BEFORE acquiring permission to make a provider write.
        await gateway.authenticate(for_create=True)
        claimed = await self.db.rpc('commerce_claim_context_checkout', {
            'p_attempt_id': attempt['id'], **self.scope, **owner})
        try:
            checkout_mode(order, claimed, self.profile.context)
            if (claimed.get('id') != attempt['id'] or claimed.get('order_id') != order['id']
                    or claimed.get('commerce_quote_id') != order['commerce_quote_id']
                    or claimed.get('stripe_profile_ref') != self.profile.reference
                    or claimed.get('state') != 'creating' or claimed.get('session_id') is not None
                    or claimed.get('params') != attempt.get('params')
                    or claimed.get('idempotency_key') != attempt.get('idempotency_key')):
                raise CustomerCheckoutError('checkout_claim_requires_inspection')
            session = await gateway.create(claimed['params'], claimed['idempotency_key'])
            self.validate(session, claimed, order)
            await self.db.rpc('commerce_bind_context_session', {
                'p_attempt_id': attempt['id'], 'p_session_id': session['id'], **self.scope})
        except Exception:
            try:
                await self.db.rpc('commerce_context_checkout_unknown', {
                    'p_attempt_id': attempt['id'], 'p_error_code': 'provider_response_unknown',
                    **self.scope, **owner})
            except Exception:
                pass  # the durable creating state still forbids another attempt
            raise

    async def accept_signed_event(self, event):
        # Signature verification belongs to the raw HTTP boundary. Never call
        # this with client JSON or select a profile using session metadata.
        if (event.get('livemode') is not (self.profile.context.mode == 'production')
                or 'account' in event or 'context' in event):
            raise ValueError('Webhook profile mismatch')
        kind = event['type']
        session = event['data']['object']
        if kind not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
            object_id = session.get('id')
            checkout_prefix = 'cs_test_' if self.profile.context.mode == 'sandbox' else 'cs_live_'
            identities = {'checkout.session.expired': (checkout_prefix, 'checkout.session'),
                'checkout.session.async_payment_failed': (checkout_prefix, 'checkout.session'),
                'payment_intent.payment_failed': ('pi_', 'payment_intent'), 'refund.created': ('re_', 'refund'),
                'refund.updated': ('re_', 'refund'), 'refund.failed': ('re_', 'refund'), 'charge.refunded': ('ch_', 'charge')}
            identity = identities.get(kind)
            if identity is None:
                return {'received': True, 'ignored': True}
            prefix, object_type = identity
            if (not isinstance(object_id, str)
                    or not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_]{1,240}', object_id)
                    or session.get('object') != object_type):
                raise ValueError('Invalid financial event object')
            return await self.db.rpc('commerce_record_context_event', {
                'p_event_id': event['id'], 'p_event_type': kind, 'p_object_id': object_id,
                'p_is_test': self.profile.context.mode == 'sandbox', **self.scope})
        metadata = session.get('metadata')
        if not isinstance(metadata, dict):
            raise ValueError('Missing checkout identity')
        attempt, order = await self.context(metadata.get('attempt_id'))
        observed = self.validate(session, attempt, order)
        if not observed['financial_valid']:
            return {'received': True, 'awaiting_payment': True,
                    'is_test': self.profile.context.mode == 'sandbox'}
        return await self.db.rpc('commerce_settle_context_checkout', {
            'p_event_id': event['id'], 'p_event_type': kind, 'p_session': session,
            'p_destination_matches': observed['destination_matches'], **self.scope})


def hosted_context_url(value, session_id, *, is_test):
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value)
        prefix = 'cs_test_' if is_test else 'cs_live_'
        if (not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value)
                or '\\' in value or parsed.scheme != 'https' or parsed.hostname != 'checkout.stripe.com'
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.path != '/c/pay/' + session_id
                or not re.fullmatch(prefix + r'[A-Za-z0-9_]{1,240}', session_id)):
            raise ValueError
        return value
    except (ValueError, TypeError, AttributeError):
        raise CustomerCheckoutError('checkout_provider_response_requires_review') from None


class ContextCustomerCheckout(ContextCheckoutPayments):
    async def _owned_order(self, order_id, quote_id, cart, owner):
        rows = await self.db.select('carts', params={'id': 'eq.' + cart['id'], 'limit': 2})
        if (len(rows) != 1 or rows[0].get('user_id') != owner['p_user_id']
                or rows[0].get('guest_session_id') != owner['p_guest_session']):
            raise CustomerCheckoutError('checkout_unavailable')
        if owner['p_user_id'] is not None and await self.db.rpc('is_auth_session_active', {
                'p_user_id': owner['p_user_id'], 'p_session_id': owner['p_auth_session_id']}) is not True:
            raise CustomerCheckoutError('authentication_required', 401)
        rows = await self.db.select('orders', params={'id': 'eq.' + _id(order_id), 'limit': 2})
        if len(rows) != 1:
            raise CustomerCheckoutError('checkout_unavailable')
        order = rows[0]
        if (order.get('id') != str(order_id) or order.get('commerce_quote_id') != quote_id or order.get('cart_id') != cart['id']
                or order.get('user_id') != owner['p_user_id']
                or order.get('guest_session_id') != owner['p_guest_session']
                or order.get('stripe_account_id') != self.profile.context.stripe_account_id
                or order.get('stripe_profile_ref') != self.profile.reference
                or order.get('is_test') is not (self.profile.context.mode == 'sandbox')):
            raise CustomerCheckoutError('checkout_unavailable')
        return order

    def _paid(self, order):
        if (order.get('status') == 'paid' and order.get('payment_status') == 'paid'
                and type(order.get('refunded_amount_cents')) is int and order['refunded_amount_cents'] == 0):
            return {'order_id': order['id'], 'order_number': order['order_number'],
                    'quote_id': order['commerce_quote_id'], 'status': 'paid',
                    'is_test': self.profile.context.mode == 'sandbox', 'url': None}
        if (order.get('status') != 'pending' or order.get('payment_status') != 'unpaid'
                or type(order.get('refunded_amount_cents')) is not int or order['refunded_amount_cents'] != 0):
            raise CustomerCheckoutError('checkout_requires_review')
        return None

    async def start(self, quote_id, request_key, cart, user, guest_session, owner, *, gateway, origin,
                    allowed_countries):
        from app.commerce_stripe_gateway import AuthenticatedStripeGateway
        if (type(gateway) is not AuthenticatedStripeGateway
                or gateway.server_context != self.profile.context):
            raise CustomerCheckoutError('checkout_gateway_mismatch')
        _id(request_key)
        quote_id = _id(quote_id)
        quote = await CartQuoteService(self.db, allowed_countries).read(quote_id, cart, user, guest_session)
        if quote is None:
            raise CustomerCheckoutError('checkout_unavailable')
        prepared = await self.db.rpc('commerce_prepare_context_checkout', {
            'p_quote_id': quote_id, 'p_frontend_origin': origin,
            'p_is_test': self.profile.context.mode == 'sandbox', **self.scope, **owner})
        attempt, order = prepared['attempt'], prepared['order']
        current = await self._owned_order(order['id'], quote_id, cart, owner)
        if (paid := self._paid(current)) is not None:
            return paid
        if not _same_snapshot(current, order):
            raise CustomerCheckoutError('checkout_requires_review')
        checkout_mode(order, attempt, self.profile.context)
        if attempt.get('stripe_profile_ref') != self.profile.reference:
            raise CustomerCheckoutError('checkout_profile_mismatch')
        if attempt['state'] == 'drafting':
            params = build_checkout_params(order, prepared['items'], attempt, trusted_origin=origin,
                now=datetime.now(timezone.utc), server_context=self.profile.context)
            attempt = await self.db.rpc('commerce_store_context_checkout_params', {
                'p_attempt_id': attempt['id'], 'p_params': params, **self.scope, **owner})
        if attempt.get('session_id') is None:
            await self.create_session(attempt, order, owner, gateway)
        attempt, snapshot = await self.context(attempt['id'])
        current = await self._owned_order(order['id'], quote_id, cart, owner)
        if (paid := self._paid(current)) is not None:
            return paid
        if not attempt.get('session_id') or not _same_snapshot(snapshot, order):
            raise CustomerCheckoutError('checkout_requires_inspection')
        session = await gateway.retrieve(attempt['session_id'])
        observed = self.validate(session, attempt, snapshot)
        current = await self._owned_order(order['id'], quote_id, cart, owner)
        if (paid := self._paid(current)) is not None:
            return paid
        if not _same_snapshot(current, order):
            raise CustomerCheckoutError('checkout_requires_review')
        result = {'order_id': order['id'], 'order_number': order['order_number'], 'quote_id': quote_id,
                  'session_id': attempt['session_id'], 'is_test': self.profile.context.mode == 'sandbox'}
        if observed['financial_valid']:
            return {**result, 'status': 'awaiting_webhook', 'url': None}
        if session['status'] != 'open' or session['expires_at'] <= datetime.now(timezone.utc).timestamp():
            raise CustomerCheckoutError('checkout_requires_inspection')
        return {**result, 'status': 'open', 'url': hosted_context_url(session.get('url'),
                attempt['session_id'], is_test=result['is_test'])}
