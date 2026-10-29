"""Explicit signed receivers for immutable account-bound checkout histories."""
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.commerce_context_payments import ContextCheckoutPayments
from app.commerce_webhook_profiles import load_webhook_profiles, verify_profile_event, WebhookProfileError

logger = logging.getLogger(__name__)


def create_context_webhook_router(db, get_settings):
    router = APIRouter(prefix='/api', tags=['stripe-context-webhook'])

    @router.post('/stripe/webhook/{profile_ref}', include_in_schema=False)
    async def webhook(profile_ref: str, request: Request,
                      stripe_signature: str | None = Header(default=None, alias='Stripe-Signature')):
        settings = get_settings()
        try:
            profiles = load_webhook_profiles(settings.stripe_webhook_profiles_json,
                                             legacy_secret=settings.stripe_webhook_secret)
            profile = next((p for p in profiles if p.reference == profile_ref), None)
        except WebhookProfileError:
            raise HTTPException(503, 'Stripe receiver is not configured') from None
        if profile is None:
            raise HTTPException(404, 'Stripe receiver not found')
        if not stripe_signature:
            raise HTTPException(400, 'Missing webhook signature')
        # Bound memory even if Content-Length is absent or dishonest.
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > 1048576:
                raise HTTPException(413, 'Webhook body too large')
            payload.extend(chunk)
        try:
            event = verify_profile_event(profile, bytes(payload), stripe_signature)
        except WebhookProfileError:
            raise HTTPException(400, 'Invalid Stripe receiver signature or context') from None
        try:
            return await ContextCheckoutPayments(db, profile).accept_signed_event(event)
        except Exception as error:
            # No raw event, signature, account, address or exception detail logged.
            # Non-2xx retains Stripe retry; a receipt DB failure is not a success.
            logger.error('Profile checkout event requires inspection (%s)', type(error).__name__)
            raise HTTPException(500, 'Checkout event requires inspection') from None

    return router
