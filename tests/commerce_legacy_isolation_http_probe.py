"""SQL guards on a disposable loopback PostgreSQL fixture, no provider calls.

The deliberately minimal quote rows below test refusal at the legacy boundary;
they are not validated commercial offers and do not enable a live checkout.
The probe runs the existing 655 synthetic HTTP/SQL pipeline checks first.
"""
import json
from urllib.error import HTTPError
from uuid import uuid4

from tests import commerce_http_probe as probe
from tests import commerce_pipeline_http_probe as pipeline
from tests.commerce_http_probe import sql, eq


def protected():
    result = {}
    for table in ('orders', 'order_items', 'products', 'product_variants',
                  'commerce_checkout_attempts', 'commerce_variant_reservations',
                  'supplier_orders', 'supplier_order_items', 'order_tracking_events',
                  'cart_items', 'admin_audit', 'email_logs'):
        result[table] = sorted(sql('select row_to_json(t) snapshot from public.'+table+' t'),
                               key=lambda r: json.dumps(r, sort_keys=True))
    return result


def reject(statement, params, expected):
    try:
        sql(statement, params)
    except HTTPError as error:
        assert error.code == 400, error.code
        assert expected in error.read().decode(), expected
        probe.checks += 1
    else:
        raise AssertionError('Expected SQL refusal')


def seed_quoted(is_test, paid):
    guest = 'isolation_synthetic_'+uuid4().hex
    cart = sql('insert into carts(guest_session_id) values($1) returning *', [guest])[0]
    context = {'cart': cart, 'country': 'FR', 'mode': 'tracked', 'postal_code': '75001'}
    quote = sql("""insert into commerce_quotes(cart_id,owner_guest_session,country,mode,
        destination,source_context,payload,subtotal_cents,shipping_cents,tax_cents,total_cents,
        expires_at,request_key) values($1,$2,'FR','tracked',$3,$4,'{"currency":"EUR"}',1000,0,0,1000,
        clock_timestamp()+interval '40 minutes',$5) returning id""",
        [cart['id'], guest, {'country': 'FR', 'postal_code': '75001'}, context, str(uuid4())])[0]['id']
    order = sql("""insert into orders(order_number,subtotal_cents,total_cents,currency,
        commerce_quote_id,is_test,payment_status) values($1,1000,1000,'EUR',$2,$3,$4) returning id""",
        ['ISOLATION-'+uuid4().hex, quote, is_test, 'paid' if paid else 'unpaid'])[0]['id']
    product = sql("select id from products where sku='TEST-001'")[0]['id']
    sql("""insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents)
        values($1,$2,'Synthetic legacy isolation','synthetic','ISOLATION-ONLY',1,1000)""", [order, product])
    return order


def main():
    pipeline.main()
    start = probe.checks
    complete = "select complete_paid_order($1,'pi_synthetic','client@example.test','Synthetic','{}','{}') result"
    for is_test in (True, False):
        for paid in (False, True):
            order = seed_quoted(is_test, paid)
            before = protected()
            reject(complete, [order], 'dedicated commerce payment workflow')
            eq(protected(), before)
            reject('select private.ensure_supplier_order($1)', [order], 'dedicated snapshot fulfillment')
            eq(protected(), before)
            if not is_test and not paid:
                reject("update orders set payment_status='paid' where id=$1", [order],
                       'dedicated snapshot fulfillment')
                eq(protected(), before)
    # Historical missing-order behavior remains harmless/idempotent.
    eq(sql(complete, [str(uuid4())])[0]['result'], False)
    eq(sql('select private.ensure_supplier_order($1) result', [str(uuid4())])[0]['result'], None)
    # Existing legacy unquoted production/test behavior is covered by fixture
    # startup AFTER loading the new migration; inspect the preserved privileges.
    for fn, definer in (('public.complete_paid_order(uuid,text,text,text,jsonb,jsonb)', False),
                        ('private.ensure_supplier_order(uuid)', True)):
        row = sql("""select p.prosecdef, p.proconfig,
            has_function_privilege('service_role',p.oid,'EXECUTE') service,
            has_function_privilege('anon',p.oid,'EXECUTE') anon,
            has_function_privilege('authenticated',p.oid,'EXECUTE') authenticated
            from pg_proc p where p.oid=$1::regprocedure""", [fn])[0]
        eq(row['prosecdef'], definer)
        eq(row['service'], True)
        eq(row['anon'], False)
        eq(row['authenticated'], False)
        eq(any(x == 'search_path=""' for x in row['proconfig']), True)
    print('Quoted/legacy isolation SQL checks:', probe.checks-start,
          '; no Stripe call, live checkout, supplier transmission or hosted database.')


if __name__ == '__main__':
    main()
