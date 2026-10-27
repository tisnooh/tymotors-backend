"""Signed local HTTP -> disposable SQL refund receipts, NOT real Stripe refunds.

Runs the existing complete synthetic commerce pipeline first. No hosted database,
real provider, customer email, refund creation, stock release or supplier call.
"""
from copy import deepcopy
import json
from urllib.error import HTTPError
from uuid import uuid4

from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import sql, request, eq, HEADERS


def refund(intent, amount=1000, status='succeeded', *, refund_id=None, currency='eur'):
    return {'object': 'event', 'id': 'evt_' + uuid4().hex,
        'created': 1793050000, 'type': 'refund.updated', 'livemode': False,
        'data': {'object': {'object': 'refund', 'id': refund_id or 're_' + uuid4().hex,
            'payment_intent': intent, 'charge': 'ch_' + intent.removeprefix('pi_') if intent else None,
            'amount': amount, 'currency': currency, 'status': status,
            'metadata': {'order_id': 'untrusted', 'quote_id': 'untrusted'},
            'description': 'PRIVATE DATA MUST NOT BE STORED'}}}


def order(identity):
    return sql('select * from orders where id=$1', [identity])[0]


def money(identity, cents, *, full=False):
    row = order(identity)
    eq(row['refunded_amount_cents'], cents)
    eq(row['financial_review_required'], True)
    eq(row['payment_status'], 'refunded' if full else 'paid')


def reject_sql(statement, params=()):
    try:
        sql(statement, list(params))
    except HTTPError as error:
        eq(error.code, 400)
        return
    raise AssertionError('SQL unexpectedly accepted invalid/unauthorized mutation')


def main():
    pipeline.main()
    start = probe.checks
    table = 'public.commerce_test_refund_events'
    eq(sql('select relrowsecurity rls from pg_class where oid=$1::regclass', [table])[0]['rls'], True)
    for role in ('anon', 'authenticated'):
        for permission in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
            eq(sql('select has_table_privilege($1,$2,$3) allowed', [role,table,permission])[0]['allowed'], False)
        for signature in ('public.commerce_record_test_refund(jsonb)',
                          'private.commerce_project_test_refunds(uuid)', 'private.commerce_test_refund_hold(uuid)'):
            eq(sql("select has_function_privilege($1,$2,'EXECUTE') allowed", [role,signature])[0]['allowed'], False)
    for permission in ('UPDATE','DELETE','TRUNCATE'):
        eq(sql('select has_table_privilege($1,$2,$3) allowed', ['service_role',table,permission])[0]['allowed'], False)
    rows = sql("""select o.id,t.id task_id,t.tracking_number,t.state,prep.mapping_id
        from orders o join commerce_test_tasks t on t.order_id=o.id
        join commerce_hypersku_preparations prep on prep.task_id=t.id
        where t.state='delivered' and o.payment_status='paid' order by o.created_at""")
    eq(len(rows), 5)
    originals = sql("""select (select jsonb_agg(row_to_json(x) order by id) from product_variants x) variants,
      (select jsonb_agg(row_to_json(x) order by id) from supplier_offers x) offers,
      (select count(*) from supplier_orders) supplier_orders,
      (select count(*) from email_logs) emails,
      (select count(*) from commerce_test_task_events) task_events,
      (select count(*) from commerce_hypersku_preparations) preparations""")[0]
    oid = rows[0]['id']
    intent = order(oid)['stripe_payment_intent_id']
    pending = refund(intent, status='pending')
    count = sql('select count(*) n from commerce_test_refund_events')[0]['n']
    pipeline.webhook(pending, valid=False, expected=400)
    live = deepcopy(pending); live['livemode'] = True
    pipeline.webhook(live, expected=400)
    malformed = deepcopy(pending); malformed['data']['object']['amount'] = True
    pipeline.webhook(malformed, expected=400)
    eq(sql('select count(*) n from commerce_test_refund_events')[0]['n'], count)
    receipt = pipeline.webhook(pending)
    eq(receipt['requires_reconciliation'], True)
    money(oid, 0)
    simulation = request('/admin/commerce/orders/'+oid+'/simulation-status',headers=HEADERS)
    eq(simulation['aggregate_state'],'held')
    tracking = request('/order-tracking','POST',{'order_number':order(oid)['order_number'],'email':'recipient@example.com'})
    eq(tracking['simulation']['aggregate_state'],'held')
    eq('financial_review_required' in tracking,False)
    # Even a zero-valued pending refund blocks replay/progression of old packets.
    request('/admin/commerce/test-tasks/'+rows[0]['task_id']+'/simulate', 'POST',
        {'expected':'shipped','next':'delivered','tracking_number':rows[0]['tracking_number']}, HEADERS, status=409)
    request('/admin/commerce/hypersku/tasks/'+rows[0]['task_id']+'/prepare', 'POST',
        {'mapping_id': rows[0]['mapping_id']}, HEADERS, status=409)
    eq(pipeline.webhook(pending)['duplicate'], True)
    succeeded = deepcopy(pending)
    succeeded['id'] = 'evt_' + uuid4().hex
    succeeded['data']['object']['status'] = 'succeeded'
    pipeline.webhook(succeeded)
    money(oid, 1000)
    different_event_same_refund = deepcopy(succeeded)
    different_event_same_refund.update(id='evt_'+uuid4().hex, type='refund.created')
    pipeline.webhook(different_event_same_refund)
    money(oid, 1000)
    late_pending = deepcopy(pending); late_pending['id'] = 'evt_' + uuid4().hex
    pipeline.webhook(late_pending)
    money(oid, 1000)
    charge = {'object':'event','id':'evt_'+uuid4().hex,'created':1793050000,
        'livemode':False,'type':'charge.refunded','data':{'object':{'object':'charge',
            'id':succeeded['data']['object']['charge'],'payment_intent':intent,
            'amount_refunded':1000,'currency':'eur','livemode':False}}}
    pipeline.webhook(charge)
    money(oid, 1000)  # Cumulative charge observation is NOT another refund.
    pipeline.webhook(refund(intent, amount=order(oid)['total_cents']-1000))
    money(oid, order(oid)['total_cents'], full=True)
    # Late real payment success replays cannot resurrect the refunded order.
    context = sql("""select e.*,a.commerce_quote_id,a.expires_at from commerce_test_payment_events e
        join commerce_checkout_attempts a on a.id=e.attempt_id where a.order_id=$1 limit 1""", [oid])[0]
    def paid_event(local_order, context, pi):
        return {'object':'event','id':'evt_'+uuid4().hex,'type':'checkout.session.completed','livemode':False,
            'data':{'object':{'object':'checkout.session','id':context['session_id'],'mode':'payment',
                'livemode':False,'status':'complete','payment_status':'paid','currency':'eur',
                'client_reference_id':local_order['id'],'expires_at':int(context['expires_at']),
                'metadata':{'order_id':local_order['id'],'quote_id':context['commerce_quote_id'],
                    'attempt_id':context.get('attempt_id', context.get('id'))},
                'amount_total':local_order['total_cents'],'amount_subtotal':local_order['subtotal_cents'],
                'total_details':{'amount_shipping':local_order['shipping_amount_cents'],'amount_tax':0,'amount_discount':0},
                'automatic_tax':{'enabled':False},'payment_intent':pi,
                'shipping_details':{'address':local_order['shipping_address']}}}}
    eq(pipeline.webhook(paid_event(order(oid), context, intent))['duplicate'], True)
    money(oid, order(oid)['total_cents'], full=True)
    # Mismatched currency and over-total receipts persist but are not money.
    second = rows[1]['id']; second_pi = order(second)['stripe_payment_intent_id']
    bad_currency = refund(second_pi, currency='usd')
    pipeline.webhook(bad_currency)
    money(second, 0)
    collision = deepcopy(bad_currency); collision['data']['object']['amount'] += 1
    pipeline.webhook(collision, expected=500)
    eq(sql('select amount_cents from commerce_test_refund_events where event_id=$1', [bad_currency['id']])[0]['amount_cents'],1000)
    third = rows[2]['id']; third_pi = order(third)['stripe_payment_intent_id']
    over = refund(third_pi, order(third)['total_cents']+1)
    eq(pipeline.webhook(over)['reason'], 'refund_identity_or_total_conflict')
    money(third, 0)
    fourth = rows[3]['id']; fourth_pi = order(fourth)['stripe_payment_intent_id']
    terminal = refund(fourth_pi, 100)
    pipeline.webhook(terminal)
    money(fourth,100)
    failed = deepcopy(terminal)
    failed.update(id='evt_'+uuid4().hex, type='refund.failed')
    failed['data']['object']['status']='failed'
    eq(pipeline.webhook(failed)['reason'], 'refund_identity_or_total_conflict')
    money(fourth,100)  # Review, never erase already recorded financial history.
    fifth = rows[4]['id']; fifth_pi = order(fifth)['stripe_payment_intent_id']
    for state in ('failed','canceled','requires_action',None):
        pipeline.webhook(refund(fifth_pi,100,status=state))
        money(fifth,0)
    contradictory=refund(fifth_pi,100)
    contradictory['type']='refund.failed'
    eq(pipeline.webhook(contradictory)['reason'],'refund_identity_or_total_conflict')
    money(fifth,0)
    reused=refund(fifth_pi,100,refund_id=terminal['data']['object']['id'])
    eq(pipeline.webhook(reused)['reason'],'refund_identity_or_total_conflict')
    money(fifth,0)
    money(fourth,100)
    unbound = refund(None)
    eq(pipeline.webhook(unbound)['reason'], 'unbound_test_refund_receipt')
    # Existing bound session whose payment was rejected cross-order in pipeline.
    before = sql("""select a.*,s.session_id from commerce_checkout_attempts a
        join orders o on o.id=a.order_id join commerce_test_sessions s on s.attempt_id=a.id
        where o.commerce_quote_id is not null and o.payment_status='unpaid' limit 1""")[0]
    before_oid = before['order_id']; before_pi = 'pi_' + uuid4().hex
    early = refund(before_pi,1200)
    # Metadata may target an unrelated order, but cannot bind a refund to it.
    early['data']['object']['metadata']={'order_id':fifth, 'attempt_id':before['id']}
    eq(pipeline.webhook(early)['reason'], 'unbound_test_refund_receipt')
    eq(order(before_oid)['financial_review_required'],False)
    result = pipeline.webhook(paid_event(order(before_oid),before,before_pi))
    eq(result['fulfillment_held'],True)
    money(before_oid,1200)
    eq(sql('select count(*) n from commerce_test_tasks where order_id=$1',[before_oid])[0]['n'],0)
    eq(sql('select count(*) n from commerce_test_refund_events where event_id=$1',[early['id']])[0]['n'],1)
    # Minimal immutable history, never supplier/customer metadata/URLs/descriptions.
    persisted = sql('select * from commerce_test_refund_events where event_id=$1',[early['id']])[0]
    eq('metadata' in persisted,False)
    eq('description' in persisted,False)
    for statement in ('update commerce_test_refund_events set currency=\'usd\'',
                      'delete from commerce_test_refund_events','truncate commerce_test_refund_events'):
        reject_sql(statement)
    # A direct privileged RPC cannot bypass numeric/schema validation.
    from app.commerce_refund_events import normalize_test_refund_event
    normalized=normalize_test_refund_event(refund(before_pi))
    for key,value in [('event_created',True),('amount_cents',0),('amount_cents',1.1),
                      ('currency','EUR'),('event_type','unknown'),('refund_id',None)]:
        reject_sql('select commerce_record_test_refund($1)',[json.dumps({**normalized,key:value})])
    final = sql("""select (select jsonb_agg(row_to_json(x) order by id) from product_variants x) variants,
      (select jsonb_agg(row_to_json(x) order by id) from supplier_offers x) offers,
      (select count(*) from supplier_orders) supplier_orders,
      (select count(*) from email_logs) emails,
      (select count(*) from commerce_test_task_events) task_events,
      (select count(*) from commerce_hypersku_preparations) preparations""")[0]
    eq(final, originals)
    print(json.dumps({'refund_checks':probe.checks-start, 'total_checks':probe.checks,
        'result':'passed','stripe_transport':'FAKE','signature_verification':'real SDK/local HMAC',
        'real_refunds':0,'provider_calls':0,'production_access':False}))


if __name__ == '__main__':
    main()
