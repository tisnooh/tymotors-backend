"""Manual multi-parcel contract in the disposable DB; no real external action."""
import json
from urllib.error import HTTPError
from uuid import uuid4

from tests import commerce_http_probe as probe
from tests import commerce_production_http_probe as context
from tests.commerce_http_probe import ADMIN, HEADERS, eq, request, save, sql


ACCOUNT, PROFILE = context.ACCOUNT, context.PROFILE
RPC = 'public.commerce_advance_context_task(uuid,uuid,timestamptz,text,text,text,text,text,text)'


def snapshot():
    return {table: sql('select row_to_json(t) snapshot from public.'+table+' t order by row_to_json(t)::text')
            for table in ('orders', 'commerce_fulfillment_tasks', 'order_tracking_events', 'email_logs', 'admin_audit')}


def reject(statement, values=(), mutations=()):
    before = snapshot()
    refused = False
    sql('begin')
    try:
        for operation, params in mutations:
            sql(operation, params)
        try:
            sql(statement, list(values))
        except HTTPError as error:
            eq(error.code, 400)
            refused = True
    finally:
        sql('rollback')
    eq(refused, True)
    eq(snapshot(), before)


def row(task_id):
    return sql('select to_jsonb(t) value from commerce_fulfillment_tasks t where id=$1', [task_id])[0]['value']


def advance(task, state, *, proof=None, supplier=None, tracking=None, carrier=None, link=None, expected=200):
    body = {'expected_updated_at': task['updated_at'], 'next': state,
            'supplier_order_ref': supplier, 'tracking_number': tracking, 'carrier': carrier,
            'tracking_url': link, 'evidence_ref': proof or 'SYNTHETIC-EVIDENCE-'+state}
    return request('/admin/commerce/context/tasks/'+task['id']+'/advance', 'POST', body, HEADERS, status=expected)


def sql_advance(task, state, *, proof='SYNTHETIC-MANUAL-EVIDENCE', supplier=None, tracking=None, carrier=None, link=None):
    return ('select commerce_advance_context_task($1,$2,$3,$4,$5,$6,$7,$8,$9)',
            [ADMIN, task['id'], task['updated_at'], state, supplier, tracking, carrier, link, proof])


def make_order(*, groups=1, paid=True, is_test=False, matches=True):
    product = sql("select id from products where sku='TEST-001'")[0]['id']
    supplier = sql("select id from suppliers where name='Fixture supplier' limit 1")[0]['id']
    rule = sql("select * from product_compatibilities where product_id=$1 and verification_state='verified' limit 1", [product])[0]
    agent = save('agent', {'profile_id': ADMIN, 'name': 'Synthetic dispatch operator', 'role': 'orders', 'is_active': True})
    guest = 'synthetic_dispatch_'+uuid4().hex
    headers = {'X-Session-Id': guest}
    vehicle = {'brand_slug': 'bmw', 'model': rule['model_name'], 'chassis': rule['chassis'],
               'year': rule['year_from'], 'facelift': 'pre-lci', 'body_type': 'sedan'}
    for number in range(groups):
        label = 'DISPATCH-'+uuid4().hex
        variant = save('variant', {'product_id': product, 'sku': label, 'name': 'Synthetic parcel '+str(number),
            'price_cents': 3000, 'stock': 3, 'status': 'active', 'is_verified': True, 'requires_vehicle': True,
            'evidence_ref': 'SYNTHETIC ONLY', 'compatibility_ids': [rule['id']]})
        offer = save('offer', {'variant_id': variant['id'], 'supplier_id': supplier, 'supplier_sku': label,
            'supplier_variant': 'Synthetic exact', 'url': 'https://supplier.example.test/'+label,
            'verification_state': 'verified', 'evidence_ref': 'SYNTHETIC ONLY', 'is_primary': True,
            'availability': 'available', 'available_quantity': 3, 'valid_until': '2099-01-01T00:00:00Z',
            'unit_cost_cents': 1000, 'recoverable_tax_cents': 0, 'currency': 'EUR',
            'preparation_days_min': 1, 'preparation_days_max': 2, 'responsible_agent_id': agent['id']})
        save('shipping_rate', {'offer_id': offer['id'], 'country': 'FR', 'mode': 'tracked', 'max_quantity': 3,
            'shipping_cost_cents': 200, 'shipping_recoverable_tax_cents': 0, 'customer_shipping_cents': 500,
            'goods_tax_bps': 0, 'shipping_tax_bps': 0, 'agent_fee_cents': 0, 'import_duty_cents': 0,
            'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0, 'verification_state': 'verified',
            'evidence_ref': 'SYNTHETIC ONLY', 'valid_until': '2099-01-01T00:00:00Z',
            'delivery_days_min': 3, 'delivery_days_max': 5, 'multi_variant_policy': 'independent_parcels'})
        request('/cart', 'POST', {'product_id': product, 'variant_id': variant['id'], 'quantity': 1,
                                 'selected_vehicle': vehicle}, headers)
    quote = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
        'destination': {'name': 'Synthetic dispatch only', 'line1': '1 Synthetic street', 'city': 'Paris',
                        'country': 'FR', 'postal_code': '75001'}}, headers)
    context.enable()
    prepared = context.prepare(quote['quote_id'], guest, is_test=is_test,
        profile='synthetic-dispatch-sandbox' if is_test else PROFILE,
        origin='http://127.0.0.1:8765' if is_test else context.ORIGIN)
    context.params_and_claim(prepared, guest)
    session = context.session_for(prepared)
    session['customer_details'] = {'email': 'synthetic-dispatch@example.com'}
    if paid:
        context.settle(prepared, session, matches=matches)
    tasks = sql('select to_jsonb(t) value from commerce_fulfillment_tasks t where order_id=$1 order by id',
                [prepared['order']['id']])
    return prepared, session, [task['value'] for task in tasks]


def receipt(order_context, session, *, intent=True, account=ACCOUNT, profile=PROFILE, kind='refund.created'):
    event = 'evt_'+uuid4().hex
    object_id = ('re_' if kind.startswith('refund.') else 'pi_')+uuid4().hex
    return sql('select commerce_record_context_event($1,$2,$3,false,$4,$5,$6) value',
        [event, kind, object_id, account, profile, session['payment_intent'] if intent else None])[0]['value']


def main():
    context.main()
    start = probe.checks
    for role in ('anon', 'authenticated'):
        eq(sql("select has_function_privilege($1,$2,'EXECUTE') allowed", [role, RPC])[0]['allowed'], False)
        eq(sql("select has_table_privilege($1,'public.commerce_fulfillment_tasks','UPDATE') allowed", [role])[0]['allowed'], False)
    prepared, session, tasks = make_order(groups=2)
    oid = prepared['order']['id']
    eq(len(tasks), 2)
    listing = request('/admin/commerce/context/orders/'+oid+'/tasks', headers=HEADERS)['items']
    from_get = next(task for task in listing if task['id'] == tasks[0]['id'])
    eq(from_get['updated_at'], tasks[0]['updated_at'])
    tasks[0] = from_get  # GET -> exact version -> mutation, not a fabricated CAS token.
    eq(sql('select requires_compatibility_review from orders where id=$1', [oid])[0]['requires_compatibility_review'], True)
    payload = {'expected_updated_at': tasks[0]['updated_at'], 'next': 'supplier_confirmed',
               'supplier_order_ref': 'SYNTHETIC-SUPPLIER-0', 'evidence_ref': 'SYNTHETIC-REFERENCE-VARIANT-FITMENT-REVIEW'}
    path = '/admin/commerce/context/tasks/'+tasks[0]['id']+'/advance'
    request(path, 'POST', payload, status=401)
    request(path, 'POST', payload, {'Authorization': 'Bearer customer-test-token'}, status=403)
    draft = request('/admin/commerce/context/tasks/'+tasks[0]['id']+'/supplier-draft', headers=HEADERS)
    eq(draft['status'], 'draft_not_transmitted')
    eq(draft['external_send_allowed'], False)
    eq(draft['supplier_id'], tasks[0]['supplier_id'])
    eq(draft['agent_id'], tasks[0]['agent_id'])
    reject(*sql_advance(tasks[0], 'shipped', tracking='SYNTHETIC-TRACK-0', carrier='Synthetic carrier',
                       link='https://tracking.example.com/0'))
    first = request(path, 'POST', payload, HEADERS)
    eq(first['fulfillment_status'], 'requires_review')
    eq(first['notification_log_id'], None)
    eq(sql('select requires_compatibility_review from orders where id=$1', [oid])[0]['requires_compatibility_review'], True)
    eq(request(path, 'POST', payload, HEADERS)['updated'], False)
    reject(*sql_advance(tasks[0], 'supplier_confirmed', proof='DIFFERENT-EVIDENCE', supplier='SYNTHETIC-SUPPLIER-0'))
    second = advance(tasks[1], 'supplier_confirmed', supplier='SYNTHETIC-SUPPLIER-1')
    eq(second['fulfillment_status'], 'processing')
    eq(second['notification_kind'], 'order_processing')
    eq(bool(second['notification_log_id']), True)
    eq(sql('select requires_compatibility_review from orders where id=$1', [oid])[0]['requires_compatibility_review'], False)
    eq(sql("select count(*) n from admin_audit where resource=$1 and action='commerce.compatibility.reviewed'", [oid])[0]['n'], 1)
    current0 = row(tasks[0]['id'])
    stale = {**current0, 'updated_at': tasks[0]['updated_at']}
    reject(*sql_advance(stale, 'shipped', tracking='SYNTHETIC-TRACK-0', carrier='Synthetic carrier',
                       link='https://tracking.example.com/0'))
    for tracking, link in (('SIM-forbidden', 'https://tracking.example.com/0'),
                           ('SYNTHETIC-TRACK-0', 'http://tracking.example.com/0'),
                           ('SYNTHETIC-TRACK-0', 'https://user@tracking.example.com/0')):
        reject(*sql_advance(current0, 'shipped', tracking=tracking, carrier='Synthetic carrier', link=link))
    shipped0 = advance(current0, 'shipped', tracking='SYNTHETIC-TRACK-0', carrier='Synthetic carrier',
                       link='https://tracking.example.com/0')
    eq(shipped0['fulfillment_status'], 'processing')
    eq(shipped0['notification_log_id'], None)
    shipped1 = advance(row(tasks[1]['id']), 'shipped', tracking='SYNTHETIC-TRACK-1', carrier='Synthetic carrier',
                       link='https://tracking.example.com/1')
    eq(shipped1['fulfillment_status'], 'shipped')
    eq(shipped1['notification_kind'], 'order_shipped')
    eq(sql('select tracking_number,carrier,tracking_url from orders where id=$1', [oid]),
       [{'tracking_number': None, 'carrier': None, 'tracking_url': None}])
    public = request('/order-tracking', 'POST', {'order_number': prepared['order']['order_number'],
                                               'email': 'synthetic-dispatch@example.com'})
    eq(len(public['parcels']), 2)
    descriptions = ' '.join(event['description'] for event in public['tracking_events'])
    eq('SYNTHETIC-TRACK-0' in descriptions, True)
    eq('SYNTHETIC-TRACK-1' in descriptions, True)
    eq('unit_cost_cents' in json.dumps(public), False)
    eq('supplier_evidence_ref' in json.dumps(public), False)
    delivered0 = advance(row(tasks[0]['id']), 'delivered')
    eq(delivered0['fulfillment_status'], 'shipped')
    eq(delivered0['notification_log_id'], None)
    delivered1 = advance(row(tasks[1]['id']), 'delivered')
    eq(delivered1['fulfillment_status'], 'delivered')
    eq(delivered1['notification_kind'], 'order_delivered')
    eq(advance(row(tasks[1]['id']), 'delivered')['updated'], False)
    eq(sql("select count(*) n from order_tracking_events where order_id=$1 and event_key like 'commerce_parcel_%'", [oid])[0]['n'], 6)
    for kind in ('order_processing', 'order_shipped', 'order_delivered'):
        eq(sql('select count(*) n from email_logs where order_id=$1 and email_type=$2', [oid, kind])[0]['n'], 1)
    eq(sql('select count(*) n from supplier_orders where order_id=$1', [oid])[0]['n'], 0)
    eq(sql('select bool_or(external_send_allowed) allowed from commerce_fulfillment_tasks where order_id=$1', [oid])[0]['allowed'], False)
    # Refund after explicit supplier confirmation blocks dispatch and any stale
    # queued notification, without inventing returned money or a provider call.
    refund_context, refund_session, refund_tasks = make_order()
    confirmed = advance(refund_tasks[0], 'supplier_confirmed', supplier='SYNTHETIC-REFUND-ORDER')
    eq(receipt(refund_context, refund_session)['requires_reconciliation'], True)
    refund_oid = refund_context['order']['id']
    order = sql('select financial_review_required,refunded_amount_cents,payment_status from orders where id=$1', [refund_oid])[0]
    eq(order, {'financial_review_required': True, 'refunded_amount_cents': 0, 'payment_status': 'paid'})
    reject(*sql_advance(row(refund_tasks[0]['id']), 'shipped', tracking='SYNTHETIC-REFUND-TRACK',
                       carrier='Synthetic carrier', link='https://tracking.example.com/refund'))
    claim = sql('select admin_claim_order_notification($1,$2,$3,true) value',
                [ADMIN, confirmed['notification_log_id'], str(uuid4())])[0]['value']
    eq(claim['claimed'], False)
    eq(claim['state'], 'unknown')
    # Physical delivery remains recordable after financial review. It is not
    # permission to dispatch any other still-unshipped group of the same order.
    late_context, late_session, late_tasks = make_order(groups=2)
    for index, task in enumerate(late_tasks):
        advance(task, 'supplier_confirmed', supplier='SYNTHETIC-LATE-'+str(index))
    advance(row(late_tasks[0]['id']), 'shipped', tracking='SYNTHETIC-LATE-SHIPPED',
            carrier='Synthetic carrier', link='https://tracking.example.com/late')
    receipt(late_context, late_session)
    reject(*sql_advance(row(late_tasks[1]['id']), 'shipped', tracking='SYNTHETIC-LATE-BLOCKED',
                       carrier='Synthetic carrier', link='https://tracking.example.com/blocked'))
    delivered_after_review = advance(row(late_tasks[0]['id']), 'delivered')
    eq(delivered_after_review['task_state'], 'delivered')
    eq(delivered_after_review['fulfillment_status'], 'processing')
    eq(advance(row(late_tasks[0]['id']), 'delivered')['updated'], False)
    eq(sql('select financial_review_required,refunded_amount_cents,payment_status from orders where id=$1',
           [late_context['order']['id']])[0],
       {'financial_review_required': True, 'refunded_amount_cents': 0, 'payment_status': 'paid'})
    # A complete physical delivery updates only the logistics aggregate after
    # review/cancellation; it never clears a new compatibility/financial hold.
    physical_context, physical_session, physical_tasks = make_order()
    advance(physical_tasks[0], 'supplier_confirmed', supplier='SYNTHETIC-PHYSICAL-DELIVERY')
    advance(row(physical_tasks[0]['id']), 'shipped', tracking='SYNTHETIC-PHYSICAL',
            carrier='Synthetic carrier', link='https://tracking.example.com/physical')
    receipt(physical_context, physical_session)
    sql("update orders set status='cancelled',requires_compatibility_review=true where id=$1", [physical_context['order']['id']])
    physical = advance(row(physical_tasks[0]['id']), 'delivered')
    eq(physical['fulfillment_status'], 'delivered')
    eq(sql('select status,financial_review_required,requires_compatibility_review,refunded_amount_cents from orders where id=$1',
           [physical_context['order']['id']])[0],
       {'status': 'cancelled', 'financial_review_required': True, 'requires_compatibility_review': True, 'refunded_amount_cents': 0})
    eq(sql('select delivery_state from email_logs where id=$1', [physical['notification_log_id']])[0]['delivery_state'], 'unknown')
    # Refund-before-payment is retained and becomes a sticky review at settlement.
    before_context, before_session, _ = make_order(paid=False)
    receipt(before_context, before_session)
    context.settle(before_context, before_session)
    eq(sql('select financial_review_required from orders where id=$1', [before_context['order']['id']])[0]['financial_review_required'], True)
    before_task = sql('select * from commerce_fulfillment_tasks where order_id=$1', [before_context['order']['id']])[0]
    reject(*sql_advance(before_task, 'supplier_confirmed', supplier='SYNTHETIC-BEFORE-PAYMENT'))
    # A matching opaque PI from another profile/account never holds this order.
    clean_context, clean_session, clean_tasks = make_order()
    receipt(clean_context, clean_session, account=context.OTHER, profile='synthetic-context-other')
    eq(sql('select financial_review_required from orders where id=$1', [clean_context['order']['id']])[0]['financial_review_required'], False)
    receipt(clean_context, clean_session, intent=False, kind='payment_intent.payment_failed')
    eq(sql('select financial_review_required from orders where id=$1', [clean_context['order']['id']])[0]['financial_review_required'], False)
    advance(clean_tasks[0], 'supplier_confirmed', supplier='SYNTHETIC-CLEAN-ORDER')
    # Known cancellation, refund amount and stock incident cannot be shipped.
    clean_task = row(clean_tasks[0]['id'])
    operation, values = sql_advance(clean_task, 'shipped', tracking='SYNTHETIC-CLEAN-TRACK',
        carrier='Synthetic carrier', link='https://tracking.example.com/clean')
    for mutation in ("status='cancelled'", 'refunded_amount_cents=1', 'financial_review_required=true', 'stock_applied_at=null'):
        reject(operation, values, [('update orders set '+mutation+' where id=$1', [clean_context['order']['id']])])
    sandbox_context, _, sandbox_tasks = make_order(is_test=True)
    reject(*sql_advance(sandbox_tasks[0], 'supplier_confirmed', supplier='SYNTHETIC-NOT-REAL-SANDBOX'))
    incident_context, _, incident_tasks = make_order(matches=False)
    advance(incident_tasks[0], 'supplier_confirmed', supplier='SYNTHETIC-INCIDENT-DOSSIER')
    reject(*sql_advance(row(incident_tasks[0]['id']), 'shipped', tracking='SYNTHETIC-INCIDENT',
        carrier='Synthetic carrier', link='https://tracking.example.com/incident'))
    # Missing PI remains explicitly unbound and holds only its server profile;
    # it cannot be guessed into an arbitrary matching order.
    unbound = receipt(clean_context, clean_session, intent=False)
    eq(unbound['unbound_refund_requires_manual_review'], True)
    reject(operation, values)
    sql('update shop_settings set commerce_live_enabled=false where id')
    print(json.dumps({'manual_context_dispatch_checks': probe.checks-start,
        'multi_parcel_groups': 2, 'supplier_calls': 0, 'carrier_calls': 0, 'actual_shipments': 0,
        'actual_refunds': 0, 'real_payments': 0, 'live_gate_final': False}))


if __name__ == '__main__':
    main()
