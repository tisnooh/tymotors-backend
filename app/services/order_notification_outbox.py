"""Durable manual-fulfillment mail, not an exactly-once provider guarantee.

Only an explicit administrator action can claim a persisted event. An abandoned
claim or ambiguous provider outcome is never automatically retried. No worker,
historical backfill, test-order mail or external supplier transmission here.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.services.email_service import EmailService
from app.services.email_templates import order_event

KINDS = frozenset({'order_processing', 'order_shipped', 'order_delivered', 'order_cancelled'})


class OrderNotificationOutbox:
    def __init__(self, service: EmailService):
        self.service = service
        self.db = service.db

    async def deliver(self, log_id: str, actor: str) -> dict[str, Any]:
        result = {'log_id': log_id, 'sent': False}
        # Never log recipient, rendered content or provider exception strings.
        try:
            rows = await self.db.select('email_logs', params={'select': '*', 'id': f'eq.{log_id}', 'limit': 1})
            if not rows:
                return {**result, 'status': 'not_found'}
            row = rows[0]
            if row.get('event_snapshot') is None:
                return {**result, 'status': 'sent' if row.get('status') == 'sent' else 'legacy_review'}
            if row.get('delivery_state') not in {'pending', 'blocked'}:
                return {**result, 'status': row.get('delivery_state') or 'unknown'}
            ready, content, recipient = False, None, None
            try:
                snapshot = row['event_snapshot']
                order = snapshot['order']
                if (snapshot.get('version') != 1 or row['email_type'] not in KINDS
                        or str(uuid.UUID(order['id'])) != row.get('order_id')
                        or not isinstance(snapshot['items'], list)):
                    raise ValueError('Invalid frozen event')
                recipient = self.service.normalize_email(row['recipient'])
                content = order_event(row['email_type'], order, snapshot['items'],
                    f"{self.service.settings.frontend_url}/account/orders/{order['id']}")
                ready = self.service.settings.email_enabled
            except (KeyError, TypeError, ValueError, AttributeError):
                pass  # Invalid/missing snapshot is blocked before any transport.
            token = str(uuid.uuid4())
            claim = await self.db.rpc('admin_claim_order_notification', {
                'p_actor': actor, 'p_id': log_id, 'p_token': token, 'p_ready': ready})
            if claim.get('claimed') is not True:
                return {**result, 'status': claim.get('state') or 'unknown'}
        except Exception:
            # A lost claim response may mean it committed. Never retry transport.
            return {**result, 'status': 'unknown'}

        try:
            provider_id = await asyncio.to_thread(self.service.transport, recipient, content)
            outcome = 'sent'
            if provider_id is not None and (not isinstance(provider_id, str) or len(provider_id) > 500):
                provider_id = None
        except Exception:
            # SMTP/HTTP exceptions can occur after acceptance by the provider.
            provider_id, outcome = None, 'unknown'
        try:
            saved = await self.db.rpc('complete_order_notification', {
                'p_id': log_id, 'p_token': token, 'p_outcome': outcome, 'p_provider_id': provider_id})
            if saved.get('completed') is True and saved.get('state') == outcome:
                return {**result, 'status': outcome, 'sent': outcome == 'sent'}
        except Exception:
            pass  # Persisted claimed state prevents blind resend after DB failure.
        return {**result, 'status': 'unknown'}
