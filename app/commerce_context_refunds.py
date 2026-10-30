"""Financial projection of authenticated direct-account refund observations.

Caller must verify the exact raw-body HMAC before use. No provider writes,
refund creation, stock restoration or release of financial review is performed.
"""
from collections.abc import Mapping
from copy import deepcopy
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, Field, field_validator

from app.commerce_models import StrictInput
from app.commerce_refund_events import normalize_test_refund_event
from app.commerce_webhook_profiles import StripeWebhookProfile, direct_account_context_matches


def normalize_context_refund_event(event, profile):
    if (type(profile) is not StripeWebhookProfile or not isinstance(event, Mapping)
            or event.get('livemode') is not (profile.context.mode == 'production')
            or not direct_account_context_matches(event, profile.context.stripe_account_id)):
        raise ValueError('Invalid context refund event')
    adapted = deepcopy(dict(event))
    adapted['livemode'] = False
    data = adapted.get('data')
    resource = data.get('object') if isinstance(data, dict) else None
    if not isinstance(resource, dict):
        raise ValueError('Invalid context refund event')
    # Reuse the independently tested pure financial parser, after checking all
    # explicit live flags against the immutable server scope. Never mutate input.
    for obj in (resource, resource.get('payment_intent'), resource.get('charge')):
        if isinstance(obj, dict) and 'livemode' in obj:
            if obj['livemode'] is not (profile.context.mode == 'production'):
                raise ValueError('Invalid context refund event')
            obj['livemode'] = False
    return normalize_test_refund_event(adapted)


async def record_signed_context_refund(db, profile, event):
    return await db.rpc('commerce_record_context_refund', {
        'p_event': normalize_context_refund_event(event, profile),
        'p_is_test': profile.context.mode == 'sandbox',
        'p_stripe_account_id': profile.context.stripe_account_id,
        'p_profile_ref': profile.reference,
    })


class ContextRefundReviewInput(StrictInput):
    expected_updated_at: AwareDatetime
    evidence_ref: str = Field(min_length=3, max_length=1000)

    @field_validator('evidence_ref')
    @classmethod
    def plain_evidence(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Plain evidence reference required')
        return value


def create_context_refund_router(db, require_admin):
    router = APIRouter(prefix='/api/admin/commerce/context', dependencies=[Depends(require_admin)])

    @router.post('/orders/{order_id}/refund-review')
    async def review(order_id: UUID, payload: ContextRefundReviewInput, actor=Depends(require_admin)):
        return await db.rpc('commerce_reconcile_context_refunds', {
            'p_actor': actor['id'], 'p_order_id': str(order_id),
            'p_expected_updated_at': payload.expected_updated_at.isoformat(),
            'p_evidence_ref': payload.evidence_ref})

    return router
