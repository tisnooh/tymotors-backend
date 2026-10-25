"""Private, deterministic cart quote evaluation over immutable RPC source rows.

No network, reservation, supplier selection persistence or catalogue validation.
The caller must never expose this payload's private offer evaluation to clients.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import Field, ValidationError

from app.commerce_models import QuoteInput
from app.commerce_pricing import quote_offer
from app.product_image_policy import permitted_image


class CartQuoteError(ValueError):
    """Safe business code for an API 409; no source rows or costs in the error."""

    status_code = 409

    def __init__(self, code: str, reasons: tuple[str, ...] = ()):
        self.code = code
        self.reasons = reasons
        super().__init__(code)


class _GroupQuoteInput(QuoteInput):
    # Each persisted line is still limited to 20. Only the private aggregate
    # extends the administrative one-line contract: 100 lines * 20 units.
    quantity: int = Field(strict=True, ge=1, le=2000)


def _id(value: Any) -> str:
    if not isinstance(value, (str, UUID)):
        raise CartQuoteError('invalid_quote_context')
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise CartQuoteError('invalid_quote_context') from None


def _rows(context: dict, key: str) -> list[dict]:
    rows = context.get(key, [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CartQuoteError('invalid_quote_context')
    return rows


def _index(context: dict, key: str) -> dict[str, dict]:
    indexed = {}
    for row in _rows(context, key):
        identity = _id(row.get('id'))
        if identity in indexed:
            raise CartQuoteError('invalid_quote_context')
        indexed[identity] = row
    return indexed


def _rules(context: dict, product_id: str, variant_id: str, indexes: dict) -> list[dict]:
    result = []
    linked = set()
    for link in _rows(context, 'links'):
        if _id(link.get('variant_id')) != variant_id:
            continue
        rule_id = _id(link.get('compatibility_id'))
        if rule_id in linked:
            raise CartQuoteError('invalid_variant_compatibility')
        linked.add(rule_id)
        row = indexes['compatibilities'].get(rule_id)
        if not row or _id(row.get('product_id')) != product_id:
            raise CartQuoteError('invalid_variant_compatibility')
        brand = indexes['brands'].get(_id(row.get('brand_id')))
        model = indexes['models'].get(_id(row['vehicle_model_id'])) if row.get('vehicle_model_id') else None
        generation = indexes['generations'].get(_id(row['generation_id'])) if row.get('generation_id') else None
        if (not brand or (row.get('vehicle_model_id') and not model)
                or (row.get('generation_id') and not generation)):
            raise CartQuoteError('invalid_variant_compatibility')
        if model and model.get('brand_id') and _id(model['brand_id']) != _id(row['brand_id']):
            raise CartQuoteError('invalid_variant_compatibility')
        if (generation and generation.get('vehicle_model_id')
                and _id(generation['vehicle_model_id']) != _id(row.get('vehicle_model_id'))):
            raise CartQuoteError('invalid_variant_compatibility')
        # Same raw-to-public rule mapping as CatalogStore.hydrate_products.
        # No chassis is manufactured from a model, generation or photograph.
        result.append({
            'id': rule_id, 'brand_slug': brand.get('slug'),
            'model': row.get('model_name') or (model or {}).get('name'),
            'chassis': row.get('chassis'),
            'generation': row.get('generation_name') or (generation or {}).get('name'),
            'year_from': row.get('year_from'), 'year_to': row.get('year_to'),
            'body_types': row.get('body_types') or [], 'facelift': row.get('facelift') or 'unknown',
            'required_trim': row.get('required_trims') or [], 'excluded_trims': row.get('excluded_trims') or [],
            'camera_compatible': row.get('camera_compatible'),
            'parking_sensor_compatible': row.get('parking_sensor_compatible'),
            'notes': row.get('notes'), 'is_verified': row.get('verification_state') == 'verified',
        })
    return result


def _image(context: dict, product_id: str, now: datetime) -> str:
    images = [row for row in _rows(context, 'product_images') if _id(row.get('product_id')) == product_id]
    if not images:
        raise CartQuoteError('authorized_product_image_required')
    permissions = _rows(context, 'image_permissions')
    images.sort(key=lambda row: (row.get('display_order') or 0, str(row.get('id') or '')))
    for image in images:
        source = image.get('url')
        if not isinstance(source, str) or not source or permitted_image(source) is None:
            raise CartQuoteError('image_commercial_rights_unconfirmed')
        matching = [row for row in permissions if _id(row.get('product_id')) == product_id and row.get('image_url') == source]
        if len(matching) != 1:
            raise CartQuoteError('image_commercial_rights_unconfirmed')
        grant = matching[0]
        try:
            expiry = datetime.fromisoformat(grant['valid_until'])
            verified = datetime.fromisoformat(grant['verified_at'])
            _id(grant['verified_by'])
            valid = (grant.get('state') == 'verified' and grant.get('commercial_use') is True
                and grant.get('derivatives_use') is True and grant.get('product_match_confirmed') is True
                and grant.get('marks_clearance') in {'not_present','verified'}
                and isinstance(grant.get('evidence_ref'), str) and bool(grant['evidence_ref'].strip())
                and isinstance(grant.get('countries'), list) and context.get('country') in grant['countries']
                and expiry.tzinfo is not None and expiry > now and verified.tzinfo is not None and verified <= now)
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            raise CartQuoteError('image_commercial_rights_unconfirmed')
    return images[0]['url']


def build_cart_quote(context: dict, now: datetime | None = None) -> dict[str, Any]:
    """Evaluate every line, charging logistics once per exact variant group."""
    if not isinstance(context, dict):
        raise CartQuoteError('invalid_quote_context')
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CartQuoteError('invalid_quote_time')
    cart = context.get('cart')
    if not isinstance(cart, dict) or not cart.get('id'):
        raise CartQuoteError('cart_missing')
    if cart.get('currency') != 'EUR':
        raise CartQuoteError('cart_currency_mismatch')
    cart_id = _id(cart['id'])
    items = _rows(context, 'cart_items')
    if not items:
        raise CartQuoteError('cart_empty')
    if len(items) > 100:
        raise CartQuoteError('cart_too_large')
    indexes = {key: _index(context, key) for key in (
        'products', 'variants', 'offers', 'rates', 'agents', 'suppliers',
        'compatibilities', 'brands', 'models', 'generations')}
    grouped: dict[str, list[dict]] = {}
    line_ids = set()
    for item in items:
        line_id = _id(item.get('id'))
        if line_id in line_ids or _id(item.get('cart_id')) != cart_id:
            raise CartQuoteError('cart_item_mismatch')
        line_ids.add(line_id)
        if not item.get('variant_id'):
            raise CartQuoteError('variant_required')
        quantity = item.get('quantity')
        if type(quantity) is not int or not 1 <= quantity <= 20:
            raise CartQuoteError('invalid_cart_quantity')
        variant_id, product_id = _id(item['variant_id']), _id(item.get('product_id'))
        variant = indexes['variants'].get(variant_id)
        if not variant or _id(variant.get('product_id')) != product_id:
            raise CartQuoteError('variant_product_mismatch')
        grouped.setdefault(variant_id, []).append(item)
    groups = []
    for variant_id, lines in grouped.items():
        variant = indexes['variants'][variant_id]
        product_id = _id(variant.get('product_id'))
        raw_product = indexes['products'].get(product_id)
        if not raw_product:
            raise CartQuoteError('product_missing')
        if raw_product.get('currency') != 'EUR' or variant.get('currency') != 'EUR':
            raise CartQuoteError('cart_currency_mismatch')
        if type(variant.get('requires_vehicle', True)) is not bool:
            raise CartQuoteError('invalid_quote_context')
        rules = _rules(context, product_id, variant_id, indexes)
        variant_dto = {**variant, 'compatibility_ids': [rule['id'] for rule in rules]}
        product_dto = {**raw_product, 'compatibilities': rules, 'compatible_brands': []}
        quantity = sum(line['quantity'] for line in lines)
        requests = []
        for line in lines:
            try:
                requests.append(_GroupQuoteInput(
                    variant_id=variant_id, quantity=quantity, country=context.get('country'),
                    postal_code=context.get('postal_code'), mode=context.get('mode'),
                    selected_vehicle=line.get('selected_vehicle')))
            except ValidationError as error:
                vehicle_error = any(issue['loc'][0] == 'selected_vehicle' for issue in error.errors())
                raise CartQuoteError('invalid_vehicle' if vehicle_error else 'destination_incomplete') from None
        ready = []
        blocked = set()
        for offer in indexes['offers'].values():
            if _id(offer.get('variant_id')) != variant_id:
                continue
            supplier = indexes['suppliers'].get(_id(offer.get('supplier_id')))
            if not supplier:
                blocked.add('supplier_missing')
                continue
            agent = indexes['agents'].get(_id(offer['responsible_agent_id'])) if offer.get('responsible_agent_id') else None
            # DB booleans must not be replaced by truthy strings in raw context.
            if variant.get('is_verified') is not True or (agent and agent.get('is_active') is not True):
                blocked.add('unverified_commerce_record')
                continue
            evaluations = [quote_offer(variant_row=variant_dto, product=product_dto, offer_row=offer,
                rate_rows=list(indexes['rates'].values()), agent_row=agent, request=request, now=now)
                for request in requests]
            if all(evaluation['status'] == 'ready' for evaluation in evaluations):
                ready.append((offer, evaluations))
            else:
                blocked.update(reason for evaluation in evaluations for reason in evaluation['reasons'])
        if not ready:
            raise CartQuoteError('no_valid_offer', tuple(sorted(blocked)))
        # A verified, ready primary beats cost; otherwise choose verified landed
        # acquisition/logistics cost, with deterministic ID tie-breaking.
        ready.sort(key=lambda pair: (pair[0].get('is_primary') is not True,
                                    pair[1][0]['landed_cost_cents'], str(pair[0]['id'])))
        offer, evaluations = ready[0]
        evaluation = evaluations[0]
        if any(type(value) is not int or not 0 <= value <= 2_000_000_000
               for key, value in evaluation.items() if key.endswith('_cents')):
            raise CartQuoteError('quote_amount_out_of_range')
        image_url = _image(context, product_id, now)
        snapshots = []
        for line, request, checked in zip(lines, requests, evaluations):
            snapshots.append({
                'cart_item_id': _id(line['id']), 'product_id': product_id, 'variant_id': variant_id,
                'quantity': line['quantity'], 'unit_amount_cents': evaluation['unit_price_cents'],
                'sku': variant['sku'], 'product_name': raw_product['name'], 'product_slug': raw_product['slug'],
                'image_url': image_url,
                'selected_vehicle': request.selected_vehicle.model_dump() if request.selected_vehicle else None,
                'compatibility_result': deepcopy(checked.get('compatibility') or {
                    'status': 'not_required', 'reason': 'Variant does not require a vehicle'}),
                'variant_name': variant['name'], 'variant_attributes': deepcopy(variant.get('attributes') or {}),
            })
        groups.append({
            'variant_id': variant_id, 'offer_id': _id(offer['id']),
            'shipping_rate_id': evaluation['shipping_rate_id'],
            'responsible_agent_id': evaluation['responsible_agent_id'], 'supplier_id': evaluation['supplier_id'],
            'line_ids': [line['cart_item_id'] for line in snapshots],
            'evaluation': deepcopy(evaluation), 'lines': snapshots,
        })
    suppliers = Counter(group['supplier_id'] for group in groups)
    for group in groups:
        if suppliers[group['supplier_id']] > 1:
            rate = indexes['rates'].get(_id(group['shipping_rate_id']))
            if not rate or rate.get('multi_variant_policy') != 'independent_parcels':
                raise CartQuoteError('shipping_consolidation_unconfirmed')
    subtotal = sum(line['unit_amount_cents'] * line['quantity'] for group in groups for line in group['lines'])
    shipping = sum(group['evaluation']['customer_shipping_cents'] for group in groups)
    taxes = sum(group['evaluation']['sales_tax_cents'] for group in groups)
    total = subtotal + shipping
    if any(type(value) is not int or not 0 <= value <= 2_000_000_000
           for value in (subtotal, shipping, taxes, total)) or taxes > total:
        raise CartQuoteError('quote_amount_out_of_range')
    try:
        expiries = [datetime.fromisoformat(group['evaluation']['valid_until']) for group in groups]
        if any(value.tzinfo is None or value.utcoffset() is None or value <= now for value in expiries):
            raise ValueError('invalid expiry')
    except (TypeError, ValueError):
        raise CartQuoteError('invalid_quote_validity') from None
    return {'groups': groups, 'subtotal_cents': subtotal, 'shipping_cents': shipping,
            'tax_cents': taxes, 'total_cents': total, 'currency': 'EUR',
            'valid_until': min(expiries).isoformat()}
