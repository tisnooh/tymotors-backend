"""Private, test-only provider reads. No settlement, retry, refund or release.

The session identity comes from server storage, never a query/body parameter.
Provider reads and owned-transport cleanup have separate deadlines. Cleanup
failure is reported without masking the business outcome or exposing secrets.
"""
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import stripe

from app.commerce_payment_observation import CommercePaymentObservation, PaymentObservationError
from app.commerce_payment_service import CommercePaymentError, TestStripeGateway

logger = logging.getLogger(__name__)


def create_payment_observation_router(db, require_admin, get_settings, rate_limit, attempts):
    router = APIRouter(prefix='/api/admin/commerce', tags=['admin-payment-observation'])

    @router.get('/checkout-attempts/{attempt_id}/provider-observation')
    async def observe(attempt_id: UUID, actor=Depends(require_admin)):
        settings = get_settings()
        if not settings.stripe_test_mode:
            raise HTTPException(409, 'Provider observation is test-only')
        if not settings.stripe_secret_key:
            raise HTTPException(503, 'Isolated Stripe test credentials are not configured')
        rate_limit(attempts, 'payment-observe:' + actor['id'], 20, 60)
        transport = stripe.HTTPXClient(timeout=20)
        try:
            gateway = TestStripeGateway(settings.stripe_secret_key, http_client=transport)
            return await asyncio.wait_for(
                CommercePaymentObservation(db, gateway).inspect(attempt_id), timeout=25)
        except CommercePaymentError:
            raise HTTPException(503, 'Isolated Stripe test credentials are not configured') from None
        except PaymentObservationError as error:
            raise HTTPException(error.status_code, {'code': error.code}) from None
        except TimeoutError:
            raise HTTPException(502, {'code': 'provider_observation_unavailable'}) from None
        finally:
            try:
                await asyncio.wait_for(transport.close_async(), timeout=3)
            except Exception:
                # Cleanup must neither overwrite the business outcome nor leak
                # an exception containing transport configuration/credentials.
                logger.warning('Sandbox observation transport cleanup requires review')

    return router
