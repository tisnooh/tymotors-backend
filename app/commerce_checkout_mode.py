"""Pure server-side mode/account contract; never an authentication mechanism.

The caller loads immutable order/attempt snapshots and constructs this context
from server configuration. ``provider_account_id`` must come from the caller's
separately established provider/webhook context, NEVER session metadata, request
JSON, or an invented Account.livemode field. This module performs no SDK/network
verification. Matching strings do not prove account ownership or permission.

No context preserves the historical sandbox-only contract. Explicit context
allows structural production tests only; it authorizes no provider call, SQL
transition, deployment, or payment. Account snapshots are a proposed contract,
not columns added to existing database models by this change.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import re


class CheckoutModeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CheckoutServerContext:
    mode: str
    stripe_account_id: str


def _account(value):
    if not isinstance(value, str) or not re.fullmatch(r'acct_[A-Za-z0-9]{1,240}', value):
        raise CheckoutModeError('invalid_checkout_account_context')
    return value


def checkout_mode(order: Mapping, attempt: Mapping,
                  server_context: CheckoutServerContext | None = None) -> str:
    if server_context is None:
        # A future nullable SQL column appears as null in historical to_jsonb
        # rows. Null/absent carries NO account identity and is legacy-only.
        if any(row.get('stripe_account_id') is not None for row in (order, attempt)):
            raise CheckoutModeError('checkout_server_context_required')
        if order.get('is_test') is not True or attempt.get('is_test') is not True:
            raise CheckoutModeError('checkout_mode_mismatch')
        return 'sandbox'
    # Do not accept JSON dictionaries accidentally forwarded from a request.
    if type(server_context) is not CheckoutServerContext or server_context.mode not in ('sandbox', 'production'):
        raise CheckoutModeError('invalid_checkout_server_context')
    account = _account(server_context.stripe_account_id)
    expected_test = server_context.mode == 'sandbox'
    if order.get('is_test') is not expected_test or attempt.get('is_test') is not expected_test:
        raise CheckoutModeError('checkout_mode_mismatch')
    if any(_account(row.get('stripe_account_id')) != account for row in (order, attempt)):
        raise CheckoutModeError('checkout_account_mismatch')
    return server_context.mode


def check_provider_account(server_context, provider_account_id):
    if server_context is None:
        if provider_account_id is not None:
            raise CheckoutModeError('checkout_server_context_required')
        return
    if _account(provider_account_id) != server_context.stripe_account_id:
        raise CheckoutModeError('checkout_provider_account_mismatch')
