"""Owned synthetic HTTP/SQL financial outbox; no SMTP, Stripe or suppliers.

Non-test legacy rows below are disposable SQL fixtures, not real customer orders.
Completion RPC calls simulate transport results and prove NO delivery.
"""
from copy import deepcopy
import json
from urllib.error import HTTPError
from uuid import uuid4

from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import ADMIN, eq, sql


CLAIM = 'select public.admin_claim_order_notification($1,$2,$3,$4) value'
FINISH = 'select public.complete_order_notification($1,$2,$3,$4) value'


def one(statement, params=()):
    return sql(statement, list(params))[0]


def protected():
    return {table: sorted(sql('select row_to_json(t) snapshot from public.' + table + ' t'),
                          key=lambda row: json.dumps(row, sort_keys=True))
            for table in ('orders', 'order_items', 'email_logs', 'admin_audit', 'supplier_orders',
                          'supplier_order_items', 'order_tracking_events', 'commerce_checkout_attempts',
                          'commerce_test_payment_events', 'commerce_test_refund_events')}


def reject(statement, params=(), *, setup=(), contains=None):
    before = protected()
    refused = False
    sql('begin')
    try:
        for operation in setup:
            sql(operation)
        try:
            sql(statement, list(params))
        except HTTPError as error:
            eq(error.code, 400)
            if contains is not None:
                diagnostic = error.read().decode()
                if contains not in diagnostic:
                    raise AssertionError('Synthetic financial SQL refusal mismatch: ' + diagnostic)
                eq(True, True)
            refused = True
    finally:
        sql('rollback')
    eq(refused, True)
    eq(protected(), before)


def log(order, kind, cumulative=None):
    suffix = str(cumulative) if kind == 'refund_confirmed' else 'once'
    return one('select * from email_logs where idempotency_key=$1',
               [f'order:{order["id"]}:{kind}:{suffix}'])


def claim(row, *, ready=True):
    token = str(uuid4())
    return one(CLAIM, [ADMIN, row['id'], token, ready])['value'], token


def main():
    pipeline.main()
    start = probe.checks
    product = one("select id from products where sku='TEST-001'")['id']
    customer = one("select id from profiles where role='customer' order by id limit 1")['id']

    def seed(*, paid=False, is_test=False, user_id=None):
        order = one("insert into orders(order_number,subtotal_cents,total_cents,customer_email,is_test,user_id) "
                    "values('FINANCIAL-OUTBOX-'||gen_random_uuid(),1000,1000,'frozen@example.test',$1,$2) returning *", [is_test, user_id])
        sql("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents) "
            "values($1,$2,'Synthetic financial item','test-product','FINANCIAL-FIXTURE',1,1000)", [order['id'], product])
        if paid:
            pay(order)
        return one('select * from orders where id=$1', [order['id']])

    def pay(order):
        sql("update orders set payment_status='paid',status='paid',stripe_payment_intent_id=$2,paid_at=now() where id=$1",
            [order['id'], 'pi_synthetic_' + uuid4().hex])

    def refund(order, cents):
        sql('select public.record_order_refund($1,$2)', [order['stripe_payment_intent_id'], cents])

    # Atomicity includes the financial row, legacy supplier preparation and audit:
    # rejection of the outbox insert must roll back the complete SQL transition.
    injected = ["""create function public.qa_reject_financial_notification() returns trigger language plpgsql as $$
        begin if new.event_snapshot is not null and new.email_type in ('payment_confirmed','refund_confirmed')
          then raise exception 'Injected financial outbox failure'; end if; return new; end $$""",
        'create trigger qa_financial_outbox before insert on email_logs for each row execute function public.qa_reject_financial_notification()']
    pending = seed()
    reject("update orders set payment_status='paid',status='paid',stripe_payment_intent_id='pi_synthetic_rollback' where id=$1",
           [pending['id']], setup=injected, contains='Injected financial outbox failure')
    rollback_refund = seed(paid=True)
    reject('select public.record_order_refund($1,250)', [rollback_refund['stripe_payment_intent_id']],
           setup=injected, contains='Injected financial outbox failure')

    paid = seed(paid=True)
    payment = log(paid, 'payment_confirmed')
    eq(payment['delivery_state'], 'pending')
    eq(payment['status'], 'queued')
    eq(payment['event_snapshot']['version'], 1)
    eq(payment['event_snapshot']['financial']['kind'], 'payment_confirmed')
    eq(payment['event_snapshot']['financial']['refunded_amount_cents'], 0)
    eq(payment['event_snapshot']['financial']['total_cents'], 1000)
    eq(payment['event_snapshot']['financial']['payment_intent_id'], paid['stripe_payment_intent_id'])
    eq(isinstance(payment['event_snapshot']['financial']['occurred_at'], str), True)
    eq(payment['event_snapshot']['order']['is_test'], False)
    eq(payment['event_snapshot']['order']['owner_user_id'], None)
    eq('guest_session_id' in payment['event_snapshot']['order'], False)
    eq(payment['event_snapshot']['items'][0]['sku'], 'FINANCIAL-FIXTURE')
    eq('shipping_address' in payment['event_snapshot']['order'], False)
    frozen = deepcopy(payment)
    sql("update orders set payment_status='paid',fulfillment_status='processing',customer_email='changed@example.test' where id=$1", [paid['id']])
    eq(log(paid, 'payment_confirmed'), frozen)
    eq(one("select count(*) n from email_logs where order_id=$1 and email_type='payment_confirmed'", [paid['id']])['n'], 1)
    # Fulfillment progress cannot invalidate a financial receipt with unchanged funds.
    eq(claim(payment, ready=False)[0], {'claimed': False, 'state': 'blocked'})
    accepted, token = claim(payment)
    eq(accepted, {'claimed': True, 'state': 'claimed'})
    eq(claim(payment)[0], {'claimed': False, 'state': 'claimed'})
    eq(one(FINISH, [payment['id'], str(uuid4()), 'sent', 'synthetic-provider'])['value']['completed'], False)
    eq(one(FINISH, [payment['id'], token, 'sent', 'synthetic-provider'])['value'], {'completed': True, 'state': 'sent'})
    eq(claim(payment)[0], {'claimed': False, 'state': 'sent'})
    reject('update email_logs set event_snapshot=\'{}\'::jsonb where id=$1', [payment['id']], contains='immutable')
    reject('delete from email_logs where id=$1', [payment['id']], contains='cannot be deleted')

    for mutation in ("status='cancelled'", "payment_status='unpaid'", "payment_status='refunded',status='refunded'",
                     "refunded_amount_cents=100", "financial_review_required=true",
                     "stripe_payment_intent_id='pi_synthetic_changed'", "total_cents=1100"):
        changed = seed(paid=True)
        notification = log(changed, 'payment_confirmed')
        sql('update orders set ' + mutation + ' where id=$1', [changed['id']])
        eq(claim(notification)[0], {'claimed': False, 'state': 'unknown'})
    owned = seed(paid=True, user_id=customer)
    owned_log = log(owned, 'payment_confirmed')
    eq(owned_log['event_snapshot']['order']['owner_user_id'], customer)
    sql('update orders set user_id=$2 where id=$1', [owned['id'], ADMIN])
    # Even changing the log's FK cannot change the immutable captured owner.
    sql('update email_logs set user_id=$2 where id=$1', [owned_log['id'], ADMIN])
    eq(claim(owned_log)[0], {'claimed': False, 'state': 'unknown'})
    for malformed in ("currency='USD'", "subtotal_cents=0,total_cents=0",
                      'total_cents=1100', 'tax_amount_cents=1100'):
        invalid = seed()
        sql('update orders set '+malformed+' where id=$1', [invalid['id']])
        pay(invalid)
        # Snapshot and row agree, so this independently tests the SQL guard,
        # rather than merely rejecting a changed amount relative to the snapshot.
        eq(claim(log(invalid, 'payment_confirmed'))[0], {'claimed': False, 'state': 'unknown'})

    partial = seed(paid=True)
    refund(partial, 300)
    r300 = log(partial, 'refund_confirmed', 300)
    eq(r300['event_snapshot']['financial']['kind'], 'refund_confirmed')
    eq(r300['event_snapshot']['financial']['refunded_amount_cents'], 300)
    eq(r300['event_snapshot']['financial']['total_cents'], 1000)
    eq(r300['event_snapshot']['order']['refunded_amount_cents'], 300)
    refund(partial, 300)
    eq(log(partial, 'refund_confirmed', 300), r300)
    eq(one("select count(*) n from email_logs where order_id=$1 and email_type='refund_confirmed'", [partial['id']])['n'], 1)
    refund(partial, 500)
    r500 = log(partial, 'refund_confirmed', 500)
    eq(claim(r300)[0], {'claimed': False, 'state': 'unknown'})
    accepted, token = claim(r500)
    eq(accepted, {'claimed': True, 'state': 'claimed'})
    eq(one(FINISH, [r500['id'], token, 'unknown', None])['value'], {'completed': True, 'state': 'unknown'})
    eq(claim(r500)[0], {'claimed': False, 'state': 'unknown'})
    refund(partial, 1000)
    eq(claim(log(partial, 'refund_confirmed', 1000))[0], {'claimed': True, 'state': 'claimed'})
    eq(one('select refunded_amount_cents from orders where id=$1', [partial['id']])['refunded_amount_cents'], 1000)
    cancelled = seed(paid=True)
    sql("update orders set status='cancelled' where id=$1", [cancelled['id']])
    refund(cancelled, 250)
    eq(claim(log(cancelled, 'refund_confirmed', 250))[0], {'claimed': True, 'state': 'claimed'})
    reviewed = seed(paid=True)
    refund(reviewed, 250)
    sql('update orders set financial_review_required=true where id=$1', [reviewed['id']])
    eq(claim(log(reviewed, 'refund_confirmed', 250))[0], {'claimed': False, 'state': 'unknown'})
    for amount, bad_status in ((250, 'refunded'), (1000, 'paid')):
        inconsistent = seed(paid=True)
        refund(inconsistent, amount)
        notification = log(inconsistent, 'refund_confirmed', amount)
        sql('update orders set payment_status=$2 where id=$1', [inconsistent['id'], bad_status])
        eq(claim(notification)[0], {'claimed': False, 'state': 'unknown'})

    # A collision is a tombstone, not permission to rewrite or resend old logs.
    for status in ('queued', 'failed', 'sent'):
        historical = seed()
        existing = one("insert into email_logs(order_id,recipient,email_type,status,error_message,idempotency_key) "
                       "values($1,'legacy@example.test','payment_confirmed',$2,'Historical unknown outcome',$3) returning *",
                       [historical['id'], status, f'order:{historical["id"]}:payment_confirmed:once'])
        pay(historical)
        eq(log(historical, 'payment_confirmed'), existing)
        eq(claim(existing)[0], {'claimed': False, 'state': 'sent' if status == 'sent' else 'legacy_review'})
    old_refund = seed(paid=True)
    existing = one("insert into email_logs(order_id,recipient,email_type,status,idempotency_key) "
                   "values($1,'legacy@example.test','refund_confirmed','failed',$2) returning *",
                   [old_refund['id'], f'order:{old_refund["id"]}:refund_confirmed:200'])
    refund(old_refund, 200)
    eq(log(old_refund, 'refund_confirmed', 200), existing)
    eq(claim(existing)[0], {'claimed': False, 'state': 'legacy_review'})

    test = seed(paid=True, is_test=True)
    refund(test, 100)
    eq(one('select count(*) n from email_logs where order_id=$1', [test['id']])['n'], 0)
    quoted = one('select * from orders where commerce_quote_id is not null and payment_status=\'paid\' and stripe_payment_intent_id is not null order by id limit 1')
    reject('select public.record_order_refund($1,100)', [quoted['stripe_payment_intent_id']],
           contains='Quoted refunds require their reviewed financial ledger')

    for signature in ('private.enqueue_financial_order_notification()',
                      'private.financial_order_notification_matches(public.email_logs,public.orders)',
                      'public.admin_claim_order_notification(uuid,uuid,uuid,boolean)',
                      'public.complete_order_notification(uuid,uuid,text,text)'):
        for role in ('anon', 'authenticated', 'service_role'):
            eq(one('select has_function_privilege($1,$2,\'EXECUTE\') allowed',
                   [role, signature])['allowed'], role == 'service_role')
    reject(CLAIM, [customer, payment['id'], str(uuid4()), True], contains='Admin role')
    print(json.dumps({'financial_outbox_checks': probe.checks-start,
                      'stripe_transport': 'FAKE', 'smtp_calls': 0, 'supplier_api_calls': 0,
                      'financial_delivery_proven': False, 'production_access': False}))


if __name__ == '__main__':
    main()
