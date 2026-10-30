"""Bounded, opt-in tick owned by the optional application lifecycle.

The runtime must explicitly enable this and the separate SQL gate. No automatic retry of
claimed/unknown/sent outcomes and no historical backfill. Stop is checked before
each log; it cannot recall a transport already accepted by a provider.
"""
from uuid import UUID

from app.services.order_notification_outbox import FINANCIAL_KINDS


class FinancialNotificationWorker:
    def __init__(self, outbox, *, enabled=False, batch_size=10, stopped=lambda: False):
        if type(enabled) is not bool or type(batch_size) is not int or not 1 <= batch_size <= 50 or not callable(stopped):
            raise ValueError('Invalid financial notification worker configuration')
        self.outbox, self.enabled, self.batch_size, self.stopped = outbox, enabled, batch_size, stopped

    def _stopped(self):
        try:
            return self.stopped() is not False
        except Exception:
            return True

    async def run_once(self):
        report = {'status': 'disabled', 'attempted': 0, 'sent': 0}
        if self.enabled is not True:
            return report
        if self._stopped():
            return {**report, 'status': 'stopped'}
        try:
            rows = await self.outbox.db.select('email_logs', params={
                'select': 'id,email_type,delivery_state',
                'email_type': 'in.(payment_confirmed,refund_confirmed)',
                'delivery_state': 'eq.pending', 'metadata->>source': 'eq.atomic_financial_transition',
                'event_snapshot': 'not.is.null', 'order': 'created_at.asc,id.asc', 'limit': self.batch_size})
            if not isinstance(rows, list) or len(rows) > self.batch_size:
                raise ValueError('Invalid batch response')
            seen = set()
            for row in rows:
                identity = str(UUID(row['id']))
                if (not UUID(identity).int or identity in seen or row['email_type'] not in FINANCIAL_KINDS
                        or row['delivery_state'] not in {'pending', 'blocked'}):
                    raise ValueError('Invalid financial batch')
                seen.add(identity)
        except Exception:
            return {**report, 'status': 'unavailable'}
        for row in rows:
            if self.enabled is not True or self._stopped():
                return {**report, 'status': 'stopped'}
            report['attempted'] += 1
            try:
                result = await self.outbox.deliver_financial(row['id'], enabled=True)
                status = result['status']
                if result.get('sent') is True and status == 'sent':
                    report['sent'] += 1
                elif status == 'disabled':
                    return {**report, 'status': 'disabled'}
                elif status not in {'blocked', 'ineligible', 'not_eligible', 'not_found', 'legacy_review', 'sent', 'claimed'}:
                    return {**report, 'status': 'requires_review'}
            except Exception:
                return {**report, 'status': 'requires_review'}
        return {**report, 'status': 'completed'}
