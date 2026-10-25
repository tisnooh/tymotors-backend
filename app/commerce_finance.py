"""Pure private financial analysis of already-priced, immutable EUR quote groups.

This is not a price writer, evidence authenticator, tax adviser or sale approval.
Unknown is never zero. Payment fees apply once per order, not once per group.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[int, Field(strict=True, ge=0, le=2_000_000_000)]
Bps = Annotated[int, Field(strict=True, ge=0, le=10000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, frozen=True)


class Evidence(Strict):
    value: Money | None = None
    provenance: Literal['CONFIRMED', 'ASSUMPTION', 'UNKNOWN'] = 'UNKNOWN'
    reference: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode='after')
    def consistent(self):
        if self.provenance == 'UNKNOWN':
            if self.value is not None or self.reference is not None:
                raise ValueError('Unknown evidence cannot contain a claimed amount or reference')
        elif self.value is None or not self.reference:
            raise ValueError('Confirmed facts and assumptions require a value and source')
        return self


class RateEvidence(Evidence):
    value: Bps | None = None


class FinanceGroup(Strict):
    group_id: str = Field(min_length=1, max_length=200)
    variant_id: str = Field(min_length=1, max_length=200)
    offer_id: str = Field(min_length=1, max_length=200)
    shipping_rate_id: str = Field(min_length=1, max_length=200)
    quantity: int = Field(strict=True, ge=1, le=2000)
    currency: Literal['EUR']
    source_status: Literal['ready', 'blocked']
    source_reasons: list[str] = Field(default_factory=list, max_length=100)
    provenance: Literal['CONFIRMED', 'ASSUMPTION', 'UNKNOWN']
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    supplier_gross_cents: Money | None = None
    acquisition_net_cents: Money | None = None
    shipping_net_cents: Money | None = None
    additional_costs_cents: Money | None = None
    landed_cost_cents: Money | None = None
    customer_total_cents: Money | None = None
    revenue_net_cents: Money | None = None
    sales_tax_cents: Money | None = None
    contribution_margin_cents: int | None = Field(default=None, strict=True, ge=-2_000_000_000, le=2_000_000_000)

    @model_validator(mode='after')
    def sums(self):
        if self.provenance != 'UNKNOWN' and not self.evidence_refs:
            raise ValueError('An evaluated group needs identifiable evidence')
        if any(not ref.strip() or len(ref) > 1000 for ref in self.evidence_refs):
            raise ValueError('Invalid evidence reference')
        parts = (self.acquisition_net_cents, self.shipping_net_cents, self.additional_costs_cents)
        if self.landed_cost_cents is not None and all(v is not None for v in parts):
            if self.landed_cost_cents != sum(parts):
                raise ValueError('Landed cost contradicts its components')
        if self.supplier_gross_cents is not None and self.acquisition_net_cents is not None:
            if self.acquisition_net_cents > self.supplier_gross_cents:
                raise ValueError('Net acquisition exceeds gross supplier payment')
        if all(v is not None for v in (self.customer_total_cents, self.revenue_net_cents, self.sales_tax_cents)):
            if self.customer_total_cents != self.revenue_net_cents + self.sales_tax_cents:
                raise ValueError('Sales tax and net revenue contradict gross revenue')
        if all(v is not None for v in (self.contribution_margin_cents, self.revenue_net_cents, self.landed_cost_cents)):
            if self.contribution_margin_cents != self.revenue_net_cents - self.landed_cost_cents:
                raise ValueError('Source contribution contradicts costs and revenue')
        return self


def group_from_evaluation(group_id: str, evaluation: dict, *, provenance: str) -> FinanceGroup:
    """Explicit adapter, not proof verification; caller must supply provenance.

    One evaluation per quote group, NEVER one per vehicle/cart line. Source
    shipping/additional fees already cover the entire grouped quantity.
    """
    fields = set(FinanceGroup.model_fields) - {'group_id', 'source_status', 'source_reasons', 'provenance'}
    return FinanceGroup.model_validate({
        **{key: evaluation[key] for key in fields if key in evaluation},
        'group_id': group_id, 'source_status': evaluation.get('status'),
        'source_reasons': evaluation.get('reasons', []), 'provenance': provenance,
    })


class ExtraCost(Strict):
    cost_id: str = Field(min_length=1, max_length=200)
    currency: Literal['EUR']
    # Net of tax is calculated, never caller-supplied on top of gross.
    gross_cents: Evidence = Field(default_factory=Evidence)
    recoverable_tax_cents: Evidence = Field(default_factory=Evidence)
    scope: Literal['additional_order_cost_not_in_landed']

    @model_validator(mode='after')
    def tax(self):
        if self.gross_cents.value is not None and self.recoverable_tax_cents.value is not None:
            if self.recoverable_tax_cents.value > self.gross_cents.value:
                raise ValueError('Recoverable tax exceeds the extra cost')
        return self


class Scenario(Strict):
    name: Literal['PESSIMISTIC', 'REALISTIC', 'OPTIMISTIC']
    reference: str = Field(min_length=1, max_length=1000)
    landed_cost_change_bps: int = Field(strict=True, ge=-10000, le=100000)
    other_variable_cost_change_bps: int = Field(strict=True, ge=-10000, le=100000)
    return_probability_bps: Bps
    orders_in_period: int | None = Field(default=None, strict=True, ge=0, le=1000000)


class FinanceInput(Strict):
    groups: list[FinanceGroup] = Field(min_length=1, max_length=100)
    payment_fixed_gross_cents: Evidence = Field(default_factory=Evidence)
    payment_variable_bps: RateEvidence = Field(default_factory=RateEvidence)
    payment_fee_base: Literal['GROSS_CHARGED', 'NET_REVENUE'] | None = None
    payment_recoverable_tax_cents: Evidence = Field(default_factory=Evidence)
    extra_costs: list[ExtraCost] = Field(default_factory=list, max_length=100)
    # Explicit confirmation that [] means no extra charges, not unresearched.
    extra_costs_complete: Literal['CONFIRMED', 'ASSUMPTION', 'UNKNOWN'] = 'UNKNOWN'
    extra_costs_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    return_probability_bps: RateEvidence = Field(default_factory=RateEvidence)
    # Expected total incremental loss for ONE returned unit: includes net
    # revenue reversal and reverse logistics, less evidenced recoveries. It
    # excludes baseline landed cost, which is already fully charged above.
    return_loss_per_unit_net_cents: Evidence = Field(default_factory=Evidence)
    return_loss_basis: Literal['incremental_including_revenue_reversal_net_of_recoveries_excluding_landed'] | None = None
    # Different products do not silently inherit one another's return risk.
    # The two return evidence references must explicitly cover every group.
    return_profile_scope: Literal['UNIFORM_ACROSS_ALL_GROUP_UNITS'] | None = None
    fixed_costs_period_net_cents: Evidence = Field(default_factory=Evidence)
    fixed_costs_period: str | None = Field(default=None, min_length=1, max_length=100)
    # Cash outlay covers gross supplier + logistics + ALL order extra/payment
    # costs, once. It is independently evidenced; net landed cannot imply cash.
    cash_outlay_gross_cents: Evidence = Field(default_factory=Evidence)
    outlay_precedes_customer_funds: bool | None = Field(default=None, strict=True)
    cash_timing_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    cash_timing_provenance: Literal['CONFIRMED', 'ASSUMPTION', 'UNKNOWN'] = 'UNKNOWN'
    scenarios: list[Scenario] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def unique_and_complete(self):
        if len({g.group_id for g in self.groups}) != len(self.groups):
            raise ValueError('Duplicate quote group would double-count shipping')
        if len({(g.variant_id, g.offer_id, g.shipping_rate_id) for g in self.groups}) != len(self.groups):
            raise ValueError('A variant/offer/rate must be grouped once')
        if len({c.cost_id for c in self.extra_costs}) != len(self.extra_costs):
            raise ValueError('Duplicate additional cost')
        if {s.name for s in self.scenarios} != {'PESSIMISTIC', 'REALISTIC', 'OPTIMISTIC'}:
            raise ValueError('Three distinct documented scenarios are required')
        if self.extra_costs_complete != 'UNKNOWN' and not self.extra_costs_reference:
            raise ValueError('An exhaustive cost list requires a source or assumption')
        if self.fixed_costs_period_net_cents.value is not None and not self.fixed_costs_period:
            raise ValueError('Fixed costs require their period')
        if self.outlay_precedes_customer_funds is not None and not self.cash_timing_reference:
            raise ValueError('Cash timing requires evidence or an explicit assumption')
        if self.cash_timing_provenance != 'UNKNOWN' and self.outlay_precedes_customer_funds is None:
            raise ValueError('Known cash timing requires its actual sequence')
        return self


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def analyze_finance(request: FinanceInput | dict) -> dict:
    """Return an auditable private analysis, never mutation or authorization."""
    # Revalidate even an existing model: Python callers can mutate nested lists
    # or use model_construct/model_copy, which deliberately bypass validation.
    data = FinanceInput.model_validate(request.model_dump() if isinstance(request, FinanceInput) else request)
    reasons: list[str] = []
    assumptions: list[str] = []
    sources: list[dict] = []

    def evidence(path: str, item: Evidence, *, required=True):
        sources.append({'field': path, 'provenance': item.provenance, 'reference': item.reference})
        if item.provenance == 'ASSUMPTION':
            assumptions.append(path)
        if required and item.value is None:
            reasons.append(f'{path}:unknown')
        return item.value

    monetary_fields = ('supplier_gross_cents', 'acquisition_net_cents', 'shipping_net_cents',
                       'additional_costs_cents', 'landed_cost_cents', 'customer_total_cents',
                       'revenue_net_cents', 'sales_tax_cents', 'contribution_margin_cents')
    for group in data.groups:
        prefix = f'group:{group.group_id}'
        sources.append({'field': prefix, 'provenance': group.provenance, 'reference': list(group.evidence_refs)})
        if group.provenance == 'ASSUMPTION':
            assumptions.append(prefix)
        if group.provenance == 'UNKNOWN':
            reasons.append(f'{prefix}:provenance_unknown')
        if group.source_status != 'ready' or group.source_reasons:
            reasons.append(f'{prefix}:source_blocked')
        reasons.extend(f'{prefix}:{key}:unknown' for key in monetary_fields if getattr(group, key) is None)
    fixed = evidence('payment_fixed_gross_cents', data.payment_fixed_gross_cents)
    rate = evidence('payment_variable_bps', data.payment_variable_bps)
    fee_tax = evidence('payment_recoverable_tax_cents', data.payment_recoverable_tax_cents)
    probability = evidence('return_probability_bps', data.return_probability_bps)
    return_loss = evidence('return_loss_per_unit_net_cents', data.return_loss_per_unit_net_cents)
    period_fixed = evidence('fixed_costs_period_net_cents', data.fixed_costs_period_net_cents, required=False)
    cash = evidence('cash_outlay_gross_cents', data.cash_outlay_gross_cents, required=False)
    if data.payment_fee_base is None:
        reasons.append('payment_fee_base:unknown')
    if data.return_loss_basis is None:
        reasons.append('return_loss_basis:unknown')
    if len(data.groups) > 1 and data.return_profile_scope is None:
        reasons.append('multi_group_return_profile:unconfirmed_uniformity')
    if data.extra_costs_complete == 'UNKNOWN':
        reasons.append('extra_costs:completeness_unknown')
    elif data.extra_costs_complete == 'ASSUMPTION':
        assumptions.append('extra_costs:completeness')
    sources.append({'field': 'extra_costs:completeness', 'provenance': data.extra_costs_complete,
                    'reference': data.extra_costs_reference})
    sources.append({'field': 'cash_timing', 'provenance': data.cash_timing_provenance,
                    'reference': data.cash_timing_reference})
    if data.cash_timing_provenance == 'ASSUMPTION':
        assumptions.append('cash_timing')
    extra_net, extra_gross = 0, 0
    for cost in data.extra_costs:
        gross = evidence(f'extra:{cost.cost_id}:gross', cost.gross_cents)
        tax = evidence(f'extra:{cost.cost_id}:recoverable_tax', cost.recoverable_tax_cents)
        if gross is not None and tax is not None:
            extra_net += gross - tax
            extra_gross += gross

    result = {'status': 'BLOCKED', 'currency': 'EUR', 'reasons': reasons,
              'assumptions': assumptions, 'sources': sources, 'baseline': None,
              'scenarios': [], 'break_even_orders': None, 'cash_bridge_cents': None,
              'optional_unknowns': [], 'commercial_approval': False,
              'scope': 'private_contribution_analysis_not_net_profit_or_price_authorization'}
    if period_fixed is None:
        result['optional_unknowns'].append('fixed_costs_period:unknown')
    if cash is None or data.outlay_precedes_customer_funds is None or data.cash_timing_provenance == 'UNKNOWN':
        result['optional_unknowns'].append('cash_outlay_or_timing:unknown')
    if reasons:
        return result
    totals = {key: sum(getattr(group, key) for group in data.groups) for key in monetary_fields}
    qty = sum(group.quantity for group in data.groups)
    fee_base = totals['customer_total_cents'] if data.payment_fee_base == 'GROSS_CHARGED' else totals['revenue_net_cents']
    payment_gross = fixed + _round(Decimal(fee_base) * rate / 10000)
    if fee_tax > payment_gross:
        raise ValueError('Recoverable payment tax exceeds calculated gross fees')
    payment_net = payment_gross - fee_tax

    def analysis(landed: int, extras: int, prob: int):
        expected_return = _round(Decimal(qty) * prob * return_loss / 10000)
        full_variable = landed + payment_net + extras + expected_return
        contribution = totals['revenue_net_cents'] - full_variable
        return {'landed_cost_cents': landed, 'payment_fee_gross_cents': payment_gross,
                'payment_recoverable_tax_cents': fee_tax, 'payment_fee_net_cents': payment_net,
                'other_variable_costs_net_cents': extras, 'expected_return_loss_net_cents': expected_return,
                'full_variable_cost_net_cents': full_variable,
                'revenue_net_cents': totals['revenue_net_cents'], 'revenue_gross_cents': totals['customer_total_cents'],
                'sales_tax_cents': totals['sales_tax_cents'], 'contribution_margin_cents': contribution,
                'average_contribution_per_unit_cents': str((Decimal(contribution) / qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                'margin_on_net_sales_bps': _round(Decimal(contribution) * 10000 / totals['revenue_net_cents']) if totals['revenue_net_cents'] else None,
                'profitable_before_unmodelled_fixed_costs': contribution > 0}

    baseline = analysis(totals['landed_cost_cents'], extra_net, probability)
    baseline['source_components'] = totals
    baseline['groups_before_order_adjustments'] = [
        {'group_id': group.group_id, 'variant_id': group.variant_id, 'quantity': group.quantity,
         'landed_cost_cents': group.landed_cost_cents, 'revenue_net_cents': group.revenue_net_cents,
         'contribution_before_order_adjustments_cents': group.contribution_margin_cents}
        for group in data.groups]
    baseline['per_product_contribution_after_order_adjustments'] = (
        [{'group_id': data.groups[0].group_id, 'contribution_margin_cents': baseline['contribution_margin_cents']}]
        if len(data.groups) == 1 else None)
    if len(data.groups) > 1:
        result['optional_unknowns'].append('per_product_order_fee_allocation:not_defined')
    result['baseline'] = baseline
    result['status'] = 'HYPOTHETICAL' if assumptions else 'CONFIRMED_ANALYSIS'
    if period_fixed is not None:
        contribution = baseline['contribution_margin_cents']
        if period_fixed == 0:
            result['break_even_orders'] = 0
        elif contribution > 0:
            result['break_even_orders'] = int((Decimal(period_fixed) / contribution).to_integral_value(rounding=ROUND_CEILING))
        else:
            result['optional_unknowns'].append('break_even:nonpositive_contribution')
    if cash is not None and data.outlay_precedes_customer_funds is not None and data.cash_timing_provenance != 'UNKNOWN':
        # The cash figure is all-in, not a net cost plus VAT guessed again.
        minimum = totals['supplier_gross_cents'] + totals['shipping_net_cents'] + totals['additional_costs_cents'] + payment_gross + extra_gross
        if cash < minimum:
            raise ValueError('All-in cash outlay is below known gross/net cash obligations')
        result['cash_bridge_cents'] = cash if data.outlay_precedes_customer_funds else max(0, cash - totals['customer_total_cents'])
        result['cash_bridge_basis'] = 'single_order_initial_bridge_excludes_unprovided_settlement_reserves_return_timing_and_concurrent_orders'
    for scenario in data.scenarios:
        row = analysis(_round(Decimal(totals['landed_cost_cents']) * (10000 + scenario.landed_cost_change_bps) / 10000),
                       _round(Decimal(extra_net) * (10000 + scenario.other_variable_cost_change_bps) / 10000),
                       scenario.return_probability_bps)
        row.update({'name': scenario.name, 'status': 'HYPOTHETICAL', 'reference': scenario.reference,
                    'landed_cost_change_bps': scenario.landed_cost_change_bps,
                    'other_variable_cost_change_bps': scenario.other_variable_cost_change_bps,
                    'return_probability_bps': scenario.return_probability_bps,
                    'orders_in_period': scenario.orders_in_period,
                    'period_contribution_less_known_fixed_costs_cents': None})
        if period_fixed is not None and scenario.orders_in_period is not None:
            row['period_contribution_less_known_fixed_costs_cents'] = row['contribution_margin_cents'] * scenario.orders_in_period - period_fixed
        result['scenarios'].append(row)
    return result
