"""Synthetic full context settlement + account-scoped refund SQL conservation."""
from copy import deepcopy
import json
from uuid import uuid4

from tests import commerce_http_probe as probe
from tests import commerce_production_http_probe as context
from tests.commerce_context_dispatch_probe import make_order
from tests.commerce_http_probe import ADMIN, eq, sql


def receipt(session, amount=100, *, refund=None, status='succeeded', account=None,
            profile=None, kind='refund.updated', currency='eur', event=None, charge_total=None):
    p = {'event_id': event or 'evt_' + uuid4().hex, 'event_type': kind, 'event_created': 1700000000,
         'refund_id': refund or 're_' + uuid4().hex, 'payment_intent_id': session['payment_intent'],
         'charge_id': 'ch_SyntheticContextRefund', 'amount_cents': amount,
         'currency': currency, 'refund_status': status, 'charge_refunded_cents': None}
    if kind == 'charge.refunded':
        p.update(refund_id=None, amount_cents=None, refund_status=None, charge_refunded_cents=charge_total)
    return p, sql('select commerce_record_context_refund($1::jsonb,false,$2,$3) value',
                  [json.dumps(p), account or context.ACCOUNT, profile or context.PROFILE])[0]['value']


def state(order):
    return sql('select refunded_amount_cents,payment_status,status,financial_review_required from orders where id=$1',
               [order['order']['id']])[0]


def main():
    # The owned fixture applies the full reviewed migration chain before serving.
    context.main()
    start = probe.checks
    for role in ('anon','authenticated'):
        eq(sql("select has_function_privilege($1,'public.commerce_record_context_refund(jsonb,boolean,text,text)','EXECUTE') value", [role])[0]['value'], False)
    order, session, _ = make_order()
    total = order['order']['total_cents']
    # A genuinely eligible pending payment receipt must become unusable after
    # a signed refund, not merely look different in the customer page.
    old_receipt = sql("select id,event_snapshot,delivery_state,delivery_token from email_logs "
                      "where order_id=$1 and email_type='payment_confirmed'", [order['order']['id']])[0]
    eq(old_receipt['delivery_state'], 'pending')
    eq(old_receipt['delivery_token'], None)
    eq(sql('select private.financial_order_notification_matches(e,o) value '
           'from email_logs e join orders o on o.id=e.order_id where e.id=$1',
           [old_receipt['id']])[0]['value'], True)
    rid = 're_' + uuid4().hex
    payload, first = receipt(session, 100, refund=rid)
    eq(first['refunded_amount_cents'], 100)
    eq(state(order)['financial_review_required'], True)
    eq(sql('select private.financial_order_notification_matches(e,o) value '
           'from email_logs e join orders o on o.id=e.order_id where e.id=$1',
           [old_receipt['id']])[0]['value'], False)
    eq(sql('select financial_notification_auto_enabled value from shop_settings where id')[0]['value'], False)
    sql('update shop_settings set financial_notification_auto_enabled=true where id')
    try:
        refused = sql('select commerce_claim_financial_notification($1,$2,true) value',
                      [old_receipt['id'],str(uuid4())])[0]['value']
        eq(refused, {'claimed':False,'state':'unknown'})
    finally:
        sql('update shop_settings set financial_notification_auto_enabled=false where id')
    retained = sql('select event_snapshot,delivery_state,delivery_token from email_logs where id=$1',
                   [old_receipt['id']])[0]
    eq(retained['event_snapshot'], old_receipt['event_snapshot'])
    eq(retained['delivery_state'], 'unknown')
    eq(retained['delivery_token'], None)
    eq(state(order)['financial_review_required'], True)
    again = sql('select commerce_record_context_refund($1::jsonb,false,$2,$3) value',
                [json.dumps(payload), context.ACCOUNT, context.PROFILE])[0]['value']
    eq(again['duplicate'], True); eq(state(order)['refunded_amount_cents'], 100)
    # Older pending observation cannot subtract a proven successful refund.
    receipt(session, 100, refund=rid, status='pending')
    eq(state(order)['refunded_amount_cents'], 100)
    receipt(session, kind='charge.refunded', charge_total=100)
    eq(state(order)['refunded_amount_cents'], 100)
    receipt(session, total - 100)
    eq(state(order)['refunded_amount_cents'], total)
    eq(state(order)['payment_status'], 'refunded')
    eq(state(order)['financial_review_required'], True)
    # Another account/profile can never select this order through the same PI.
    other, osession, _ = make_order()
    receipt(osession, 100, account=context.OTHER)
    receipt(osession, 100, profile='foreign-profile')
    eq(state(other)['refunded_amount_cents'], 0)
    # Contradictory amount/currency/status retained for review; never guessed.
    for changed in ('amount','currency','status'):
        c, s, _ = make_order(); rid = 're_' + uuid4().hex
        receipt(s, 100, refund=rid)
        _, conflict = receipt(s, 101 if changed=='amount' else 100, refund=rid,
            currency='usd' if changed=='currency' else 'eur', status='failed' if changed=='status' else 'succeeded')
        eq(conflict['reason'], 'refund_identity_or_total_conflict')
        eq(state(c)['refunded_amount_cents'], 100)
        eq(state(c)['financial_review_required'], True)
    # Signed observation before payment is projected by the settlement trigger.
    c, s, _ = make_order(paid=False)
    _, unknown = receipt(s, 100)
    eq(unknown['reason'], 'unbound_context_refund_receipt')
    context.settle(c, s)
    eq(state(c)['refunded_amount_cents'], 100)
    eq(state(c)['financial_review_required'], True)
    # Admin retry records review proof but cannot clear financial quarantine.
    stamp = sql('select updated_at from orders where id=$1', [c['order']['id']])[0]['updated_at']
    reviewed = sql('select commerce_reconcile_context_refunds($1,$2,$3,$4) value',
                   [ADMIN,c['order']['id'],stamp,'synthetic-admin-review'])[0]['value']
    eq(reviewed['review_released'],False)
    eq(state(c)['financial_review_required'],True)
    sql('update shop_settings set commerce_live_enabled=false where id')
    print(json.dumps({'context_refund_checks':probe.checks-start, 'result':'PASS',
                      'actual_refunds':0,'production_writes':0,'review_released':False}))


if __name__ == '__main__': main()
