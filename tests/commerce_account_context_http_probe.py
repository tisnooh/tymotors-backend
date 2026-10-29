"""Disposable HTTP/SQL account-context preparation, never a provider request.

Runs the historical synthetic sandbox pipeline first, proving NULL inheritance.
The new account-bound drafts cannot be claimed by the existing gateway path.
Account strings are synthetic assertions, NOT authentication or commercial proof.
"""
from datetime import datetime, timezone
import json
from urllib.error import HTTPError
from uuid import uuid4

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_checkout_params import build_checkout_params
from tests import commerce_pipeline_http_probe as pipeline
from tests import commerce_http_probe as probe
from tests.commerce_http_probe import ADMIN, eq, request, sql


ACCOUNT = 'acct_SyntheticBoundAccountA'
OTHER_ACCOUNT = 'acct_SyntheticBoundAccountB'
ORIGIN = 'http://127.0.0.1:8765'
RPC = 'public.commerce_prepare_account_bound_test_checkout'


def protected():
    return {table: sorted(sql('select row_to_json(t) snapshot from public.' + table + ' t'),
                          key=lambda row: json.dumps(row, sort_keys=True))
            for table in ('orders', 'order_items', 'commerce_quotes', 'commerce_order_lines',
                          'commerce_checkout_attempts', 'commerce_variant_reservations',
                          'commerce_test_sessions', 'commerce_test_payment_events',
                          'commerce_test_refund_events', 'commerce_test_tasks',
                          'supplier_orders', 'supplier_order_items', 'email_logs', 'admin_audit')}


def reject(statement, params=(), *, mutations=(), error_contains=None):
    before = protected()
    refused = False
    sql('begin')
    try:
        for operation, values in mutations:
            sql(operation, values)  # A failed setup must NOT masquerade as refusal.
        try:
            sql(statement, list(params))
        except HTTPError as error:
            eq(error.code, 400)
            if error_contains is not None:
                diagnostic = error.read().decode()
                if error_contains not in diagnostic:
                    # Only the owned synthetic SQL fixture is used by this
                    # probe; retain its error rather than an opaque False/True.
                    raise AssertionError('Synthetic SQL refusal mismatch: ' + diagnostic)
                eq(True, True)
            refused = True
    finally:
        sql('rollback')
    eq(refused, True)
    eq(protected(), before)


def prepare(quote, guest, account=ACCOUNT, actor=ADMIN, origin=ORIGIN):
    return sql('select ' + RPC + '($1,$2,$3,$4,null,$5) context',
               [actor, quote, account, origin, guest])[0]['context']


def main():
    pipeline.main()  # Original params/key/session/settlement still work with NULL.
    start = probe.checks
    functions = (
        RPC + '(uuid,uuid,text,text,uuid,text)',
        'private.commerce_order_from_quote_core(uuid,uuid,uuid,text,boolean,uuid,text,uuid,text,text)',
        'private.guard_commerce_account_context()',
        'private.commerce_order_from_quote_core(uuid,uuid,uuid,text,boolean,uuid,text,uuid,text)',
        'public.commerce_order_from_quote(uuid,uuid,uuid,text,boolean)',
    )
    for function in functions:
        for role in ('anon', 'authenticated'):
            eq(sql('select has_function_privilege($1,$2,\'EXECUTE\') allowed',
                   [role, function])[0]['allowed'], False)
        eq(sql('select has_function_privilege(\'service_role\',$1,\'EXECUTE\') allowed',
               [function])[0]['allowed'], True)
    eq(sql('select count(*) n from orders where stripe_account_id is not null')[0]['n'], 0)
    eq(sql('select count(*) n from commerce_checkout_attempts where stripe_account_id is not null')[0]['n'], 0)
    legacy = sql('select row_to_json(o) snapshot from orders o order by id')
    legacy_attempts = sql('select row_to_json(a) snapshot from commerce_checkout_attempts a order by id')
    old_order = next(row['snapshot'] for row in legacy if row['snapshot'].get('commerce_quote_id'))
    customer = sql("select id from profiles where role='customer' order by id limit 1")[0]['id']
    sample = sql("select i.product_id,i.variant_id,i.selected_vehicle from order_items i "
                 "join product_variants v on v.id=i.variant_id where v.sku like 'PIPELINE-%-0' "
                 'order by i.id limit 1')[0]

    def fresh_quote():
        guest = 'account_context_' + uuid4().hex
        headers = {'X-Session-Id': guest}
        request('/cart', 'POST', {**sample, 'quantity': 1}, headers)
        quote = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
                        'destination': {'name': 'Synthetic account context', 'line1': '1 Synthetic street',
                                        'city': 'Paris', 'country': 'FR', 'postal_code': '75001'}}, headers)
        return quote['quote_id'], guest

    quote, guest = fresh_quote()
    statement = 'select ' + RPC + '($1,$2,$3,$4,null,$5)'
    for bad_account in (None, '', 'acct_', 'acct_bad-account', 'PRIVATE_SENTINEL_ONLY'):
        reject(statement, [ADMIN, quote, bad_account, ORIGIN, guest])
    reject(statement, [customer, quote, ACCOUNT, ORIGIN, guest])
    reject(statement, [None, quote, ACCOUNT, ORIGIN, guest])
    reject(statement, [ADMIN, quote, ACCOUNT, ORIGIN, 'different_guest_identity'])
    reject(statement, [ADMIN, quote, ACCOUNT, 'http://outside.example.test', guest])
    reject(statement, [ADMIN, old_order['commerce_quote_id'], ACCOUNT, ORIGIN, old_order['guest_session_id']])

    context = prepare(quote, guest)
    order, attempt = context['order'], context['attempt']
    oid, aid = order['id'], attempt['id']
    eq(order['stripe_account_id'], ACCOUNT)
    eq(attempt['stripe_account_id'], ACCOUNT)
    eq(order['is_test'], True)
    eq(attempt['is_test'], True)
    eq(attempt['state'], 'drafting')
    eq(attempt['first_requested_at'], None)
    eq(context['account_authenticated'], False)
    eq(context['provider_creation_authorized'], False)
    eq(context['publication_authorized'], False)
    eq(prepare(quote, guest), context)
    reject(statement, [ADMIN, quote, OTHER_ACCOUNT, ORIGIN, guest])
    reject(statement, [ADMIN, quote, ACCOUNT, ORIGIN, 'different_guest_identity'],
           error_contains='Cart not found or not owned')
    reject(statement, [ADMIN, quote, ACCOUNT, 'http://localhost:8765', guest])
    reject('select public.commerce_order_from_quote($1,$2,null,$3,true)', [ADMIN, quote, guest])

    # Explicit mode/account context is required for NEW drafts. This is pure
    # structural checking, never proof the synthetic account belongs to anybody.
    try:
        build_checkout_params(order, context['items'], attempt,
                              trusted_origin=ORIGIN, now=datetime.now(timezone.utc))
    except ValueError:
        eq(True, True)
    else:
        raise AssertionError('Bound draft unexpectedly accepted legacy builder context')
    params = build_checkout_params(order, context['items'], attempt, trusted_origin=ORIGIN,
                                   now=datetime.now(timezone.utc),
                                   server_context=CheckoutServerContext('sandbox', ACCOUNT))
    stored = sql('select public.commerce_store_checkout_params($1,$2,$3::jsonb) value',
                 [ADMIN, aid, json.dumps(params)])[0]['value']
    eq(stored['params'], params)
    eq(stored['stripe_account_id'], ACCOUNT)
    eq(stored['state'], 'ready')
    eq(prepare(quote, guest)['attempt'], stored)
    # Old claim/provider entry cannot skip future account-aware gateway review.
    reject('select public.commerce_claim_checkout_attempt($1,$2)', [ADMIN, aid])
    reject('update commerce_checkout_attempts set first_requested_at=now(),state=\'creating\' where id=$1', [aid])
    for value in (None, OTHER_ACCOUNT):
        reject('update orders set stripe_account_id=$2 where id=$1', [oid, value])
        reject('update commerce_checkout_attempts set stripe_account_id=$2 where id=$1', [aid, value])
    reject('update orders set is_test=false where id=$1', [oid])
    reject('update commerce_checkout_attempts set is_test=false where id=$1', [aid])
    # Existing paid/claimed sandbox history cannot be retroactively attributed.
    reject('update orders set stripe_account_id=$2 where id=$1', [old_order['id'], ACCOUNT])
    old_attempt = legacy_attempts[0]['snapshot']
    reject('update commerce_checkout_attempts set stripe_account_id=$2 where id=$1', [old_attempt['id'], ACCOUNT])
    # Test-only database CHECK remains effective even in the new overloaded core.
    another_quote, another_guest = fresh_quote()
    reject('select private.commerce_order_from_quote_core($1,$2,null,$3,false,null,null,null,\'admin\',$4)',
           [ADMIN, another_quote, another_guest, ACCOUNT])
    reject(statement, [ADMIN, another_quote, ACCOUNT, ORIGIN, another_guest],
           mutations=[('update supplier_offers set availability=\'unavailable\' where variant_id=$1', [sample['variant_id']])])
    reject(statement, [ADMIN, another_quote, ACCOUNT, ORIGIN, another_guest],
           mutations=[('set local role authenticated', [])])
    # Independent INSERT checks: a transaction creates only the new bound order
    # through the same core, then attempts a partial/mismatching attempt context.
    # Failure must roll back the order, quote consumption and every audit row.
    attempt_insert = """with bound as (
      select private.commerce_order_from_quote_core($1,$2,null,$3,true,null,null,null,'admin',$4) value
    ) insert into commerce_checkout_attempts(order_id,commerce_quote_id,total_cents,expires_at,
        quote_expires_at,frontend_origin,integration_identifier,idempotency_key,stripe_account_id,is_test)
      select (bound.value->>'order_id')::uuid,q.id,q.total_cents,
        floor(extract(epoch from q.expires_at))::bigint,q.expires_at,$5,
        'tymotors_test_'||translate(substr(replace(gen_random_uuid()::text,'-',''),1,8),'0123456789','ghijklmnop'),
        'account-insert-probe-'||gen_random_uuid()::text,$6,$7
      from bound,commerce_quotes q where q.id=$2"""
    reject(attempt_insert, [ADMIN, another_quote, another_guest, ACCOUNT, ORIGIN, OTHER_ACCOUNT, True],
           error_contains='Checkout account does not match immutable order')
    reject(attempt_insert, [ADMIN, another_quote, another_guest, ACCOUNT, ORIGIN, ACCOUNT, False],
           error_contains='Checkout account requires matching order mode')
    reject(attempt_insert, [ADMIN, another_quote, another_guest, None, ORIGIN, ACCOUNT, True],
           error_contains='Checkout account does not match immutable order')
    # Cancellation is still allowed before ANY provider claim, releases exactly
    # the held reservations, and must never permit re-preparing the same draft.
    cancelled = sql('select public.commerce_cancel_checkout_draft($1,$2) value', [ADMIN, aid])[0]['value']
    eq(cancelled['state'], 'cancelled')
    eq(cancelled['stripe_account_id'], ACCOUNT)
    eq(sql('select state from commerce_variant_reservations where attempt_id=$1', [aid]), [{'state': 'released'}])
    eq(sql('select public.commerce_cancel_checkout_draft($1,$2) value', [ADMIN, aid])[0]['value'], cancelled)
    reject(statement, [ADMIN, quote, ACCOUNT, ORIGIN, guest], error_contains='Unclaimed sandbox account preparation required')
    drafting = prepare(another_quote, another_guest)
    drafting_aid = drafting['attempt']['id']
    eq(drafting['attempt']['state'], 'drafting')
    eq(sql('select public.commerce_cancel_checkout_draft($1,$2) value', [ADMIN, drafting_aid])[0]['value']['state'], 'cancelled')
    eq(sql('select state from commerce_variant_reservations where attempt_id=$1', [drafting_aid]), [{'state': 'released'}])
    reject(statement, [ADMIN, another_quote, ACCOUNT, ORIGIN, another_guest],
           error_contains='Unclaimed sandbox account preparation required')
    # Immutable legacy row/parameter/hash/key/session values are byte-for-byte
    # equal in their JSON representation, not rewritten using the current account.
    eq(sql('select row_to_json(o) snapshot from orders o where id=any($1::uuid[]) order by id',
           [[row['snapshot']['id'] for row in legacy]]), legacy)
    eq(sql('select row_to_json(a) snapshot from commerce_checkout_attempts a where id=any($1::uuid[]) order by id',
           [[row['snapshot']['id'] for row in legacy_attempts]]), legacy_attempts)
    eq(sql('select count(*) n from commerce_test_sessions where attempt_id=$1', [aid])[0]['n'], 0)
    eq(sql('select count(*) n from commerce_test_tasks where order_id=$1', [oid])[0]['n'], 0)
    eq(sql('select count(*) n from supplier_orders where order_id=$1', [oid])[0]['n'], 0)
    print(json.dumps({'account_context_checks': probe.checks-start,
                      'result': 'sandbox_preparation_only', 'provider_calls': 0,
                      'account_authenticated': False, 'live_checkout_authorized': False,
                      'historical_context_preserved': True}))


if __name__ == '__main__':
    main()
