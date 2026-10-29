"""Server-owned direct-account Stripe webhook profiles, independent of checkout mode.

This registry contains signing secrets and must never be serialized to clients or
logs. No secret discovery/fallback and no Stripe Connect accounts are supported.
Signature verification identifies the configured receiver; it does not authorize
new purchases. Existing financial callbacks must survive a checkout stop.
"""
from dataclasses import dataclass, field
import json
import re

import stripe

from app.commerce_checkout_mode import CheckoutServerContext


class WebhookProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StripeWebhookProfile:
    reference: str
    context: CheckoutServerContext
    signing_secret: str = field(repr=False)


def load_webhook_profiles(raw: str, *, legacy_secret: str = '') -> tuple[StripeWebhookProfile, ...]:
    """Load ONLY a server secret environment value, never request JSON."""
    if raw == '':
        return ()
    try:
        if not isinstance(raw, str) or len(raw) > 16384:
            raise ValueError
        values = json.loads(raw)
        if not isinstance(values, list) or not 1 <= len(values) <= 16:
            raise ValueError
        result, references, secrets = [], set(), {legacy_secret} if legacy_secret else set()
        for value in values:
            if (not isinstance(value, dict) or set(value) != {'reference', 'mode', 'account_id', 'signing_secret'}
                    or not all(isinstance(v, str) for v in value.values())
                    or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value['reference'])
                    or value['mode'] not in ('sandbox', 'production')
                    or not re.fullmatch(r'acct_[A-Za-z0-9]{1,240}', value['account_id'])
                    or not re.fullmatch(r'whsec_[A-Za-z0-9_]{8,240}', value['signing_secret'])
                    or value['reference'] in references or value['signing_secret'] in secrets):
                raise ValueError
            result.append(StripeWebhookProfile(value['reference'],
                CheckoutServerContext(value['mode'], value['account_id']), value['signing_secret']))
            references.add(value['reference'])
            secrets.add(value['signing_secret'])
        return tuple(result)
    except (ValueError, TypeError, KeyError):
        raise WebhookProfileError('invalid_server_webhook_profiles') from None


def verify_profile_event(profile: StripeWebhookProfile, payload: bytes, signature: str) -> dict:
    """Authenticate the unchanged body with one explicitly selected secret."""
    if type(profile) is not StripeWebhookProfile or not signature or not isinstance(payload, bytes):
        raise WebhookProfileError('invalid_webhook_signature')
    try:
        event = stripe.Webhook.construct_event(payload, signature, profile.signing_secret).to_dict()
    except (ValueError, stripe.SignatureVerificationError, AttributeError, TypeError):
        raise WebhookProfileError('invalid_webhook_signature') from None
    if (event.get('object') != 'event'
            or event.get('livemode') is not (profile.context.mode == 'production')
            or 'account' in event  # direct-account endpoint only; Connect is not implemented
            or 'context' in event
            or not isinstance(event.get('id'), str)
            or not re.fullmatch(r'evt_[A-Za-z0-9_]{1,240}', event['id'])
            or not isinstance(event.get('type'), str)
            or not isinstance(event.get('data'), dict)
            or not isinstance(event['data'].get('object'), dict)):
        raise WebhookProfileError('webhook_profile_mismatch')
    return event
