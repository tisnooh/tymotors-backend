"""Owned customer quotes plus admin-only, test-only order preparation.

Quotes advertise sandbox request eligibility only when a test gateway is
configured. The separate customer checkout route must revalidate and reserve;
this is not financial approval. These quote endpoints make no external calls
and do not send supplier orders or email. Live checkout remains closed.
"""
from uuid import UUID
import re

from fastapi import APIRouter, Depends, Header, HTTPException

from app.commerce_models import CartQuoteInput
from app.commerce_quote_engine import CartQuoteError
from app.commerce_quote_service import CartQuoteService, public_quote
from app.supabase_rest import SupabaseError


def create_cart_quote_router(db, cart_for, optional_user, require_admin, get_settings,
                             rate_limit, attempts):
    router = APIRouter(prefix='/api', tags=['commerce-quotes'])

    def service():
        return CartQuoteService(db, get_settings().shipping_countries)

    def sandbox_checkout_available():
        settings = get_settings()
        return settings.stripe_test_mode and bool(re.fullmatch(
            r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+', settings.stripe_secret_key or ''))

    def refuse(error):
        # reasons may expose supplier operational details; only a safe engine code.
        raise HTTPException(409, {'code': error.code}) from None

    async def cart_and_owner(user, session_id):
        cart = await cart_for(user, session_id, create=False)
        if not cart:
            raise HTTPException(404, 'Cart not found')
        return cart

    @router.post('/cart/quote')
    async def create(payload: CartQuoteInput,
                     x_session_id: str | None = Header(default=None), user=Depends(optional_user)):
        cart = await cart_and_owner(user, x_session_id)
        # Bound stored snapshots and expensive evaluation per owner, not by a
        # spoofable user-supplied request key. No address or IP in the key.
        rate_limit(attempts, 'quote:' + cart['id'], 20, 3600)
        try:
            return public_quote(await service().create(payload, cart, user, x_session_id),
                sandbox_checkout_available=sandbox_checkout_available())
        except CartQuoteError as error:
            refuse(error)

    @router.get('/cart/quote/{quote_id}')
    async def read(quote_id: UUID, x_session_id: str | None = Header(default=None),
                   user=Depends(optional_user)):
        cart = await cart_and_owner(user, x_session_id)
        try:
            row = await service().read(quote_id, cart, user, x_session_id)
            if row is None:
                raise HTTPException(404, 'Quote not found')
            return public_quote(row, sandbox_checkout_available=sandbox_checkout_available())
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
