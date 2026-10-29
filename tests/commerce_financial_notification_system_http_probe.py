"""Disposable SQL claims only: no worker startup, SMTP or real Stripe/provider.

The persisted enable flag is toggled solely inside this isolated fixture DB.
No native multi-connection PostgreSQL concurrency proof is claimed.
"""
import json
from uuid import uuid4
from urllib.error import HTTPError

from tests import commerce_financial_outbox_http_probe as financial
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import ADMIN, eq, sql


SYSTEM = 'select public.commerce_claim_financial_notification($1,$2,$3) value'
CORE = 'select private.claim_order_notification_core($1,$2,$3,$4,$5) value'
one = financial.one


def settings(enabled):
    sql('update shop_settings set financial_notification_auto_enabled=$1 where id', [enabled])


def protected():
    return {'tables': financial.protected(), 'settings': sql('select row_to_json(s) snapshot from shop_settings s')}


def system(row, *, ready=True):
    token = str(uuid4())
    return one(SYSTEM, [row['id'], token, ready])['value'], token


def unchanged(row, expected, *, ready=True):
    before = protected()
    result, _ = system(row, ready=ready)
    eq(result, {'claimed': False, 'state': expected})
    eq(protected(), before)


def reject(statement, params, *, contains):
    before = protected()
    financial.reject(statement, params, contains=contains)
    eq(protected(), before)


def main():
    financial.main()  # Existing admin claim, financial validation and lifecycle regression.
    start = probe.checks
    eq(one('select financial_notification_auto_enabled value from shop_settings where id')['value'], False)
    product = one("select id from products where sku='TEST-001'")['id']
    customer = one("select id from profiles where role='customer' order by id limit 1")['id']

    def seed(*, user=None):
        order = one("insert into orders(order_number,subtotal_cents,total_cents,customer_email,user_id) "
                    "values('SYSTEM-FINANCIAL-'||gen_random_uuid(),1000,1000,'frozen@example.test',$1) returning *", [user])
        sql("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents) "
            "values($1,$2,'Synthetic system item','test-product','SYSTEM-FIXTURE',1,1000)", [order['id'], product])
        sql("update orders set payment_status='paid',status='paid',stripe_payment_intent_id=$2 where id=$1",
            [order['id'], 'pi_synthetic_system_' + uuid4().hex])
        order = one('select * from orders where id=$1', [order['id']])
        return order, financial.log(order, 'payment_confirmed')

    order, payment = seed()
    unchanged(payment, 'disabled')
    unchanged(payment, 'disabled', ready=False)
    before = protected()
    eq(one(CORE, [None, payment['id'], str(uuid4()), True, 'systemfinancial'])['value'],
       {'claimed': False, 'state': 'disabled'})
    eq(protected(), before)

    # Missing singleton and denied settings SELECT both fail closed without touching logs.
    sql('begin')
    try:
        sql('delete from shop_settings where id')
        unchanged(payment, 'disabled')
    finally:
        sql('rollback')
    sql('begin')
    try:
        sql('revoke select on shop_settings from service_role')
        sql('set local role service_role')
        eq(system(payment)[0], {'claimed': False, 'state': 'disabled'})
    finally:
        sql('rollback')
    eq(protected(), before)

    for principal, actor in [('unknown', None), (None, None), ('systemfinancial', ADMIN)]:
        reject(CORE, [actor, payment['id'], str(uuid4()), True, principal],
               contains='principal' if principal != 'systemfinancial' else 'impersonate')
    reject(CORE, [customer, payment['id'], str(uuid4()), True, 'admin'], contains='Admin role')
    for signature in ('private.claim_order_notification_core(uuid,uuid,uuid,boolean,text)',
                      'public.commerce_claim_financial_notification(uuid,uuid,boolean)',
                      'public.admin_claim_order_notification(uuid,uuid,uuid,boolean)'):
        for role in ('anon', 'authenticated', 'service_role'):
            eq(one("select has_function_privilege($1,$2,'EXECUTE') allowed", [role, signature])['allowed'],
               role == 'service_role')
    eq(one("select prosecdef value from pg_proc where oid='public.commerce_claim_financial_notification(uuid,uuid,boolean)'::regprocedure")['value'], False)

    # All activation below is disposable fixture setup, never a deployment setting.
    settings(True)
    try:
        blocked, token = system(payment, ready=False)
        eq(blocked, {'claimed': False, 'state': 'blocked'})
        eq(one('select delivery_token value from email_logs where id=$1', [payment['id']])['value'], None)
        settings(False)
        unchanged(payment, 'disabled')
        settings(True)
        result, token = system(payment)
        eq(result, {'claimed': True, 'state': 'claimed'})
        audit = one("select admin_user_id,metadata from admin_audit where resource=$1 and action='email.outbox_claim'", [payment['id']])
        eq(audit['admin_user_id'], None)
        eq(audit['metadata']['principal'], 'systemfinancial')
        unchanged(payment, 'claimed')
        before_claimed = protected()
        eq(financial.claim(payment)[0], {'claimed': False, 'state': 'claimed'})
        eq(protected(), before_claimed)
        settings(False)
        unchanged(payment, 'disabled')
        # Stop prevents new claims, but does not discard an already-known result.
        eq(one(financial.FINISH, [payment['id'], token, 'sent', 'synthetic-result'])['value'],
           {'completed': True, 'state': 'sent'})
        settings(True)
        unchanged(payment, 'sent')

        _, admin_first = seed()
        eq(financial.claim(admin_first)[0], {'claimed': True, 'state': 'claimed'})
        unchanged(admin_first, 'claimed')

        _, uncertain = seed()
        result, uncertain_token = system(uncertain)
        eq(result['claimed'], True)
        eq(one(financial.FINISH, [uncertain['id'], uncertain_token, 'unknown', None])['value']['completed'], True)
        unchanged(uncertain, 'unknown')

        # System scope excludes fulfillment, historical collisions, wrong sources and test orders.
        sql("update orders set fulfillment_status='processing' where id=$1", [order['id']])
        fulfillment_id = one("select private.enqueue_order_notification($1,'order_processing') value", [order['id']])['value']
        unchanged({'id': fulfillment_id}, 'not_eligible')
        legacy = one("insert into email_logs(order_id,recipient,email_type,status,idempotency_key) "
                     "values($1,'legacy@example.test','payment_confirmed','failed',$2) returning *",
                     [order['id'], 'legacy-system-' + uuid4().hex])
        unchanged(legacy, 'not_eligible')
        _, wrong_source = seed()
        sql("update email_logs set metadata=jsonb_set(metadata,'{source}','\"historical_import\"') where id=$1", [wrong_source['id']])
        unchanged(wrong_source, 'not_eligible')
        test_order = one("insert into orders(order_number,subtotal_cents,total_cents,is_test) "
                         "values('SYSTEM-TEST-'||gen_random_uuid(),1000,1000,true) returning *")
        fake_test_log = one("insert into email_logs(order_id,recipient,email_type,status,idempotency_key,metadata,event_snapshot,delivery_state) "
                            "select $1,recipient,email_type,'queued',$2,metadata,event_snapshot,'pending' from email_logs where id=$3 returning *",
                            [test_order['id'], 'synthetic-test-' + uuid4().hex, wrong_source['id']])
        sql("update email_logs set metadata=jsonb_set(metadata,'{source}','\"atomic_financial_transition\"') where id=$1", [fake_test_log['id']])
        unchanged(fake_test_log, 'not_eligible')

        # Current financial state and frozen owner remain authoritative, through shared core.
        for mutation in ("financial_review_required=true", "stripe_payment_intent_id='pi_synthetic_changed_" + uuid4().hex + "'",
                         "user_id='" + customer + "'", "payment_status='unpaid'", "status='cancelled'"):
            changed_order, changed_log = seed()
            try:
                sql('update orders set ' + mutation + ' where id=$1', [changed_order['id']])
            except HTTPError as error:
                raise AssertionError('Synthetic system-financial mutation failed: ' + error.read().decode()) from error
            eq(system(changed_log)[0], {'claimed': False, 'state': 'unknown'})
            unchanged(changed_log, 'unknown')
        refund_order, old_payment = seed()
        sql('select public.record_order_refund($1,250)', [refund_order['stripe_payment_intent_id']])
        eq(system(old_payment)[0], {'claimed': False, 'state': 'unknown'})
        refund_log = financial.log(refund_order, 'refund_confirmed', 250)
        eq(system(refund_log)[0], {'claimed': True, 'state': 'claimed'})
    finally:
        settings(False)
    eq(one('select financial_notification_auto_enabled value from shop_settings where id')['value'], False)
    print(json.dumps({'system_financial_claim_checks': probe.checks-start,
                      'automatic_activation': False, 'smtp_calls': 0, 'provider_calls': 0,
                      'production_access': False, 'native_concurrency_proven': False}))


if __name__ == '__main__':
    main()
