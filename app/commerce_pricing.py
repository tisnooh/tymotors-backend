"""Evidence-gated, side-effect-free quote calculation, consumed by the admin API.

Supplier gross unit cost already includes its tax; subtract only confirmed
recoverable tax. Import duty/nonrecoverable import tax are *additional* amounts,
never that supplier tax again. Shipping costs/fees cover the entire quoted line.
Unknown values block the quote: None is not a free charge or an exchange rate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from pydantic import ValidationError

from app.commerce_models import AgentInput, OfferInput, QuoteInput, ShippingRateInput, VariantInput
from app.compatibility import check_compatibility


def _record(model, row):
    return model.model_validate({key: value for key, value in row.items() if key in model.model_fields})


def _cents(value: Decimal) -> int:
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _postal(value: str) -> str:
    return value.replace(' ', '').replace('-', '').upper()


def _fresh(value: datetime | None, now: datetime) -> bool:
    return value is not None and value > now


def quote_offer(*, variant_row: dict, product: dict, offer_row: dict, rate_rows: list[dict],
                agent_row: dict | None, request: QuoteInput, now: datetime | None = None) -> dict[str, Any]:
    """Private administrative evaluation, not a checkout authorization or reservation."""
    now = now or datetime.now(timezone.utc)
    reasons = []
    result = {'offer_id': str(offer_row.get('id') or ''), 'status': 'blocked', 'reasons': reasons}
    try:
        variant = _record(VariantInput, variant_row)
        offer = _record(OfferInput, offer_row)
    except (ValidationError, ValueError):
        reasons.append('invalid_commerce_record')
        return result
    if str(variant_row.get('id')) != str(request.variant_id) or str(offer.variant_id) != str(request.variant_id):
        reasons.append('variant_offer_mismatch')
    if str(variant.product_id) != str(product.get('id')):
        reasons.append('variant_product_mismatch')
    if product.get('status') != 'active' or product.get('is_verified') is not True:
        reasons.append('product_not_verified_active')
    if variant.status != 'active' or not variant.is_verified or not variant.evidence_ref:
        reasons.append('variant_not_verified_active')
    if variant.stock < request.quantity:
        reasons.append('variant_stock_insufficient')
    if offer.verification_state != 'verified' or not offer.evidence_ref:
        reasons.append('offer_unverified')
    if offer.availability != 'available' or offer.available_quantity is None or offer.available_quantity < request.quantity:
        reasons.append('supplier_stock_unconfirmed_or_insufficient')
    if not _fresh(offer.valid_until, now):
        reasons.append('offer_terms_missing_or_expired')
    if request.quantity < offer.moq:
        reasons.append('minimum_order_quantity')
    if offer.preparation_days_min is None or offer.preparation_days_max is None:
        reasons.append('preparation_time_unknown')
    agent = None
    if agent_row:
        try:
            agent = _record(AgentInput, agent_row)
        except ValidationError:
            pass
    if (not agent or not agent.is_active or agent.role not in {'orders', 'supervisor'}
            or str(agent_row.get('id')) != str(offer.responsible_agent_id)):
        reasons.append('responsible_order_agent_missing_or_inactive')
    if variant.requires_vehicle:
        if not request.selected_vehicle:
            reasons.append('vehicle_required')
        else:
            ids = {str(value) for value in variant.compatibility_ids}
            scoped = {**product, 'compatibilities': [rule for rule in product.get('compatibilities', []) if str(rule.get('id')) in ids]}
            fitment = check_compatibility(scoped, request.selected_vehicle)
            result['compatibility'] = fitment
            if fitment['status'] != 'compatible':
                reasons.append('variant_fitment_not_confirmed')
    matching = []
    invalid_rate = False
    for row in rate_rows:
        # Only rows for this offer are eligible; another offer cannot donate rates.
        if (str(row.get('offer_id')) != str(offer_row.get('id'))
                or row.get('country') != request.country or row.get('mode') != request.mode):
            continue
        try:
            rate = _record(ShippingRateInput, row)
        except ValidationError:
            invalid_rate = True
            continue
        if (rate.country == request.country and rate.mode == request.mode
                and rate.min_quantity <= request.quantity <= rate.max_quantity
                and _postal(request.postal_code).startswith(_postal(rate.postal_prefix))):
            matching.append((row, rate))
    if invalid_rate:
        # Do not hide a broken regional restriction by silently using a generic
        # country rate. An operator must repair this offer/destination/mode.
        reasons.append('shipping_rule_invalid')
        return result
    if not matching:
        reasons.append('shipping_rate_missing')
        return result
    # A more specific regional rate beats the country-wide rule, but ambiguous
    # same-specificity matches must be resolved by an operator, never guessed.
    specificity = max(len(_postal(rate.postal_prefix)) for _, rate in matching)
    matching = [(row, rate) for row, rate in matching if len(_postal(rate.postal_prefix)) == specificity]
    if len(matching) != 1:
        reasons.append('shipping_rate_ambiguous')
        return result
    rate_row, rate = matching[0]
    if rate.verification_state != 'verified' or not rate.evidence_ref or not _fresh(rate.valid_until, now):
        reasons.append('shipping_terms_unverified_or_expired')
    if rate.delivery_days_min is None or rate.delivery_days_max is None:
        reasons.append('delivery_time_unknown')
    if offer.unit_cost_cents is None or offer.recoverable_tax_cents is None:
        reasons.append('supplier_cost_or_tax_basis_unknown')
    cost_keys = ('shipping_cost_cents', 'shipping_recoverable_tax_cents', 'customer_shipping_cents',
                 'agent_fee_cents', 'import_duty_cents', 'nonrecoverable_tax_cents', 'other_cost_cents')
    if any(getattr(rate, key) is None for key in cost_keys):
        reasons.append('logistics_cost_breakdown_incomplete')
    if rate.goods_tax_bps is None or rate.shipping_tax_bps is None:
        reasons.append('sales_tax_basis_unknown')
    fx = Decimal(1)
    if offer.currency != variant.currency:
        if not offer.fx_rate or not offer.fx_evidence_ref or not _fresh(offer.fx_valid_until, now):
            reasons.append('exchange_rate_unconfirmed_or_expired')
        else:
            fx = offer.fx_rate
    elif offer.fx_rate not in {None, Decimal(1)}:
        reasons.append('same_currency_exchange_rate_invalid')
    if reasons:
        return result
    quantity = request.quantity
    supplier_gross = _cents(Decimal(offer.unit_cost_cents * quantity) * fx)
    acquisition_net = _cents(Decimal((offer.unit_cost_cents - offer.recoverable_tax_cents) * quantity) * fx)
    shipping_net = rate.shipping_cost_cents - rate.shipping_recoverable_tax_cents
    logistics_extra = sum(getattr(rate, key) for key in ('agent_fee_cents', 'import_duty_cents', 'nonrecoverable_tax_cents', 'other_cost_cents'))
    landed = acquisition_net + shipping_net + logistics_extra
    customer_total = variant.price_cents * quantity + rate.customer_shipping_cents
    # Destination-specific confirmed tax rates: never inherit a domestic product
    # rate for another country, or assume shipping and goods share a regime.
    revenue_net = (_cents(Decimal(variant.price_cents * quantity) * 10000 / (10000 + rate.goods_tax_bps))
                   + _cents(Decimal(rate.customer_shipping_cents) * 10000 / (10000 + rate.shipping_tax_bps)))
    margin = revenue_net - landed
    if margin < 0:
        reasons.append('negative_contribution_margin')
    result.update({
        'status': 'blocked' if reasons else 'ready',
        'variant_id': str(request.variant_id), 'supplier_id': str(offer.supplier_id),
        'responsible_agent_id': str(offer.responsible_agent_id),
        'supplier_sku': offer.supplier_sku, 'supplier_variant': offer.supplier_variant,
        'shipping_rate_id': str(rate_row['id']), 'quantity': quantity, 'currency': variant.currency,
        'supplier_gross_cents': supplier_gross, 'acquisition_net_cents': acquisition_net,
        'shipping_net_cents': shipping_net, 'additional_costs_cents': logistics_extra,
        'landed_cost_cents': landed, 'customer_shipping_cents': rate.customer_shipping_cents,
        'unit_price_cents': variant.price_cents, 'customer_total_cents': customer_total,
        'revenue_net_cents': revenue_net, 'sales_tax_cents': customer_total - revenue_net,
        'contribution_margin_cents': margin,
        'margin_basis': 'before_payment_fees_and_operating_expenses_not_net_profit',
        'valid_until': min(value for value in [offer.valid_until, rate.valid_until,
                                             offer.fx_valid_until if offer.currency != variant.currency else offer.valid_until]).isoformat(),
        'delivery_days_min': offer.preparation_days_min + rate.delivery_days_min,
        'delivery_days_max': offer.preparation_days_max + rate.delivery_days_max,
        'evidence_refs': [variant.evidence_ref, offer.evidence_ref, rate.evidence_ref]
                         + ([offer.fx_evidence_ref] if offer.currency != variant.currency else []),
    })
    return result


def select_offers(results: list[dict], offers: list[dict]) -> dict:
    ready = [result for result in results if result['status'] == 'ready']
    ready.sort(key=lambda result: (result['landed_cost_cents'], result['offer_id']))
    primary_ids = {str(offer['id']) for offer in offers if offer.get('is_primary') is True}
    return {'status': 'ready' if ready else 'blocked', 'offers': results,
            'best_cost_offer_id': ready[0]['offer_id'] if ready else None,
            'primary_offer_id': next((r['offer_id'] for r in ready if r['offer_id'] in primary_ids), None),
            'alternative_offer_ids': [r['offer_id'] for r in ready if r['offer_id'] not in primary_ids],
            'scope': 'administrative_evaluation_not_checkout_authorization_or_stock_reservation'}
