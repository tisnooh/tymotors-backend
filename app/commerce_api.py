"""Private operational API, attached to the existing admin boundary.

This foundation does not activate products, write public prices, issue supplier
orders, send messages, or authorize checkout. UI integration remains explicit.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from app.commerce_models import Kind, MODELS, QuoteInput, SaveInput, TABLES
from app.commerce_pricing import quote_offer, select_offers


def create_commerce_router(db, catalog, require_admin, allowed_countries):
    router = APIRouter(prefix='/api/admin/commerce', tags=['admin-commerce'])

    async def complete_rows(table, params, maximum):
        # PostgREST can cap rows below the requested limit. Exact counts and
        # completeness checks prevent hidden restrictions from disappearing.
        rows, expected_total, page_number, chunk = [], None, 1, 100
        while True:
            page = await db.page(table, params={**params, 'order': 'id.asc'}, page=page_number, limit=chunk)
            total = page['total']
            if total > maximum or (expected_total is not None and total != expected_total):
                raise HTTPException(409, 'Commerce associations changed or exceed evaluation limits')
            expected_total = total
            expected_count = min(chunk, max(0, total - len(rows)))
            if len(page['items']) != expected_count:
                raise HTTPException(409, 'Incomplete commerce data; evaluation refused')
            rows.extend(page['items'])
            if len(rows) == total:
                if len({row['id'] for row in rows}) != total:
                    raise HTTPException(409, 'Commerce data changed during evaluation')
                return rows
            page_number += 1

    @router.post('/quote')
    async def quote(payload: QuoteInput, _admin=Depends(require_admin)):
        if payload.country not in allowed_countries:
            return {'status': 'blocked', 'reasons': ['destination_not_supported'], 'offers': []}
        variants = await db.select('product_variants', params={'id': f'eq.{payload.variant_id}', 'limit': 1})
        if not variants:
            raise HTTPException(404, 'Variant not found')
        variant = variants[0]
        product, offers, links = await asyncio.gather(
            catalog.product_by('id', variant['product_id'], public_only=False),
            complete_rows('supplier_offers', {'variant_id': f'eq.{payload.variant_id}'}, 100),
            db.page('variant_compatibilities', params={'variant_id': f'eq.{payload.variant_id}', 'order': 'compatibility_id.asc'}, page=1, limit=100),
        )
        if not product:
            raise HTTPException(404, 'Product not found')
        if links['total'] > 100 or len(links['items']) != links['total']:
            raise HTTPException(409, 'Commerce associations exceed supported evaluation size')
        variant = {**variant, 'compatibility_ids': [link['compatibility_id'] for link in links['items']]}
        if not offers:
            return {'status': 'blocked', 'reasons': ['supplier_offer_missing'], 'offers': []}
        ids = ','.join(str(UUID(offer['id'])) for offer in offers)
        agent_ids = sorted({str(UUID(offer['responsible_agent_id'])) for offer in offers if offer.get('responsible_agent_id')})
        rates, agents = await asyncio.gather(
            complete_rows('shipping_rates', {'offer_id': f'in.({ids})', 'country': f'eq.{payload.country}',
                                             'mode': f'eq.{payload.mode}'}, 1000),
            db.select('commerce_agents', params={'id': 'in.(' + ','.join(agent_ids) + ')'})
            if agent_ids else asyncio.sleep(0, result=[]),
        )
        by_agent = {str(agent['id']): agent for agent in agents}
        results = [quote_offer(variant_row=variant, product=product, offer_row=offer, rate_rows=rates,
                               agent_row=by_agent.get(str(offer.get('responsible_agent_id'))), request=payload)
                   for offer in offers]
        return select_offers(results, offers)

    @router.get('/{kind}')
    async def records(kind: Kind, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                      parent_id: UUID | None = None, _admin=Depends(require_admin)):
        params = {'select': '*', 'order': 'created_at.desc,id.asc'}
        parent = {'variant': 'product_id', 'offer': 'variant_id', 'shipping_rate': 'offer_id', 'agent': 'profile_id'}[kind]
        if parent_id:
            params[parent] = f'eq.{parent_id}'
        result = await db.page(TABLES[kind], params=params, page=page, limit=limit)
        if kind == 'variant' and result['items']:
            ids = ','.join(str(UUID(item['id'])) for item in result['items'])
            # This relation has a composite key rather than an id column.
            link_page = await db.page('variant_compatibilities', params={'variant_id': f'in.({ids})',
                                      'order': 'variant_id.asc,compatibility_id.asc'}, page=1, limit=1000)
            if link_page['total'] > 1000 or len(link_page['items']) != link_page['total']:
                raise HTTPException(409, 'Incomplete compatibility associations; narrow the product page')
            links = link_page['items']
            result['items'] = [{**item, 'compatibility_ids': [link['compatibility_id'] for link in links
                                                          if link['variant_id'] == item['id']]}
                               for item in result['items']]
        return result

    async def save(kind, record_id, payload, actor):
        if record_id is not None and payload.expected_updated_at is None:
            raise HTTPException(422, 'Expected version is required for updates')
        if record_id is None and payload.expected_updated_at is not None:
            raise HTTPException(422, 'New records have no expected version')
        try:
            data = MODELS[kind].model_validate(payload.data).model_dump(mode='json')
        except ValidationError:
            # Do not echo supplier data/URLs or arbitrary input back in errors.
            raise HTTPException(422, 'Invalid commerce record') from None
        return await db.rpc('admin_save_commerce_record', {
            'p_actor': actor['id'], 'p_kind': kind, 'p_id': str(record_id) if record_id else None,
            'p_data': data, 'p_expected': payload.expected_updated_at.isoformat() if payload.expected_updated_at else None,
        })

    @router.post('/{kind}')
    async def create(kind: Kind, payload: SaveInput, actor=Depends(require_admin)):
        return await save(kind, None, payload, actor)

    @router.put('/{kind}/{record_id}')
    async def update(kind: Kind, record_id: UUID, payload: SaveInput, actor=Depends(require_admin)):
        return await save(kind, record_id, payload, actor)

    return router
