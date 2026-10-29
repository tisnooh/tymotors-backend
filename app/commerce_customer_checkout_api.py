"""Customer sandbox checkout using owned immutable quotes; live stays closed."""
import asyncio
import hashlib
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import stripe

from app.commerce_customer_checkout import CustomerCheckoutError, CustomerTestCheckout, customer_owner
from app.commerce_models import StrictInput
from app.commerce_payment_service import CommercePaymentError, TestStripeGateway
from app.commerce_context_payments import ContextCustomerCheckout
from app.commerce_stripe_gateway import AuthenticatedStripeGateway, StripeGatewayError
from app.commerce_webhook_profiles import load_webhook_profiles, WebhookProfileError
from app.supabase_rest import SupabaseError

logger=logging.getLogger(__name__)


class CustomerCheckoutInput(StrictInput):
    request_key: UUID


def create_customer_checkout_router(db,cart_for,optional_user,get_settings,rate_limit,bucket,client_key):
    router=APIRouter(prefix='/api',tags=['customer-test-checkout'])

    @router.post('/cart/quote/{quote_id}/checkout')
    async def checkout(quote_id:UUID,payload:CustomerCheckoutInput,request:Request,
                       x_session_id:str|None=Header(default=None),user=Depends(optional_user)):
        settings=get_settings()
        profile = None
        if settings.stripe_checkout_profile:
            try:
                profiles = load_webhook_profiles(settings.stripe_webhook_profiles_json,
                                                 legacy_secret=settings.stripe_webhook_secret)
                profile = next((p for p in profiles if p.reference == settings.stripe_checkout_profile), None)
                if profile is None or (profile.context.mode == 'sandbox') is not settings.stripe_test_mode:
                    raise WebhookProfileError('checkout_profile_missing')
            except WebhookProfileError:
                raise HTTPException(503, 'Stripe checkout profile is not configured') from None
        if not settings.stripe_test_mode and profile is None:
            raise HTTPException(409,'Live commerce checkout is not approved')
        if not settings.stripe_secret_key:
            raise HTTPException(503,'Isolated Stripe test checkout is not configured')
        if profile is None and not settings.stripe_webhook_secret:
            raise HTTPException(503,'Signed Stripe webhook is not configured')
        rate_limit(bucket,'customer-checkout:ip:'+client_key(request),10,60)
        try:
            owner=customer_owner(user,request.headers.get('authorization'),x_session_id)
        except CustomerCheckoutError as error:
            raise HTTPException(error.status_code,{'code':error.code}) from None
        actor=owner['p_user_id'] or hashlib.sha256(owner['p_guest_session'].encode()).hexdigest()
        rate_limit(bucket,'customer-checkout:owner:'+actor,10,60)
        cart=await cart_for(user,x_session_id,create=False)
        if not cart:
            raise HTTPException(409,{'code':'checkout_unavailable'})
        rate_limit(bucket,'customer-checkout:cart:'+cart['id'],20,3600)
        transport=stripe.HTTPXClient(timeout=20)
        try:
            if profile is not None:
                gateway=AuthenticatedStripeGateway(settings.stripe_secret_key,profile.context,http_client=transport)
                return await asyncio.wait_for(ContextCustomerCheckout(db,profile).start(
                    quote_id,payload.request_key,cart,user,x_session_id,owner,gateway=gateway,
                    origin=settings.frontend_url,allowed_countries=settings.shipping_countries),timeout=50)
            gateway=TestStripeGateway(settings.stripe_secret_key,http_client=transport)
            return await asyncio.wait_for(CustomerTestCheckout(db,gateway,settings.frontend_url,
                settings.shipping_countries).start(quote_id,payload.request_key,cart,user,x_session_id,owner),timeout=50)
        except CustomerCheckoutError as error:
            raise HTTPException(error.status_code,{'code':error.code}) from None
        except CommercePaymentError:
            raise HTTPException(503,'Isolated Stripe test checkout is not configured') from None
        except StripeGatewayError:
            raise HTTPException(502,{'code':'checkout_requires_inspection'}) from None
        except (SupabaseError, ValueError, KeyError, TypeError):
            raise HTTPException(409,{'code':'checkout_unavailable'}) from None
        except TimeoutError:
            # No cancellation/hold release: the provider may have created a session.
            raise HTTPException(502,{'code':'checkout_requires_inspection'}) from None
        finally:
            try:
                await asyncio.wait_for(transport.close_async(),timeout=3)
            except Exception:
                logger.warning('Customer sandbox transport cleanup requires review')

    return router
