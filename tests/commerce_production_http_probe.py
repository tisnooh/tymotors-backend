"""Disposable account/mode execution contract, SYNTHETIC data and no provider.

Runs the historical pipeline first. Production-shaped rows here are fabricated
fixtures inside the owned PostgreSQL engine, never commercially verified offers.
No Stripe account, hosted database, SMTP, purchase or supplier call is used.
"""
from datetime import datetime, timezone
import json
from urllib.error import HTTPError
from uuid import uuid4

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_checkout_params import build_checkout_params
from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import ADMIN, eq, request, save, sql


ACCOUNT = 'acct_SyntheticContextA'
OTHER = 'acct_SyntheticContextB'
PROFILE = 'synthetic-context-production'
ORIGIN = 'https://shop.example.com'


def protected():
    return {table: sql('select row_to_json(t) snapshot from public.' + table + ' t order by row_to_json(t)::text')
            for table in ('orders', 'commerce_quotes', 'commerce_order_lines', 'order_items',
                          'commerce_checkout_attempts', 'commerce_variant_reservations',
                          'commerce_payment_sessions', 'commerce_payment_events',
                          'commerce_fulfillment_tasks', 'supplier_orders', 'supplier_order_items',
                          'product_variants', 'email_logs', 'admin_audit')}


def reject(statement, values=(), mutations=()):
    before = protected()
    rejected = False
    sql('begin')
    try:
        for operation, params in mutations:
            sql(operation, params)
        try:
            sql(statement, list(values))
        except HTTPError as error:
            eq(error.code, 400)
            rejected = True
    finally:
        sql('rollback')
    eq(rejected, True)
    eq(protected(), before)


def enable(account=ACCOUNT, profile=PROFILE):
    # This is exclusively the disposable test DB, not a merchant declaration.
    sql("""update shop_settings set commerce_live_enabled=true,
        commerce_launch_approval_ref='SYNTHETIC LOCAL EXECUTION ONLY',
        commerce_launch_approved_at=clock_timestamp()-interval '1 minute',
        commerce_launch_approval_expires_at=clock_timestamp()+interval '1 hour',
        commerce_launch_stripe_account_id=$1,commerce_launch_profile_ref=$2 where id""", [account, profile])


def prepare(quote, guest, *, is_test=False, account=ACCOUNT, profile=PROFILE, origin=ORIGIN):
    try:
        return sql('select commerce_prepare_context_checkout($1,$2,$3,$4,$5,null,$6,null) value',
                   [quote, origin, is_test, account, profile, guest])[0]['value']
    except HTTPError as error:
        raise AssertionError('Synthetic context preparation failed: ' + error.read().decode()) from None


def params_and_claim(context, guest):
    attempt, order = context['attempt'], context['order']
    server = CheckoutServerContext('sandbox' if order['is_test'] else 'production', order['stripe_account_id'])
    params = build_checkout_params(order, context['items'], attempt, trusted_origin=attempt['frontend_origin'],
                                   now=datetime.now(timezone.utc), server_context=server)
    values = [attempt['id'], json.dumps(params), order['stripe_account_id'], order['stripe_profile_ref'], guest]
    stored = sql('select commerce_store_context_checkout_params($1,$2::jsonb,$3,$4,null,$5,null) value', values)[0]['value']
    eq(stored['state'], 'ready')
    claimed = sql('select commerce_claim_context_checkout($1,$2,$3,null,$4,null) value',
                  [attempt['id'], order['stripe_account_id'], order['stripe_profile_ref'], guest])[0]['value']
    eq(claimed['state'], 'creating')
    eq(claimed['params'], params)
    eq(claimed['idempotency_key'], stored['idempotency_key'])
    return claimed


def session_for(context, *, sid=None, intent=None):
    order, attempt = context['order'], context['attempt']
    return {'object': 'checkout.session', 'id': sid or ('cs_test_' if order['is_test'] else 'cs_live_') + uuid4().hex,
            'mode': 'payment', 'livemode': not order['is_test'], 'currency': 'eur',
            'client_reference_id': order['id'], 'expires_at': int(attempt['expires_at']),
            'metadata': {'order_id': order['id'], 'quote_id': order['commerce_quote_id'], 'attempt_id': attempt['id']},
            'amount_subtotal': order['subtotal_cents'], 'amount_total': order['total_cents'],
            'total_details': {'amount_discount': 0, 'amount_tax': 0, 'amount_shipping': order['shipping_amount_cents']},
            'automatic_tax': {'enabled': False}, 'status': 'complete', 'payment_status': 'paid',
            'payment_intent': intent or 'pi_' + uuid4().hex,
            'shipping_details': {'address': order['shipping_address']},
            'customer_details': {'email': 'synthetic@example.test'}}


def settle(context, session, event=None, matches=True):
    order = context['order']
    return sql('select commerce_settle_context_checkout($1,$2,$3::jsonb,$4,$5,$6) value',
               [event or 'evt_' + uuid4().hex, 'checkout.session.completed', json.dumps(session), matches,
                order['stripe_account_id'], order['stripe_profile_ref']])[0]['value']


def main():
    pipeline.main()
    start = probe.checks
    eq(sql('select commerce_context_checkout_enabled(false,$1,$2) enabled', [ACCOUNT, PROFILE])[0]['enabled'], False)
    legacy = protected()
    for table in ('commerce_payment_sessions', 'commerce_payment_events', 'commerce_fulfillment_tasks'):
        eq(sql('select relrowsecurity enabled from pg_class where oid=$1::regclass', ['public.'+table])[0]['enabled'], True)
        for role in ('anon', 'authenticated'):
            for operation in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
                eq(sql('select has_table_privilege($1,$2,$3) allowed', [role, 'public.'+table, operation])[0]['allowed'], False)
    for name in ('commerce_prepare_context_checkout', 'commerce_store_context_checkout_params',
                 'commerce_claim_context_checkout', 'commerce_context_checkout_unknown',
                 'commerce_bind_context_session', 'commerce_record_context_event',
                 'commerce_settle_context_checkout', 'commerce_context_checkout_enabled'):
        for role in ('anon', 'authenticated'):
            eq(sql("select has_function_privilege($1,p.oid,'EXECUTE') allowed from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname=$2", [role, name])[0]['allowed'], False)
    sample = sql("select i.product_id,i.selected_vehicle from order_items i join product_variants v on v.id=i.variant_id where v.sku like 'PIPELINE-%-0' limit 1")[0]
    supplier = sql("select id from suppliers where name='Fixture supplier' limit 1")[0]['id']
    agent = save('agent', {'profile_id': ADMIN, 'name': 'Synthetic context operator', 'role': 'orders', 'is_active': True})
    rule = sql("select id from product_compatibilities where product_id=$1 and verification_state='verified' limit 1", [sample['product_id']])[0]['id']

    def fresh(*, stock=3):
        label = 'CONTEXT-' + uuid4().hex
        variant = save('variant', {'product_id': sample['product_id'], 'sku': label, 'name': 'Synthetic execution',
            'price_cents': 3000, 'stock': stock, 'status': 'active', 'is_verified': True, 'requires_vehicle': True,
            'evidence_ref': 'SYNTHETIC ONLY NOT COMMERCIAL PROOF', 'compatibility_ids': [rule]})
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
            'delivery_days_min': 3, 'delivery_days_max': 5})
        guest = 'synthetic_context_' + uuid4().hex
        headers = {'X-Session-Id': guest}
        request('/cart', 'POST', {**sample, 'variant_id': variant['id'], 'quantity': 1}, headers)
        quote = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
            'destination': {'name': 'Synthetic only', 'line1': '1 Synthetic street', 'city': 'Paris',
                            'country': 'FR', 'postal_code': '75001'}}, headers)
        return quote['quote_id'], guest, variant['id'], offer['id']

    statement = 'select commerce_prepare_context_checkout($1,$2,false,$3,$4,null,$5,null)'
    quote, guest, variant, offer = fresh()
    reject(statement, [quote, ORIGIN, ACCOUNT, PROFILE, guest])
    enable()
    eq(sql('select commerce_launch_registration_status from shop_settings where id')[0]['commerce_launch_registration_status'], 'pending')
    eq(sql('select commerce_context_checkout_enabled(false,$1,$2) enabled', [ACCOUNT, PROFILE])[0]['enabled'], True)
    for account, profile, who in ((OTHER, PROFILE, guest), (ACCOUNT, 'different-profile', guest), (ACCOUNT, PROFILE, 'different_guest_identity')):
        reject(statement, [quote, ORIGIN, account, profile, who])
    reject(statement, [quote, 'http://127.0.0.1:8765', ACCOUNT, PROFILE, guest])
    reject(statement, [quote, ORIGIN, ACCOUNT, PROFILE, guest],
           [('update supplier_offers set availability=\'unavailable\' where id=$1', [offer])])
    context = prepare(quote, guest)
    aid, oid = context['attempt']['id'], context['order']['id']
    eq(context['order']['is_test'], False)
    eq(context['attempt']['is_test'], False)
    eq(context['order']['stripe_account_id'], ACCOUNT)
    eq(context['attempt']['stripe_profile_ref'], PROFILE)
    eq(prepare(quote, guest), context)
    for table, identity in (('orders', oid), ('commerce_checkout_attempts', aid)):
        for column, value in (('stripe_account_id', OTHER), ('stripe_profile_ref', 'other-profile'), ('is_test', True)):
            reject(f'update {table} set {column}=$2 where id=$1', [identity, value])
    params_and_claim(context, guest)
    reject('select commerce_claim_context_checkout($1,$2,$3,null,$4,null)', [aid, ACCOUNT, PROFILE, guest])
    reject('select commerce_claim_checkout_attempt($1,$2)', [ADMIN, aid])
    session = session_for(context, sid='cs_live_same_synthetic_identity', intent='pi_same_synthetic_identity')
    # Closing new-request permission cannot discard a payment already initiated.
    sql('update shop_settings set commerce_live_enabled=false where id')
    event = 'evt_same_synthetic_identity'
    result = settle(context, session, event)
    eq(result['duplicate'], False)
    eq(result['is_test'], False)
    eq(result['fulfillment_held'], False)
    eq(settle(context, session, event)['duplicate'], True)
    eq(settle(context, session)['duplicate'], True)
    eq(sql('select session_id from commerce_checkout_attempts where id=$1', [aid])[0]['session_id'], session['id'])
    eq(sql('select stock from product_variants where id=$1', [variant])[0]['stock'], 2)
    eq(sql('select state from commerce_variant_reservations where attempt_id=$1', [aid]), [{'state': 'consumed'}])
    tasks = sql('select * from commerce_fulfillment_tasks where order_id=$1', [oid])
    eq(len(tasks), 1)
    eq(tasks[0]['agent_id'], agent['id'])
    eq(tasks[0]['supplier_id'], supplier)
    eq(tasks[0]['offer_id'], offer)
    eq(tasks[0]['snapshot']['offer']['unit_cost_cents'], 1000)
    eq(tasks[0]['external_send_allowed'], False)
    eq(sql('select count(*) n from supplier_orders where order_id=$1', [oid])[0]['n'], 0)
    eq(sql('select count(*) n from email_logs where order_id=$1 and email_type=\'payment_confirmed\'', [oid])[0]['n'], 1)
    reject('select commerce_bind_test_session($1,$2)', [aid, 'cs_test_incorrect_mode'])
    reject('select commerce_bind_context_session($1,$2,$3,$4)', [aid, session['id'], OTHER, PROFILE])
    reject('select commerce_bind_context_session($1,$2,$3,$4)', [aid, 'cs_live_changed_identity', ACCOUNT, PROFILE])
    reject('select commerce_settle_context_checkout($1,$2,$3::jsonb,true,$4,$5)',
           ['evt_' + uuid4().hex, 'checkout.session.completed', json.dumps({**session, 'amount_total': 3501}), ACCOUNT, PROFILE])
    # Same opaque provider IDs in another account cannot collide with paid truth.
    quote2, guest2, variant2, offer2 = fresh()
    enable(OTHER)
    other = prepare(quote2, guest2, account=OTHER)
    params_and_claim(other, guest2)
    other_session = session_for(other, sid=session['id'], intent=session['payment_intent'])
    eq(settle(other, other_session, event)['duplicate'], False)
    eq(sql('select count(*) n from orders where stripe_payment_intent_id=$1', [session['payment_intent']])[0]['n'], 2)
    eq(sql('select count(*) n from commerce_payment_events where event_id=$1', [event])[0]['n'], 2)
    # No implicit provider actions or refund application from reconciliation-only receipts.
    failure = 'evt_' + uuid4().hex
    receipt = 'select commerce_record_context_event($1,$2,$3,false,$4,$5) value'
    values = [failure, 'charge.refunded', 'ch_synthetic_refund_receipt', OTHER, PROFILE]
    eq(sql(receipt, values)[0]['value']['duplicate'], False)
    eq(sql(receipt, values)[0]['value']['duplicate'], True)
    reject(receipt, [failure, 'charge.refunded', 'ch_different_receipt', OTHER, PROFILE])
    eq(sql('select refunded_amount_cents from orders where id=$1', [other['order']['id']])[0]['refunded_amount_cents'], 0)
    # Insufficient current stock preserves paid truth but never prepares shipment.
    quote3, guest3, variant3, offer3 = fresh()
    enable()
    held = prepare(quote3, guest3)
    params_and_claim(held, guest3)
    sql('update product_variants set stock=0 where id=$1', [variant3])
    sql('update shop_settings set commerce_live_enabled=false where id')
    eq(settle(held, session_for(held))['fulfillment_held'], True)
    eq(sql('select payment_status from orders where id=$1', [held['order']['id']])[0]['payment_status'], 'paid')
    incident_tasks = sql('select * from commerce_fulfillment_tasks where order_id=$1', [held['order']['id']])
    eq(len(incident_tasks), 1)
    eq(incident_tasks[0]['agent_id'], agent['id'])
    eq(incident_tasks[0]['external_send_allowed'], False)
    eq('inventory_unavailable' in incident_tasks[0]['review_reasons'], True)
    # Explicit sandbox profile uses the same durable context without stock mutation.
    quote4, guest4, variant4, offer4 = fresh()
    sandbox = prepare(quote4, guest4, is_test=True, origin='http://127.0.0.1:8765', profile='synthetic-context-sandbox')
    params_and_claim(sandbox, guest4)
    eq(settle(sandbox, session_for(sandbox))['is_test'], True)
    eq(sql('select stock from product_variants where id=$1', [variant4])[0]['stock'], 3)
    # Legacy PI-only refund helpers are confined to NULL-account history even
    # when an opaque provider identifier appears in several account contexts.
    legacy_order = sql("""insert into orders(order_number,is_test,status,payment_status,subtotal_cents,total_cents,
        stripe_payment_intent_id,stripe_session_id) values($1,true,'paid','paid',3500,3500,$2,$3) returning id""",
        ['SYNTHETIC-LEGACY-' + uuid4().hex, session['payment_intent'], session['id']])[0]['id']
    sql('select record_order_refund($1,1)', [session['payment_intent']])
    eq(sql('select refunded_amount_cents from orders where id=$1', [legacy_order])[0]['refunded_amount_cents'], 1)
    eq(sql('select refunded_amount_cents from orders where id=any($1::uuid[]) order by id', [
        [oid, other['order']['id']]]), [{'refunded_amount_cents': 0}, {'refunded_amount_cents': 0}])
    normalized = {'event_id': 'evt_' + uuid4().hex, 'event_type': 'refund.created', 'event_created': 1900000000,
                  'refund_id': 're_' + uuid4().hex, 'payment_intent_id': session['payment_intent'],
                  'charge_id': 'ch_' + uuid4().hex, 'amount_cents': 1, 'currency': 'eur',
                  'refund_status': 'succeeded', 'charge_refunded_cents': None}
    sql('select commerce_record_test_refund($1::jsonb)', [json.dumps(normalized)])
    eq(sql('select financial_review_required from orders where id=any($1::uuid[]) order by id', [
        [oid, other['order']['id']]]), [{'financial_review_required': False}, {'financial_review_required': False}])
    eq(sql('select private.commerce_project_test_refunds($1) value', [sandbox['order']['id']])[0]['value']['reason'],
       'not_quoted_test_order')
    # A held sandbox checkout cannot consume production reservation capacity,
    # nor lock out a real-mode purchase from the same cart.
    quote5, guest5, variant5, _ = fresh(stock=1)
    isolated = prepare(quote5, guest5, is_test=True, origin='http://127.0.0.1:8765', profile='synthetic-context-sandbox')
    params_and_claim(isolated, guest5)
    another = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
        'destination': isolated['order']['shipping_address']}, {'X-Session-Id': guest5})
    enable()
    real_capacity = prepare(another['quote_id'], guest5)
    params_and_claim(real_capacity, guest5)
    eq(sql('select count(*) n from commerce_variant_reservations where variant_id=$1 and state=\'held\'', [variant5])[0]['n'], 2)
    eq(sql('select stock from product_variants where id=$1', [variant5])[0]['stock'], 1)
    sql('update shop_settings set commerce_live_enabled=false where id')
    eq(sql('select commerce_live_enabled from shop_settings where id')[0]['commerce_live_enabled'], False)
    # Original NULL-profile order/attempt rows and all original paid facts unchanged.
    for table in ('orders', 'commerce_checkout_attempts'):
        ids = [row['snapshot']['id'] for row in legacy[table]]
        eq(sql('select row_to_json(t) snapshot from public.'+table+' t where id=any($1::uuid[]) order by row_to_json(t)::text', [ids]), legacy[table])
    from tests.commerce_context_http_journey import run as http_journey
    http_journey(fresh, enable, session_for)
    print(json.dumps({'context_execution_checks': probe.checks-start, 'provider_calls': 0,
                      'real_payments': 0, 'real_supplier_orders': 0, 'production_access': False,
                      'production_fixture_orders': 3, 'live_gate_final': False}))


if __name__ == '__main__':
    main()
