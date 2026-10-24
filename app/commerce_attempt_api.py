"""Admin-only durable test preparation. No SDK, payment or frontend change."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.commerce_attempt_service import CheckoutAttemptError, CheckoutAttemptService


def create_checkout_attempt_router(db, require_admin, get_settings, rate_limit, attempts):
    router = APIRouter(prefix='/api/admin/commerce', tags=['admin-checkout-preparation'])

    def service():
        return CheckoutAttemptService(db, get_settings().frontend_url)

    def ensure_test_mode():
        if not get_settings().stripe_test_mode:
            raise HTTPException(409, 'Test preparation is disabled outside test mode')

    def refuse(error):
        raise HTTPException(409, {'code': error.code}) from None

    @router.post('/orders/{order_id}/checkout-attempt')
    async def prepare(order_id: UUID, actor=Depends(require_admin)):
        ensure_test_mode()
        rate_limit(attempts, 'checkout-prepare:' + str(order_id), 20, 3600)
        try:
            return await service().prepare(actor['id'], order_id)
        except CheckoutAttemptError as error:
            refuse(error)

    @router.get('/checkout-attempts/{attempt_id}')
    async def read(attempt_id: UUID, _actor=Depends(require_admin)):
        try:
            result = await service().read(attempt_id)
            if result is None:
                raise HTTPException(404, 'Checkout attempt not found')
            return result
        except CheckoutAttemptError as error:
            refuse(error)

    @router.post('/checkout-attempts/{attempt_id}/cancel-draft')
    async def cancel(attempt_id: UUID, actor=Depends(require_admin)):
        ensure_test_mode()
        try:
            return await service().cancel_draft(actor['id'], attempt_id)
        except CheckoutAttemptError as error:
            refuse(error)

    return router
