"""Account-bound Stripe adapter, with no route, activation or commercial authority.

The durable checkout service must claim/persist the attempt and its exact params
and key before calling ``create``. This adapter neither rotates keys nor retries
ambiguous POSTs. It is not a replacement for signed-event settlement, a launch
decision, immutable order validation, or database idempotence.

The authenticated account is read using the SAME instance/credential used for
Checkout, without Connect delegation. Stripe's Account has no ``livemode``
guarantee: credential prefix constrains the mode and every returned Session's
strict livemode and ID are checked independently. Session metadata is never used
as account authentication. A disabled account may still be read to reconcile
previously initiated payments; only NEW production creation requires charges.

Official API references verified 2026-10-29:
https://docs.stripe.com/api/accounts/retrieve
https://docs.stripe.com/api/checkout/sessions/retrieve
https://docs.stripe.com/api/idempotent_requests
SDK16 accounts.retrieve_current_async() uses GET /v1/account.
"""
from __future__ import annotations

from copy import deepcopy
import re

import stripe

from app.commerce_checkout_mode import CheckoutServerContext


class StripeGatewayError(ValueError):
    """Safe code only. ``provider_request_started`` refers to a creation POST.

    True means a Session MIGHT have been created, not that the payment succeeded.
    False does not prove that some earlier invocation created no session.
    """

    def __init__(self, code: str, *, provider_request_started: bool = False):
        self.code = code
        self.provider_request_started = provider_request_started
        super().__init__(code)


_CREATE_FIELDS = frozenset({
    'mode', 'client_reference_id', 'metadata', 'payment_intent_data', 'line_items',
    'shipping_options', 'shipping_address_collection', 'billing_address_collection',
    'automatic_tax', 'adaptive_pricing', 'allow_promotion_codes',
    'integration_identifier', 'expires_at', 'success_url', 'cancel_url',
})


def _plain(value):
    if hasattr(value, 'to_dict'):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise ValueError('Unexpected provider object')
    return value


class AuthenticatedStripeGateway:
    """Explicit expected account/mode; no network during construction.

    Only direct merchant keys are supported. No stripe_account/Stripe-Context
    override, alternate endpoint, automatic API retry or cached authentication.
    Caller owns an explicitly supplied HTTP client and closes it after use.
    """

    def __init__(self, api_key, server_context: CheckoutServerContext, *, http_client=None):
        if (type(server_context) is not CheckoutServerContext
                or server_context.mode not in ('sandbox', 'production')
                or not isinstance(server_context.stripe_account_id, str)
                or not re.fullmatch(r'acct_[A-Za-z0-9]{1,240}', server_context.stripe_account_id)):
            raise StripeGatewayError('stripe_server_context_required')
        key_mode = 'test' if server_context.mode == 'sandbox' else 'live'
        prefixes = '(?:sk|rk|rkcs)' if key_mode == 'test' else '(?:sk|rk)'
        if not isinstance(api_key, str) or not re.fullmatch(prefixes + '_' + key_mode + r'_[A-Za-z0-9_]+', api_key):
            raise StripeGatewayError('stripe_credentials_mode_mismatch')
        self._server_context = server_context
        options = {'max_network_retries': 0}
        if http_client is not None:
            options['http_client'] = http_client
        self._client = stripe.StripeClient(api_key, **options)

    @property
    def server_context(self) -> CheckoutServerContext:
        return self._server_context

    async def authenticate(self, *, for_create: bool = False) -> CheckoutServerContext:
        """Authenticate key ownership, without treating account flags as law."""
        if type(for_create) is not bool:
            raise StripeGatewayError('invalid_stripe_authentication_scope')
        try:
            account = _plain(await self._client.v1.accounts.retrieve_current_async())
        except Exception:
            # Stripe error messages may contain private requests/provider data.
            raise StripeGatewayError('stripe_account_authentication_failed') from None
        if (account.get('object') != 'account'
                or account.get('id') != self.server_context.stripe_account_id):
            raise StripeGatewayError('stripe_account_mismatch')
        if (for_create and self.server_context.mode == 'production'
                and account.get('charges_enabled') is not True):
            raise StripeGatewayError('stripe_account_charges_unavailable')
        return self.server_context

    def _session_identity(self, identity):
        prefix = 'cs_test_' if self.server_context.mode == 'sandbox' else 'cs_live_'
        if not isinstance(identity, str) or not re.fullmatch(prefix + r'[A-Za-z0-9_]{1,240}', identity):
            raise StripeGatewayError('stripe_session_mode_mismatch')
        return identity

    def _session(self, response, *, identity=None, created=False):
        try:
            session = _plain(response)
            self._session_identity(session.get('id'))
            if (session.get('object') != 'checkout.session'
                    or session.get('livemode') is not (self.server_context.mode == 'production')
                    or session.get('mode') != 'payment'
                    or (identity is not None and session['id'] != identity)):
                raise ValueError('Unexpected provider session')
            return session
        except (ValueError, TypeError, AttributeError, KeyError):
            raise StripeGatewayError('stripe_session_response_requires_review',
                                     provider_request_started=created) from None

    async def create(self, params, key):
        """Send exactly one POST with the frozen caller key; never retry here."""
        # Only the existing quote builder's contract is accepted. In particular,
        # no Connect transfer, delegation, payment-method override or SDK option
        # can be smuggled inside a JSON dictionary. Full financial/content
        # validation remains the durable checkout service's responsibility.
        if (not isinstance(params, dict) or not params or set(params) - _CREATE_FIELDS
                or params.get('mode') != 'payment'
                or not isinstance(params.get('payment_intent_data'), dict)
                or set(params['payment_intent_data']) != {'metadata'}
                or not isinstance(params['payment_intent_data']['metadata'], dict)):
            raise StripeGatewayError('invalid_stripe_checkout_params')
        if (not isinstance(key, str) or not 1 <= len(key) <= 255
                or not key.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in key)):
            raise StripeGatewayError('invalid_stripe_idempotency_key')
        # Copy before the await: a caller mutation cannot change claimed params
        # while the provider ownership check is in progress.
        frozen = deepcopy(params)
        await self.authenticate(for_create=True)
        try:
            response = await self._client.v1.checkout.sessions.create_async(
                frozen, options={'idempotency_key': key})
        except Exception:
            raise StripeGatewayError('stripe_creation_requires_inspection',
                                     provider_request_started=True) from None
        return self._session(response, created=True)

    async def retrieve(self, session_id):
        """Read the exact bound session, even when new charges are disabled."""
        identity = self._session_identity(session_id)
        await self.authenticate()
        try:
            response = await self._client.v1.checkout.sessions.retrieve_async(identity)
        except Exception:
            raise StripeGatewayError('stripe_session_read_failed') from None
        return self._session(response, identity=identity)
