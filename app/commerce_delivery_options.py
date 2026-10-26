"""Read-only discovery of admissible modes for the exact owner's FR cart.

No price defaults, writes, persisted address, reservation or provider operation.
The selected mode must still pass the ordinary quote and checkout revalidations.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from uuid import UUID

from app.commerce_models import DELIVERY_DISCOVERY_MODE
from app.commerce_quote_engine import CartQuoteError, build_cart_quote
from app.commerce_quote_service import CartQuoteService


class CartDeliveryOptions:
    def __init__(self, db, allowed_countries):
        self.db, self.allowed_countries = db, allowed_countries

    async def discover(self, payload, cart, user, guest):
        owner = CartQuoteService.owner(cart, user, guest)
        destination = payload.destination
        # France launch only. Configuration alone must not enable other countries.
        if destination.country != 'FR' or 'FR' not in self.allowed_countries:
            raise CartQuoteError('destination_not_supported')
        source = await self.db.rpc('commerce_cart_context', {
            'p_cart_id':cart['id'], **owner, 'p_country':'FR',
            'p_mode':DELIVERY_DISCOVERY_MODE, 'p_postal_code':destination.postal_code,
        })
        if (not isinstance(source,dict) or not isinstance(source.get('cart'),dict)
                or source['cart'].get('id') != cart['id']
                or source.get('country') != 'FR' or source.get('postal_code') != destination.postal_code
                or source.get('mode') != DELIVERY_DISCOVERY_MODE):
            raise CartQuoteError('invalid_quote_context')
        CartQuoteService.owner(source['cart'], user, guest)
        offers, lines = source.get('offers'), source.get('cart_items')
        if (not isinstance(offers,list) or len(offers)>1000 or not isinstance(lines,list)
                or not 1<=len(lines)<=100 or any(not isinstance(line,dict) for line in lines)):
            raise CartQuoteError('invalid_quote_context')
        try:
            variants={str(UUID(line['variant_id'])) for line in lines}
            offer_ids=[]
            for offer in offers:
                if not isinstance(offer,dict) or str(UUID(offer['variant_id'])) not in variants:
                    raise ValueError
                identity=str(UUID(offer['id']))
                if not UUID(identity).int or identity in offer_ids:
                    raise ValueError
                offer_ids.append(identity)
        except (ValueError,KeyError,TypeError,AttributeError):
            raise CartQuoteError('invalid_quote_context') from None
        rates=[]
        # Bound URI length and exact counts. Never truncate a catalogue page and
        # silently choose an arbitrary first mode or rate.
        for offset in range(0,len(offer_ids),40):
            batch=offer_ids[offset:offset+40]
            page=await self.db.page('shipping_rates',params={
                'offer_id':'in.('+','.join(batch)+')','country':'eq.FR',
                'verification_state':'eq.verified','order':'id.asc'},page=1,limit=1000)
            rows,total=page.get('items'),page.get('total')
            if (not isinstance(rows,list) or type(total) is not int or not 0<=total<=1000
                    or total!=len(rows) or len(rates)+total>1000):
                raise CartQuoteError('incomplete_delivery_options')
            for row in rows:
                if (not isinstance(row,dict) or row.get('offer_id') not in batch
                        or row.get('country')!='FR' or row.get('verification_state')!='verified'
                        or not isinstance(row.get('mode'),str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',row['mode'])):
                    raise CartQuoteError('invalid_quote_context')
            rates.extend(rows)
        modes=sorted({row['mode'] for row in rates if row['mode']!=DELIVERY_DISCOVERY_MODE})
        if len(modes)>10:
            raise CartQuoteError('incomplete_delivery_options')
        options=[]
        now=datetime.now(timezone.utc)
        for mode in modes:
            context={**deepcopy(source),'mode':mode,'rates':[row for row in rates if row['mode']==mode]}
            try:
                evaluated=build_cart_quote(context,now=now)
            except CartQuoteError:
                # No private reasons, supplier identity, costs or data from other
                # baskets reach the customer, including in an empty result.
                continue
            expiry=min(datetime.fromisoformat(evaluated['valid_until']),now+timedelta(minutes=45))
            options.append({'mode':mode,'currency':evaluated['currency'],
                **{key:evaluated[key] for key in ('subtotal_cents','shipping_cents','tax_cents','total_cents')},
                'expires_at':expiry.isoformat()})
        return {'country':'FR','options':options,'requires_quote':True}
