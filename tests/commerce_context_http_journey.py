"""HTTP -> real SDK/FAKE transport -> disposable SQL -> signed webhook -> receipt.

This proves execution of application transitions, NOT real merchant eligibility,
provider connectivity, commercial offers, supplier acceptance or shipment.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.commerce_http_probe import ADMIN, HEADERS, eq, request, sql
from tests.context_checkout_fixture import PROFILES


def qa(path, payload=None):
    req = Request('http://127.0.0.1:8765' + path,
        data=json.dumps(payload if payload is not None else {}).encode(),
        headers={**HEADERS, 'Content-Type': 'application/json'})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def signed(event, *, profile=PROFILES[0], valid=True, expected=200):
    raw = json.dumps(event).encode()
    stamp = str(int(time.time()))
    digest = hmac.new(profile['signing_secret'].encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    if not valid:
        digest = '0' * 64
    req = Request('http://127.0.0.1:8765/api/stripe/webhook/' + profile['reference'], method='POST', data=raw,
        headers={'Content-Type': 'application/json', 'Stripe-Signature': 't=' + stamp + ',v1=' + digest})
    try:
        with urlopen(req, timeout=30) as response:
            status, value = response.status, json.load(response)
    except HTTPError as error:
        status, value = error.code, json.load(error)
    eq(status, expected)
    return value


def run(fresh, enable, session_for):
    profile = PROFILES[0]
    eq(qa('/qa-context-config', {'profile_ref': profile['reference']})['transport'], 'FAKE')
    enable()
    quote, guest, variant, _offer = fresh()
    owner = {'X-Session-Id': guest}
    before = qa('/qa-context-counters')['create_calls']
    response = request('/cart/quote/' + quote + '/checkout', 'POST', {'request_key': str(uuid4())}, owner)
    eq(response['is_test'], False)
    eq(response['status'], 'open')
    eq(response['url'].startswith('https://checkout.stripe.com/c/pay/cs_live_'), True)
    eq(qa('/qa-context-counters')['create_calls'] - before, 1)
    again = request('/cart/quote/' + quote + '/checkout', 'POST', {'request_key': str(uuid4())}, owner)
    eq(again, response)
    eq(qa('/qa-context-counters')['create_calls'] - before, 1)
    receipt = request('/checkout-session/' + response['session_id'], headers=owner)
    eq(receipt['paid'], False)
    eq(receipt['is_test'], False)
    request('/checkout-session/' + response['session_id'], headers={'X-Session-Id': 'synthetic_foreign_owner_1234'}, status=404)
    order = sql('select * from orders where id=$1', [response['order_id']])[0]
    attempt = sql('select * from commerce_checkout_attempts where order_id=$1', [order['id']])[0]
    context = {'order': order, 'attempt': attempt}
    session = session_for(context, sid=response['session_id'])
    event = {'id': 'evt_' + uuid4().hex, 'object': 'event', 'livemode': True,
             'type': 'checkout.session.completed', 'data': {'object': session}}
    signed(event, valid=False, expected=400)
    signed(event, profile=PROFILES[1], expected=500)  # valid OTHER receiver, wrong immutable account/profile
    delegated = deepcopy(event)
    delegated['account'] = profile['account_id']
    signed(delegated, expected=400)
    eq(sql('select payment_status from orders where id=$1', [order['id']])[0]['payment_status'], 'unpaid')
    # Direct snapshot contexts observed through the authenticated Stripe API
    # must match our configured account, not be confused with Connect events.
    foreign_context = {**event, 'context': PROFILES[1]['account_id']}
    signed(foreign_context, expected=400)
    event['context'] = profile['account_id']
    signed(event, valid=False, expected=400)
    # A local sales stop must not lose financial truth for an existing checkout.
    sql('update shop_settings set commerce_live_enabled=false where id')
    eq(signed(event)['duplicate'], False)
    eq(signed(event)['duplicate'], True)
    eq(sql('select stock from product_variants where id=$1', [variant])[0]['stock'], 2)
    tasks = sql('select * from commerce_fulfillment_tasks where order_id=$1', [order['id']])
    eq(len(tasks), 1)
    eq(tasks[0]['supplier_id'], sql('select supplier_id from supplier_offers where id=$1', [tasks[0]['offer_id']])[0]['supplier_id'])
    eq(tasks[0]['external_send_allowed'], False)
    eq(tasks[0]['state'], 'requires_review')
    eq(sql('select count(*) n from supplier_orders where order_id=$1', [order['id']])[0]['n'], 0)
    paid = request('/checkout-session/' + response['session_id'], headers=owner)
    eq(paid['paid'], True)
    eq(paid['order_reference'], order['order_number'])
    eq(paid['total'], order['total_cents'] / 100)
    # No paid receipt triggers a new provider charge.
    eq(qa('/qa-context-counters')['create_calls'] - before, 1)
    # New cart cannot start a payment with the stop flag down.
    next_quote, next_guest, _, _ = fresh()
    other_owner = {'X-Session-Id': next_guest}
    available = request('/cart/quote/' + next_quote, headers=other_owner)
    eq(available['checkout_available'], False)
    request('/cart/quote/' + next_quote + '/checkout', 'POST', {'request_key': str(uuid4())}, other_owner, status=409)
    eq(qa('/qa-context-counters')['create_calls'] - before, 1)
    print(json.dumps({'http_context_journey': 'PASS', 'provider_transport': 'FAKE_HTTPX_WITH_REAL_SDK',
        'fake_checkout_posts': 1, 'actual_stripe_payments': 0, 'actual_supplier_orders': 0,
        'paid_receipt': True, 'duplicate_payment_effects': 0, 'live_gate_final': False}))
