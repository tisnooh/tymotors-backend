"""Manual evidence-backed fulfillment over existing admin auth and frozen groups.

These endpoints record human actions/evidence; they never contact a supplier,
purchase goods, obtain a carrier label or attest that a real parcel exists.
"""
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, Field, field_validator

from app.commerce_models import StrictInput
from app.commerce_checkout_params import _origin


class ContextDispatchInput(StrictInput):
    expected_updated_at: AwareDatetime
    next: Literal['supplier_confirmed', 'shipped', 'delivered']
    supplier_order_ref: str | None = Field(default=None, min_length=1, max_length=200)
    tracking_number: str | None = Field(default=None, min_length=1, max_length=120)
    carrier: str | None = Field(default=None, min_length=1, max_length=100)
    tracking_url: str | None = Field(default=None, min_length=9, max_length=1000)
    evidence_ref: str = Field(min_length=3, max_length=1000)

    @field_validator('supplier_order_ref', 'tracking_number', 'carrier', 'evidence_ref')
    @classmethod
    def plain_reference(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Plain evidence or reference required')
        return value

    @field_validator('tracking_url', mode='before')
    @classmethod
    def public_tracking(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError('Public HTTPS tracking URL required')
        try:
            p = urlsplit(value)
            host = p.hostname
            if (p.scheme != 'https' or not host or p.username is not None or p.password is not None
                    or p.port not in (None, 443) or '\\' in value or not value.isascii()
                    or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
                    or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal'))):
                raise ValueError
            _origin('https://' + p.netloc, production=True)
        except (ValueError, TypeError):
            raise ValueError('Public HTTPS tracking URL required') from None
        return value


async def customer_context_parcels(db, order):
    if not order.get('stripe_profile_ref'):
        return []
    rows = await db.select('commerce_fulfillment_tasks', params={
        'select': 'id,state,tracking_number,carrier,tracking_url,shipped_at,delivered_at',
        'order_id': 'eq.' + order['id'], 'order': 'created_at.asc,id.asc', 'limit': 101})
    if len(rows) > 100:
        raise HTTPException(409, 'Shipment summary requires review')
    # Never expose supplier/agent/cost/evidence/snapshots or unshipped references.
    fields = ('tracking_number', 'carrier', 'tracking_url', 'shipped_at', 'delivered_at')
    return [{'reference': row['id'], 'state': row['state'],
             **{key: row.get(key) if row['state'] in ('shipped', 'delivered') else None for key in fields}}
            for row in rows]


def create_context_dispatch_router(db, require_admin, notify):
    router = APIRouter(prefix='/api/admin/commerce/context', dependencies=[Depends(require_admin)])

    @router.get('/orders/{order_id}/tasks')
    async def tasks(order_id: UUID):
        return {'items': await db.select('commerce_fulfillment_tasks', params={
            'order_id': 'eq.' + str(order_id), 'order': 'created_at.asc,id.asc', 'limit': 100})}

    @router.get('/tasks/{task_id}/supplier-draft')
    async def supplier_draft(task_id: UUID, actor=Depends(require_admin)):
        rows = await db.select('commerce_fulfillment_tasks', params={'id': 'eq.' + str(task_id), 'limit': 2})
        if len(rows) != 1 or rows[0].get('id') != str(task_id):
            raise HTTPException(404, 'Fulfillment task not found')
        task = rows[0]
        orders = await db.select('orders', params={'id': 'eq.' + task['order_id'], 'limit': 2})
        if (len(orders) != 1 or orders[0].get('id') != task['order_id']
                or orders[0].get('is_test') is not False or not orders[0].get('stripe_profile_ref')):
            raise HTTPException(409, 'Production fulfillment context required')
        await db.insert('admin_audit', {'admin_user_id': actor['id'], 'action': 'commerce.context.supplier_draft',
            'resource': task['id'], 'metadata': {'order_id': task['order_id'], 'external_send_allowed': False}})
        return {'task_id': task['id'], 'order_id': task['order_id'], 'status': 'draft_not_transmitted',
            'external_send_allowed': False, 'supplier_id': task['supplier_id'], 'agent_id': task['agent_id'],
            'supplier_sku': task['supplier_sku'], 'quantity': task['quantity'],
            'source_snapshot': task['snapshot'], 'delivery_address': orders[0]['shipping_address'],
            'review_reasons': task.get('review_reasons', [])}

    @router.post('/tasks/{task_id}/advance')
    async def advance(task_id: UUID, payload: ContextDispatchInput, actor=Depends(require_admin)):
        result = await db.rpc('commerce_advance_context_task', {
            'p_actor': actor['id'], 'p_task_id': str(task_id),
            'p_expected_updated_at': payload.expected_updated_at.isoformat(), 'p_next': payload.next,
            'p_supplier_order_ref': payload.supplier_order_ref, 'p_tracking_number': payload.tracking_number,
            'p_carrier': payload.carrier, 'p_tracking_url': payload.tracking_url, 'p_evidence_ref': payload.evidence_ref})
        if (result.get('status_changed') is True and result.get('notification_kind') in ('order_processing', 'order_shipped', 'order_delivered')
                and result.get('notification_log_id')):
            await notify(result['notification_log_id'], actor['id'])
        return result

    return router
