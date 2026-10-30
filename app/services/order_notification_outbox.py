"""Durable fulfillment/financial receipts, not an exactly-once provider guarantee.

Only an explicit administrator action can claim a persisted event. An abandoned
claim or ambiguous provider outcome is never automatically retried. No worker,
historical backfill, test-order mail or external supplier transmission here.
"""
from __future__ import annotations

import asyncio
import uuid
import re
from datetime import datetime
from typing import Any

from app.services.email_service import EmailService
from app.services.email_templates import order_event

KINDS = frozenset({'order_processing', 'order_shipped', 'order_delivered', 'order_cancelled'})
FINANCIAL_KINDS = frozenset({'payment_confirmed', 'refund_confirmed'})


def financial_amount(snapshot, kind):
    """Check the frozen receipt, not provider authenticity or current eligibility.

    SQL independently checks current financial state under the order/log lock.
    Refund amounts are cumulative, matching the historical idempotency key.
    """
    order, financial = snapshot['order'], snapshot['financial']
    if (type(snapshot['version']) is not int or snapshot['version'] != 1
            or kind not in FINANCIAL_KINDS or financial['kind'] != kind or order['is_test'] is not False
            or order['currency'] != 'EUR' or financial['payment_intent_id'] != order['stripe_payment_intent_id']
            or not isinstance(financial['payment_intent_id'], str)
            or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,240}', financial['payment_intent_id'])):
        raise ValueError('Invalid financial receipt identity')
    total, refunded = financial['total_cents'], financial['refunded_amount_cents']
    for value in (total, refunded, order['total_cents'], order['refunded_amount_cents'],
                  order['subtotal_cents'], order['shipping_amount_cents'], order['tax_amount_cents']):
        if type(value) is not int or not 0 <= value <= 99_999_999:
            raise ValueError('Invalid receipt amount')
    stamp = datetime.fromisoformat(financial['occurred_at'].replace('Z', '+00:00'))
    if (stamp.tzinfo is None or stamp.utcoffset() is None or total <= 0
            or total != order['total_cents'] or refunded != order['refunded_amount_cents']
            or refunded > total or order['subtotal_cents'] + order['shipping_amount_cents'] != total
            or order['tax_amount_cents'] > total):
        raise ValueError('Financial receipt amount mismatch')
    items = snapshot['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('Financial receipt items missing')
    for item in items:
        if (not isinstance(item, dict) or type(item.get('quantity')) is not int
                or not 1 <= item['quantity'] <= 20 or type(item.get('unit_amount_cents')) is not int
                or not 0 <= item['unit_amount_cents'] <= 99_999_999):
            raise ValueError('Invalid financial receipt item')
    if sum(i['quantity'] * i['unit_amount_cents'] for i in items) != order['subtotal_cents']:
        raise ValueError('Financial receipt subtotal mismatch')
    if kind == 'payment_confirmed':
        if refunded != 0 or order['payment_status'] != 'paid':
            raise ValueError('Invalid payment receipt state')
        return None
    if refunded <= 0 or order['payment_status'] != ('refunded' if refunded == total else 'paid'):
        raise ValueError('Invalid refund receipt state')
    return refunded


class OrderNotificationOutbox:
    def __init__(self, service: EmailService):
        self.service = service
        self.db = service.db

    async def deliver(self, log_id: str, actor: str) -> dict[str, Any]:
        return await self._deliver(log_id, actor)

    async def deliver_financial(self, log_id: str, *, enabled=False) -> dict[str, Any]:
        """Opt-in system entry; SQL separately checks its persistent stop gate."""
        if enabled is not True:
            return {'log_id': log_id, 'sent': False, 'status': 'disabled'}
        return await self._deliver(log_id, None, system_financial=True)

    async def _deliver(self, log_id, actor, *, system_financial=False):
        result = {'log_id': log_id, 'sent': False}
        # Never log recipient, rendered content or provider exception strings.
        try:
            rows = await self.db.select('email_logs', params={'select': '*', 'id': f'eq.{log_id}', 'limit': 1})
            if not rows:
                return {**result, 'status': 'not_found'}
            row = rows[0]
            if system_financial and row.get('delivery_state') != 'pending':
                return {**result, 'status': row.get('delivery_state') or 'unknown'}
            if system_financial and (row.get('email_type') not in FINANCIAL_KINDS
                    or (row.get('metadata') or {}).get('source') != 'atomic_financial_transition'):
                return {**result, 'status': 'ineligible'}
            if row.get('event_snapshot') is None:
                return {**result, 'status': 'sent' if row.get('status') == 'sent' else 'legacy_review'}
            if row.get('delivery_state') not in {'pending', 'blocked'}:
                return {**result, 'status': row.get('delivery_state') or 'unknown'}
            ready, content, recipient = False, None, None
            try:
                snapshot = row['event_snapshot']
                order = snapshot['order']
                if (snapshot.get('version') != 1 or row['email_type'] not in KINDS | FINANCIAL_KINDS
                        or str(uuid.UUID(order['id'])) != row.get('order_id')
                        or not isinstance(snapshot['items'], list)):
                    raise ValueError('Invalid frozen event')
                recipient = self.service.normalize_email(row['recipient'])
                amount = financial_amount(snapshot, row['email_type']) if row['email_type'] in FINANCIAL_KINDS else None
                content = order_event(row['email_type'], order, snapshot['items'],
                    f"{self.service.settings.frontend_url}/account/orders/{order['id']}", amount_cents=amount)
                ready = self.service.settings.email_enabled
            except (KeyError, TypeError, ValueError, AttributeError):
                pass  # Invalid/missing snapshot is blocked before any transport.
            token = str(uuid.uuid4())
            claim_args = {'p_id': log_id, 'p_token': token, 'p_ready': ready}
            if not system_financial:
                claim_args['p_actor'] = actor
            claim = await self.db.rpc('commerce_claim_financial_notification' if system_financial
                                      else 'admin_claim_order_notification', claim_args)
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
