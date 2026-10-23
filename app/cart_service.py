"""Cart projection from current server data, preserving exact line identities."""
from collections import defaultdict

from fastapi import HTTPException

from app.catalog_availability import purchase_availability
from app.compatibility import check_compatibility
from app.schemas import VehicleSelection


class CartService:
    def __init__(self, db, catalog, settings):
        self.db, self.catalog, self.settings = db, catalog, settings

    async def response(self, cart):
        empty = {'items': [], 'subtotal': 0, 'shipping': 0, 'total': 0, 'currency': 'EUR',
                 'shipping_status': 'empty', 'checkout_available': False}
        if not cart:
            return empty
        page = await self.db.page('cart_items', params={'select': '*', 'cart_id': f"eq.{cart['id']}",
                                  'order': 'created_at.asc,id.asc'}, page=1, limit=100)
        if page['total'] > 100 or len(page['items']) != page['total']:
            raise HTTPException(409, 'Incomplete cart data; checkout refused')
        lines = page['items']
        if not lines:
            return {**empty, 'currency': cart.get('currency', 'EUR')}
        product_ids = sorted({line['product_id'] for line in lines})
        products = await self.catalog.hydrate_products(await self.db.select('products', params={
            'select': '*', 'id': 'in.(' + ','.join(product_ids) + ')'}))
        by_product = {product['id']: product for product in products}
        variants_page = await self.db.page('product_variants', params={'product_id': 'in.(' + ','.join(product_ids) + ')',
                                           'order': 'id.asc'}, page=1, limit=1000)
        if variants_page['total'] > 1000 or len(variants_page['items']) != variants_page['total']:
            raise HTTPException(409, 'Incomplete variant data; checkout refused')
        by_variant = {variant['id']: variant for variant in variants_page['items']}
        products_with_variants = {variant['product_id'] for variant in by_variant.values() if variant['status'] != 'archived'}
        linked_ids = sorted({line['variant_id'] for line in lines if line.get('variant_id')})
        links = []
        if linked_ids:
            link_page = await self.db.page('variant_compatibilities', params={
                'variant_id': 'in.(' + ','.join(linked_ids) + ')', 'order': 'variant_id.asc,compatibility_id.asc'}, page=1, limit=1000)
            if link_page['total'] > 1000 or len(link_page['items']) != link_page['total']:
                raise HTTPException(409, 'Incomplete variant fitment data; checkout refused')
            links = link_page['items']
        quantities = defaultdict(int)
        for line in lines:
            quantities[(line['product_id'], line.get('variant_id'))] += line['quantity']
        items, subtotal_cents, blocked = [], 0, False
        for line in lines:
            product = by_product.get(line['product_id'])
            if not product:
                raise HTTPException(409, 'A cart product is missing; reload the cart')
            view = purchase_availability(product, self.settings)
            variant_id, reason = line.get('variant_id'), None
            if variant_id:
                variant = by_variant.get(variant_id)
                if not variant or variant['product_id'] != product['id']:
                    # A physically missing/foreign row violates the FK/trigger;
                    # never conceal that integrity failure with a base SKU.
                    raise HTTPException(409, 'A cart variant is unavailable; remove that exact line')
                rule_ids = {link['compatibility_id'] for link in links if link['variant_id'] == variant_id}
                view = {**view, 'sku': variant['sku'], 'variant_name': variant['name'],
                        'price_cents': variant['price_cents'], 'price': variant['price_cents'] / 100,
                        'stock': variant['stock'], 'currency': variant['currency'], 'test_purchase': False,
                        'purchase_available': product['status'] == 'active' and product.get('is_verified') is True,
                        'compatibilities': [rule for rule in product.get('compatibilities', []) if rule['id'] in rule_ids]}
                if (variant['status'] != 'active' or variant.get('is_verified') is not True
                        or not variant.get('evidence_ref') or variant['currency'] != product['currency']
                        or product['status'] != 'active' or product.get('is_verified') is not True):
                    reason = 'variant_not_verified_active'
                stock_limit = variant['stock']
            else:
                if product['id'] in products_with_variants:
                    reason = 'explicit_variant_selection_required'
                stock_limit = 20 if view.get('test_purchase') else product.get('stock', 0)
            if view['currency'] != cart.get('currency', 'EUR'):
                reason = 'cart_currency_mismatch'
            # Sandbox drafts have no real inventory. The 20 cap is per line,
            # matching the SQL demonstration gate, not an invented aggregate stock.
            other_quantity = 0 if view.get('test_purchase') else quantities[(line['product_id'], variant_id)] - line['quantity']
            maximum = min(20, max(0, stock_limit - other_quantity))
            if line['quantity'] > maximum or not view.get('purchase_available'):
                reason = reason or 'stock_or_product_unavailable'
            facts = {key: value for key, value in (line.get('selected_vehicle') or {}).items() if key in VehicleSelection.model_fields}
            vehicle = VehicleSelection.model_validate(facts) if facts else None
            compatibility_result = check_compatibility(view, vehicle) if vehicle else {'status': 'unknown', 'reason': 'No vehicle selected'}
            if variant_id and not variant.get('requires_vehicle', True):
                compatibility_result = {'status': 'not_required', 'reason': 'No vehicle-specific fitment required'}
            line_total_cents = view['price_cents'] * line['quantity']
            subtotal_cents += line_total_cents
            blocked = blocked or bool(reason)
            items.append({**view, 'product_id': product['id'], 'cart_item_id': line['id'], 'variant_id': variant_id,
                          'quantity': line['quantity'], 'max_order_quantity': maximum,
                          'purchase_available': not reason, 'line_blocked_reason': reason,
                          'selected_vehicle': {**vehicle.model_dump(), 'compatibility_status': compatibility_result['status'],
                                               'compatibility_reason': compatibility_result.get('reason')} if vehicle else None,
                          'compatibility_result': compatibility_result, 'line_total': line_total_cents / 100})
        # Legacy flat rates are retained only for the existing TEST demonstration.
        # Variant quotes need a confirmed destination/rate before checkout exists.
        needs_quote = bool(linked_ids) or not self.settings.stripe_test_mode
        shipping_cents = (0 if subtotal_cents >= self.settings.free_shipping_threshold_cents else self.settings.shipping_rate_cents)
        return {'items': items, 'subtotal': subtotal_cents / 100,
                'shipping': None if needs_quote else shipping_cents / 100,
                'total': None if needs_quote else (subtotal_cents + shipping_cents) / 100,
                'currency': cart.get('currency', 'EUR'),
                'shipping_status': 'requires_quote' if needs_quote else 'legacy_test_estimate',
                'checkout_available': not blocked and not needs_quote}
