"""Persistent private quotes, explicitly NOT payment or stock reservations.

Source rows stay server-side. Only an allowlisted projection can reach customers.
No fallback shipping, automatic re-selection on retries, or financial commitment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.commerce_models import CartQuoteInput
from app.commerce_quote_engine import CartQuoteError, build_cart_quote
from app.product_image_policy import permitted_image
from app.supabase_rest import SupabaseError


def public_quote(row: dict, now: datetime | None = None, *, sandbox_checkout_available: bool = False) -> dict:
    """An explicit contract: never return source_context, evaluations or addresses."""
    now = now or datetime.now(timezone.utc)
    try:
        expiry = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError('Naive quote expiry')
        status = row['state']
        if status not in {'ready', 'superseded', 'consumed'}:
            raise ValueError('Invalid quote state')
        if status == 'ready' and expiry <= now:
            status = 'expired'
        lines = [{key: line.get(key) for key in (
            'cart_item_id', 'product_id', 'variant_id', 'quantity',
            'unit_amount_cents', 'sku', 'product_name', 'product_slug',
            'image_url', 'variant_name', 'variant_attributes',
        )} for group in row['payload']['groups'] for line in group['lines']]
        for line in lines:
            # Enforce the existing rights policy again on historical snapshots,
            # without changing any source image or the immutable order history.
            if not isinstance(line['image_url'], str) or not permitted_image(line['image_url']):
                line['image_url'] = None
        return {
            'quote_id': str(UUID(row['id'])), 'status': status,
            'expires_at': expiry.isoformat(), 'currency': row['currency'],
            'country': row['country'], 'mode': row['mode'],
            'subtotal_cents': row['subtotal_cents'], 'shipping_cents': row['shipping_cents'],
            'tax_cents': row['tax_cents'], 'total_cents': row['total_cents'],
            'items': lines, 'checkout_available': sandbox_checkout_available is True and status == 'ready',
            'requires_revalidation': True,
            'scope': 'persisted_quote_not_payment_or_reservation',
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise CartQuoteError('invalid_persisted_quote') from None


class CartQuoteService:
    def __init__(self, db, allowed_countries):
        self.db = db
        self.allowed_countries = allowed_countries

    @staticmethod
    def owner(cart, user, guest_session):
        # Verify independently of the cart lookup. Authentication takes priority:
        # an authenticated account can never operate on a supplied guest's cart.
        if user:
            if cart.get('user_id') != user['id'] or cart.get('guest_session_id') is not None:
                raise CartQuoteError('cart_not_accessible')
            return {'p_user_id': user['id'], 'p_guest_session': None}
        if (cart.get('user_id') is not None or not guest_session
                or cart.get('guest_session_id') != guest_session):
            raise CartQuoteError('cart_not_accessible')
        return {'p_user_id': None, 'p_guest_session': guest_session}

    @staticmethod
    def check_row_owner(row, cart, owner):
        if (row.get('cart_id') != cart['id'] or row.get('owner_user_id') != owner['p_user_id']
                or row.get('owner_guest_session') != owner['p_guest_session']):
            raise CartQuoteError('quote_not_accessible')

    async def read(self, quote_id, cart, user, guest_session):
        owner = self.owner(cart, user, guest_session)
        rows = await self.db.select('commerce_quotes', params={
            'id': f'eq.{quote_id}', 'cart_id': f"eq.{cart['id']}", 'limit': 1,
        })
        if not rows:
            return None
        self.check_row_owner(rows[0], cart, owner)
        return rows[0]

    async def create(self, payload: CartQuoteInput, cart, user, guest_session):
        owner = self.owner(cart, user, guest_session)
        destination = payload.destination.model_dump(mode='json')
        if destination['country'] not in self.allowed_countries:
            raise CartQuoteError('destination_not_supported')
        rows = await self.db.select('commerce_quotes', params={
            'cart_id': f"eq.{cart['id']}", 'request_key': f'eq.{payload.request_key}', 'limit': 1,
        })
        if rows:
            row = rows[0]
            self.check_row_owner(row, cart, owner)
            if row.get('destination') != destination or row.get('mode') != payload.mode:
                raise CartQuoteError('request_key_conflict')
            # A retry restores the original terms, even after catalogue changes.
            # Expired/consumed/superseded quotes remain unusable for new orders.
            return row
        source = await self.db.rpc('commerce_cart_context', {
            'p_cart_id': cart['id'], **owner, 'p_country': destination['country'],
            'p_mode': payload.mode, 'p_postal_code': destination['postal_code'],
        })
        private_payload = build_cart_quote(source)
        try:
            return await self.db.rpc('commerce_save_quote', {
                'p_cart_id': cart['id'], **owner, 'p_request_key': str(payload.request_key),
                'p_destination': destination, 'p_mode': payload.mode,
                'p_source': source, 'p_payload': private_payload,
            })
        except SupabaseError as error:
            # Database messages may contain private refs/values; never echo them.
            if error.status_code in {400, 403, 404, 409, 422}:
                raise CartQuoteError('quote_changed_or_unavailable') from None
            raise
