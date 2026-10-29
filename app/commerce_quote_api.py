"""Owned customer quotes plus admin-only, test-only order preparation.

Quotes advertise sandbox request eligibility only when a test gateway is
configured. The separate customer checkout route must revalidate and reserve;
this is not financial approval. These quote endpoints make no external calls
and do not send supplier orders or email. Live checkout remains closed.
"""
from uuid import UUID
import re

from fastapi import APIRouter, Depends, Header, HTTPException

from app.commerce_models import CartQuoteInput, CartDeliveryOptionsInput
from app.commerce_delivery_options import CartDeliveryOptions
from app.commerce_quote_engine import CartQuoteError
from app.commerce_quote_service import CartQuoteService, public_quote
from app.supabase_rest import SupabaseError
from app.commerce_webhook_profiles import load_webhook_profiles, WebhookProfileError


def create_cart_quote_router(db, cart_for, optional_user, require_admin, get_settings,
                             rate_limit, attempts):
    router = APIRouter(prefix='/api', tags=['commerce-quotes'])

    def service():
        return CartQuoteService(db, get_settings().shipping_countries)

    async def sandbox_checkout_available():
        settings = get_settings()
        if settings.stripe_checkout_profile:
            try:
                profiles = load_webhook_profiles(settings.stripe_webhook_profiles_json,
                                                 legacy_secret=settings.stripe_webhook_secret)
                profile = next((p for p in profiles if p.reference == settings.stripe_checkout_profile), None)
                expected = 'sandbox' if settings.stripe_test_mode else 'production'
                key_pattern = r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+' if settings.stripe_test_mode else r'(sk|rk)_live_[A-Za-z0-9_]+'
                configured = bool(profile is not None and profile.context.mode == expected
                                  and re.fullmatch(key_pattern, settings.stripe_secret_key or ''))
                if not configured or settings.stripe_test_mode:
                    return configured
                # This indication is never purchase authority; the transactional
                # claim rechecks the current gate before any provider write.
                return await db.rpc('commerce_context_checkout_enabled', {
                    'p_is_test': False, 'p_stripe_account_id': profile.context.stripe_account_id,
                    'p_profile_ref': profile.reference}) is True
            except (WebhookProfileError, SupabaseError):
                return False
        return settings.stripe_test_mode and bool(re.fullmatch(
            r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+', settings.stripe_secret_key or ''))

    def refuse(error):
        # reasons may expose supplier operational details; only a safe engine code.
        raise HTTPException(409, {'code': error.code}) from None

    async def cart_and_owner(user, session_id, authorization):
        # HTTPBearer(auto_error=False) treats a wrong/empty scheme as absent.
        # An explicit invalid auth header must never downgrade to guest access.
        if authorization is not None and user is None:
            raise HTTPException(401, 'Invalid authentication')
        cart = await cart_for(user, session_id, create=False)
        if not cart:
            raise HTTPException(404, 'Cart not found')
        return cart

    @router.post('/cart/delivery-options')
    async def delivery_options(payload: CartDeliveryOptionsInput,
                               authorization: str | None = Header(default=None),
                               x_session_id: str | None = Header(default=None), user=Depends(optional_user)):
        cart = await cart_and_owner(user, x_session_id, authorization)
        rate_limit(attempts, 'delivery-options:' + cart['id'], 20, 3600)
        try:
            return await CartDeliveryOptions(db,get_settings().shipping_countries).discover(
                payload,cart,user,x_session_id)
        except CartQuoteError as error:
            refuse(error)
        except SupabaseError:
            raise HTTPException(409, {'code':'delivery_options_unavailable'}) from None

    @router.post('/cart/quote')
    async def create(payload: CartQuoteInput,
                     authorization: str | None = Header(default=None),
                     x_session_id: str | None = Header(default=None), user=Depends(optional_user)):
        cart = await cart_and_owner(user, x_session_id, authorization)
        # Bound stored snapshots and expensive evaluation per owner, not by a
        # spoofable user-supplied request key. No address or IP in the key.
        rate_limit(attempts, 'quote:' + cart['id'], 20, 3600)
        try:
            return public_quote(await service().create(payload, cart, user, x_session_id),
                sandbox_checkout_available=await sandbox_checkout_available())
        except CartQuoteError as error:
            refuse(error)

    @router.get('/cart/quote/{quote_id}')
    async def read(quote_id: UUID, x_session_id: str | None = Header(default=None),
                   authorization: str | None = Header(default=None),
                   user=Depends(optional_user)):
        cart = await cart_and_owner(user, x_session_id, authorization)
        try:
            row = await service().read(quote_id, cart, user, x_session_id)
            if row is None:
                raise HTTPException(404, 'Quote not found')
            return public_quote(row, sandbox_checkout_available=await sandbox_checkout_available())
        except CartQuoteError as error:
            refuse(error)

    @router.post('/admin/commerce/quotes/{quote_id}/prepare-test-order')
    async def prepare_test_order(quote_id: UUID, actor=Depends(require_admin)):
        if not get_settings().stripe_test_mode:
            raise HTTPException(409, 'Test order preparation is disabled outside test mode')
        rows = await db.select('commerce_quotes', params={'id': f'eq.{quote_id}', 'limit': 1})
        if not rows:
            raise HTTPException(404, 'Quote not found')
        row = rows[0]
        try:
            result = await db.rpc('commerce_order_from_quote', {
                'p_quote_id': str(quote_id), 'p_user_id': row.get('owner_user_id'),
                'p_guest_session': row.get('owner_guest_session'), 'p_is_test': True,
                'p_actor': actor['id'],
            })
        except SupabaseError as error:
            if error.status_code in {400, 403, 404, 409, 422}:
                raise HTTPException(409, 'Quote changed or unavailable for a test order') from None
            raise
        # Do not expose private line snapshots or future RPC fields by accident.
        return {key: result[key] for key in ('order_id', 'order_number', 'is_test')}

    return router
