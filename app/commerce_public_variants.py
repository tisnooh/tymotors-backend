"""Customer-visible variant identities, never supplier terms or sale approval.

Selection is separate from shipping, fitment and payment authorization. Missing
or ambiguous variants must not downgrade an addition to the legacy base SKU.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response


def create_public_variant_router(db, catalog, get_settings):
    router = APIRouter(prefix='/api', tags=['product-variants'])

    @router.get('/products/{product_id}/variants')
    async def variants(product_id: UUID, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        identity = str(product_id)
        product = await catalog.product_by('id', identity, public_only=False)
        settings = get_settings()
        if (not product or product.get('status') not in {'draft', 'active'}
                or (product['status'] == 'draft' and not settings.test_catalog_available)):
            raise HTTPException(404, 'Product not found')
        result = {'product_id': identity, 'variants': [], 'requires_quote': True,
                  'checkout_available': False, 'test_mode': settings.stripe_test_mode}
        # Previewing a draft is not a licence to select an unverified SKU.
        if product['status'] != 'active' or product.get('is_verified') is not True:
            return result
        page = await db.page('product_variants', params={
            'product_id': 'eq.' + identity, 'status': 'eq.active',
            'is_verified': 'eq.true', 'order': 'id.asc'}, page=1, limit=100)
        rows, total = page.get('items'), page.get('total')
        if (not isinstance(rows, list) or type(total) is not int
                or total < 0 or total > 100 or len(rows) != total):
            raise HTTPException(409, 'Incomplete variant data; selection refused')
        seen = set()
        for row in rows:
            try:
                variant_id = str(UUID(row['id']))
                if (variant_id in seen or str(UUID(row['product_id'])) != identity
                        or not UUID(variant_id).int):
                    raise ValueError
                seen.add(variant_id)
                if (row.get('status') != 'active' or row.get('is_verified') is not True
                        or not isinstance(row.get('evidence_ref'), str) or not row['evidence_ref'].strip()):
                    continue
                if (row.get('currency') != 'EUR' or type(row.get('price_cents')) is not int
                        or not 0 <= row['price_cents'] <= 2_000_000_000
                        or type(row.get('requires_vehicle')) is not bool):
                    raise ValueError
                for field, maximum in (('sku',100), ('name',160)):
                    value = row.get(field)
                    if (not isinstance(value,str) or not value.strip() or len(value) > maximum
                            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                        raise ValueError
                attributes = row.get('attributes')
                if (not isinstance(attributes,dict) or len(attributes) > 30
                        or any(not isinstance(k,str) or not isinstance(v,str)
                            or len(k) > 100 or len(v) > 500 for k,v in attributes.items())):
                    raise ValueError
                result['variants'].append({
                    'id':variant_id, 'product_id':identity, 'sku':row['sku'],
                    'name':row['name'], 'attributes':attributes, 'currency':'EUR',
                    'price_cents':row['price_cents'], 'requires_vehicle':row['requires_vehicle'],
                    'status':'active', 'is_verified':True,
                })
            except (KeyError, TypeError, ValueError, AttributeError):
                raise HTTPException(409, 'Invalid variant data; selection refused') from None
        return result

    return router
