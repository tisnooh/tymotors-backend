"""Private deterministic allocation from immutable quote order lines.

No source selection, alternative substitution, purchase, email or carrier call.
Only sandbox planning is enabled; current catalogue rows are never consulted.
"""
from copy import deepcopy
from uuid import UUID
import re


class FulfillmentPlanError(ValueError):
    pass


def _identity(value):
    try:
        result = str(UUID(str(value)))
        if not UUID(result).int:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise FulfillmentPlanError('invalid_fulfillment_identity') from None


def plan_test_fulfillment(order, lines):
    """Return one task per exact supplier/agent/offer/rate, amounts in cents.

    Quote group costs are charged ONCE even if multiple cart lines represent
    different compatible vehicles. Every public order line must be supplied by
    the trusted caller, which compares complete coverage transactionally.
    """
    if order.get('is_test') is not True or order.get('currency') != 'EUR':
        raise FulfillmentPlanError('test_fulfillment_only')
    oid, qid = _identity(order.get('id')), _identity(order.get('commerce_quote_id'))
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise FulfillmentPlanError('invalid_fulfillment_lines')
    tasks, seen = {}, set()
    for line in lines:
        if _identity(line.get('order_id')) != oid or _identity(line.get('quote_id')) != qid:
            raise FulfillmentPlanError('fulfillment_snapshot_mismatch')
        item_id = _identity(line.get('order_item_id'))
        if item_id in seen:
            raise FulfillmentPlanError('duplicate_fulfillment_line')
        seen.add(item_id)
        group, offer, rate, agent, supplier = [line.get(k) for k in (
            'group_snapshot', 'offer_snapshot', 'rate_snapshot', 'agent_snapshot', 'supplier_snapshot')]
        snap = line.get('line_snapshot')
        if any(not isinstance(x, dict) for x in (group, offer, rate, agent, supplier, snap)):
            raise FulfillmentPlanError('invalid_fulfillment_snapshot')
        variant = _identity(group.get('variant_id'))
        key = tuple(_identity(x) for x in (group.get('supplier_id'), group.get('responsible_agent_id'),
                                         group.get('offer_id'), group.get('shipping_rate_id'), variant))
        if (key != (_identity(supplier.get('id')), _identity(agent.get('id')), _identity(offer.get('id')),
                    _identity(rate.get('id')), _identity(offer.get('variant_id')))
                or _identity(offer.get('supplier_id')) != key[0]
                or _identity(offer.get('responsible_agent_id')) != key[1]
                or _identity(rate.get('offer_id')) != key[2]
                or _identity(snap.get('variant_id')) != variant
                or offer.get('currency') not in ('EUR','USD','GBP','CNY')
                or not isinstance(offer.get('supplier_sku'), str) or not offer['supplier_sku'].strip()):
            raise FulfillmentPlanError('fulfillment_snapshot_mismatch')
        qty = snap.get('quantity')
        if type(qty) is not int or not 1 <= qty <= 20:
            raise FulfillmentPlanError('invalid_fulfillment_quantity')
        if key not in tasks:
            tasks[key] = {
                'supplier_id': key[0], 'agent_id': key[1], 'offer_id': key[2],
                'shipping_rate_id': key[3], 'variant_id': key[4],
                'supplier_sku': offer['supplier_sku'], 'supplier_variant': offer.get('supplier_variant'),
                'currency': 'EUR', 'quantity': 0, 'order_item_ids': [],
                'supplier_currency': offer['currency'], 'supplier_unit_cost_minor': offer.get('unit_cost_cents'),
                'shipping_cost_cents': rate.get('shipping_cost_cents'),
                'group_snapshot': deepcopy(group), 'offer_snapshot': deepcopy(offer),
                'rate_snapshot': deepcopy(rate), 'agent_snapshot': deepcopy(agent),
                'supplier_snapshot': deepcopy(supplier),
                'is_test': True, 'status': 'prepared', 'external_send_allowed': False,
            }
        task = tasks[key]
        for name, value in [('group_snapshot', group), ('offer_snapshot', offer), ('rate_snapshot', rate),
                            ('agent_snapshot', agent), ('supplier_snapshot', supplier)]:
            if task[name] != value:
                raise FulfillmentPlanError('inconsistent_fulfillment_group')
        task['quantity'] += qty
        task['order_item_ids'].append(item_id)
    for task in tasks.values():
        for name in ('supplier_unit_cost_minor', 'shipping_cost_cents'):
            if type(task[name]) is not int or task[name] < 0:
                raise FulfillmentPlanError('unknown_fulfillment_cost')
        expected = task['group_snapshot'].get('lines')
        if (not isinstance(expected, list)
                or sum(x.get('quantity', 0) for x in expected) != task['quantity']
                or len(expected) != len(task['order_item_ids'])):
            raise FulfillmentPlanError('incomplete_fulfillment_group')
        evaluation = task['group_snapshot'].get('evaluation')
        if not isinstance(evaluation, dict) or evaluation.get('currency') != 'EUR' or evaluation.get('status') != 'ready':
            raise FulfillmentPlanError('missing_frozen_cost_evaluation')
        for name in ('supplier_gross_cents','acquisition_net_cents','shipping_net_cents','landed_cost_cents'):
            value = evaluation.get(name)
            if type(value) is not int or value < 0:
                raise FulfillmentPlanError('unknown_fulfillment_cost')
            task[name.replace('_cents','_eur_cents')] = value
        task['supplier_total_cost_minor'] = task['supplier_unit_cost_minor'] * task['quantity']
        task['order_item_ids'].sort()
    return sorted(tasks.values(), key=lambda task: (task['supplier_id'], task['agent_id'], task['offer_id']))


def summarize_test_fulfillment(order, tasks, group_keys):
    """Customer-safe projection of SIM tasks, never a real shipment status.

    Expected groups come from immutable private order lines. Missing/duplicate
    tasks cannot masquerade as a complete delivery. One simulated parcel per
    group is a test contract, NOT a real HyperSKU packing guarantee.
    """
    if order.get('is_test') is not True:
        raise FulfillmentPlanError('test_fulfillment_only')
    oid = _identity(order.get('id'))
    if (not isinstance(tasks, list) or len(tasks) > 100 or not isinstance(group_keys, set)
            or not 1 <= len(group_keys) <= 100 or any(not isinstance(k, str) or not k for k in group_keys)):
        raise FulfillmentPlanError('invalid_simulation_projection')
    parcels, seen_ids, seen_groups = [], set(), set()
    valid_states = {'prepared','received_by_agent','quality_checked','shipped','delivered'}
    for task in tasks:
        if not isinstance(task, dict): raise FulfillmentPlanError('inconsistent_simulation_tasks')
        identity = _identity(task.get('id'))
        group = task.get('group_key')
        state, tracking = task.get('state'), task.get('tracking_number')
        if (not isinstance(group,str) or not isinstance(state,str)
                or task.get('is_test') is not True or _identity(task.get('order_id')) != oid
                or identity in seen_ids or group in seen_groups or group not in group_keys
                or state not in valid_states):
            raise FulfillmentPlanError('inconsistent_simulation_tasks')
        shipped = state in {'shipped','delivered'}
        if ((shipped and (not isinstance(tracking, str) or not re.fullmatch(r'SIM-[A-Za-z0-9_-]{1,100}', tracking)))
                or (not shipped and tracking is not None)):
            raise FulfillmentPlanError('invalid_simulation_tracking')
        seen_ids.add(identity); seen_groups.add(group)
        parcels.append({'reference':'SIM-'+identity,'state':state,'tracking_number':tracking})
    if tasks and seen_groups != group_keys:
        raise FulfillmentPlanError('incomplete_simulation_tasks')
    held = (order.get('status') in {'cancelled','refunded'} or order.get('refunded_amount_cents', 0) != 0
            or order.get('financial_review_required', False) is not False)
    states = [p['state'] for p in parcels]
    if held: aggregate = 'held'
    elif order.get('payment_status') != 'paid': aggregate = 'awaiting_payment'
    elif not states: aggregate = 'requires_review'
    elif all(s == 'delivered' for s in states): aggregate = 'delivered'
    elif 'delivered' in states: aggregate = 'partially_delivered'
    elif all(s == 'shipped' for s in states): aggregate = 'shipped'
    elif 'shipped' in states: aggregate = 'partially_shipped'
    elif all(s == 'prepared' for s in states): aggregate = 'prepared'
    else: aggregate = 'in_progress'
    return {'is_test':True,'scope':'simulation_only_not_real_shipment','aggregate_state':aggregate,
            'simulated_parcel_count':len(parcels),'parcels':sorted(parcels,key=lambda p:p['reference'])}
