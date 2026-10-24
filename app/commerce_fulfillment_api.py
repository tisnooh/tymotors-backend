"""Existing design unchanged. Admin private plan and strictly simulated transitions."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from app.commerce_models import StrictInput
from app.commerce_fulfillment import FulfillmentPlanError, plan_test_fulfillment
from app.supabase_rest import SupabaseError


class SimulatedTransition(StrictInput):
    expected: Literal['prepared','received_by_agent','quality_checked','shipped','delivered']
    next: Literal['received_by_agent','quality_checked','shipped','delivered']
    tracking_number: str | None = Field(default=None, pattern=r'^SIM-[A-Za-z0-9_-]{1,100}$')


def create_test_fulfillment_router(db, require_admin, get_settings):
    router = APIRouter(prefix='/api/admin/commerce', tags=['admin-test-fulfillment'])

    @router.get('/orders/{order_id}/fulfillment-plan')
    async def plan(order_id: UUID, _actor=Depends(require_admin)):
        orders = await db.select('orders', params={'id': f'eq.{order_id}', 'limit': 1})
        if not orders:
            raise HTTPException(404, 'Order not found')
        lines = await db.select('commerce_order_lines', params={'order_id': f'eq.{order_id}'})
        try:
            return {'is_test': True, 'external_send_allowed': False,
                    'tasks': plan_test_fulfillment(orders[0], lines)}
        except FulfillmentPlanError as error:
            raise HTTPException(409, str(error)) from None

    @router.post('/test-tasks/{task_id}/simulate')
    async def advance(task_id: UUID, payload: SimulatedTransition, actor=Depends(require_admin)):
        if not get_settings().stripe_test_mode:
            raise HTTPException(409, 'Simulation disabled outside test mode')
        try:
            task = await db.rpc('commerce_advance_test_task', {'p_actor': actor['id'], 'p_task_id': str(task_id),
                'p_expected': payload.expected, 'p_next': payload.next, 'p_tracking_number': payload.tracking_number})
        except SupabaseError as error:
            if error.status_code in (400,403,404,409,422):
                raise HTTPException(409, 'Simulated task conflict') from None
            raise
        return {k: task[k] for k in ('id','order_id','state','is_test','tracking_number')}

    return router
