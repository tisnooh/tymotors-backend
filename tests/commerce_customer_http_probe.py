"""PUBLIC guest quote -> checkout -> signed-event simulation over disposable SQL.

The provider transport and Auth identities are FAKE; HMAC verification, HTTP,
owner RPCs and PostgreSQL rules are real local code. No real Stripe, supplier,
HyperSKU transmission, shipment or commercial catalogue validation occurs.
"""
from copy import deepcopy
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.commerce_http_probe import request, sql, save, eq, HEADERS, ADMIN
from tests.commerce_pipeline_http_probe import webhook
import tests.commerce_http_probe as probe


def counters():
    with urlopen(Request('http://127.0.0.1:8765/qa-customer-payment-counters', headers=HEADERS), timeout=15) as response:
        row = json.load(response)
    eq(row['transport'], 'FAKE')
    return row


def no_private_projection(value):
    serialized = json.dumps(value)
    for forbidden in ('supplier_id','supplier_sku','offer_id','agent_id','responsible_agent_id',
        'unit_cost_cents','cost_price_cents','source_context','idempotency_key','params_hash',
        'profile_id','commerce_quote_id','SYNTHETIC PRIVATE SUPPLIER'):
        eq(forbidden in serialized, False)


def main():
    eq(probe.API, 'http://127.0.0.1:8765/api')
    eq(probe.SQL, 'http://127.0.0.1:8766/query')
    eq(counters()['create_calls'], 0)
    marker = uuid4().hex[:10]
    label = 'CUSTOMER-HTTP-SYNTHETIC-' + marker
    products = sql("select id from products where sku='TEST-001' and status='active'")
    eq(len(products), 1)
    product = products[0]['id']
    rule = sql("select * from product_compatibilities where product_id=$1 and verification_state='verified' order by id", [product])[0]
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    # Only in-memory TEST-001 is adjusted; no actual catalogue image/file or
    # genuine photo licence is changed or asserted by the synthetic grant.
    sql("update product_images set url='https://cdn.example.com/isolated-fixture.webp' where product_id=$1", [product])
    sql("""insert into commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,
        derivatives_use,product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
        values($1,'https://cdn.example.com/isolated-fixture.webp','verified','SYNTHETIC ONLY',true,true,true,
          'not_present',array['FR'],now()+interval '1 year',$2,now())
        on conflict(product_id,image_url) do nothing""", [product, ADMIN])
    agent = save('agent', {'profile_id': ADMIN, 'name': 'SYNTHETIC customer agent', 'role': 'orders', 'is_active': True})
    variant = save('variant', {'product_id': product, 'sku': label, 'name': 'SYNTHETIC exact black',
        'price_cents': 3000, 'stock': 10, 'status': 'active', 'is_verified': True,
        'requires_vehicle': True, 'evidence_ref': 'SYNTHETIC ONLY', 'compatibility_ids': [rule['id']]})
    offer = save('offer', {'variant_id': variant['id'], 'supplier_id': supplier,
        'supplier_sku': 'SYNTHETIC PRIVATE SUPPLIER-' + marker, 'supplier_variant': 'Exact black',
        'url': 'https://supplier.example.test/' + label, 'verification_state': 'verified',
        'evidence_ref': 'SYNTHETIC ONLY', 'is_primary': True, 'availability': 'available',
        'available_quantity': 10, 'valid_until': '2099-01-01T00:00:00Z', 'unit_cost_cents': 1000,
        'recoverable_tax_cents': 0, 'currency': 'EUR', 'preparation_days_min': 1,
        'preparation_days_max': 2, 'responsible_agent_id': agent['id']})
    rate = save('shipping_rate', {'offer_id': offer['id'], 'country': 'FR', 'mode': 'tracked',
        'max_quantity': 10, 'shipping_cost_cents': 200, 'shipping_recoverable_tax_cents': 0,
        'customer_shipping_cents': 500, 'goods_tax_bps': 2000, 'shipping_tax_bps': 2000,
        'agent_fee_cents': 0, 'import_duty_cents': 0, 'nonrecoverable_tax_cents': 0,
        'other_cost_cents': 0, 'verification_state': 'verified', 'evidence_ref': 'SYNTHETIC ONLY',
        'multi_variant_policy': 'independent_parcels', 'valid_until': '2099-01-01T00:00:00Z',
        'delivery_days_min': 3, 'delivery_days_max': 5})
    mapping = request('/admin/commerce/hypersku/mappings', 'POST', {'data': {
        'offer_id': offer['id'], 'shipping_rate_id': rate['id'], 'is_test': True, 'state': 'verified',
        'hypersku_product_ref': 'SYNTHETIC-PRODUCT-' + label,
        'hypersku_variant_ref': 'SYNTHETIC-VARIANT-' + label,
        'equivalence_evidence_ref': 'SYNTHETIC ONLY', 'provider_quote_ref': 'SYNTHETIC ONLY',
        'valid_until': '2098-01-01T00:00:00Z'}}, HEADERS)
    public_variants = request('/products/' + product + '/variants')
    eq(public_variants['checkout_available'], False)
    eq(public_variants['requires_quote'], True)
    selected = [row for row in public_variants['variants'] if row['id'] == variant['id']]
    eq(len(selected), 1)
    eq(selected[0]['sku'], label)
    eq(selected[0]['price_cents'], 3000)
    no_private_projection(public_variants)
    vehicle = {'brand_slug': 'bmw', 'model': rule['model_name'], 'chassis': rule['chassis'],
        'year': rule['year_from'], 'facelift': 'pre-lci', 'body_type': 'sedan'}
    guest = {'X-Session-Id': 'customer_http_guest_' + marker}
    wrong_guest = {'X-Session-Id': 'customer_http_other_' + marker}
    request('/cart', 'POST', {'product_id': product, 'variant_id': variant['id'],
        'quantity': 1, 'selected_vehicle': vehicle}, guest)
    cart = request('/cart', headers=guest)
    eq(cart['items'][0]['variant_id'], variant['id'])
    cart_id = sql('select cart_id from cart_items where id=$1', [cart['items'][0]['cart_item_id']])[0]['cart_id']
    destination = {'name': 'Synthetic recipient', 'line1': '1 Synthetic street',
        'city': 'Paris', 'country': 'FR', 'postal_code': '75001'}
    options=request('/cart/delivery-options','POST',{'destination':destination},guest)
    eq(options['country'],'FR'); eq(options['requires_quote'],True)
    eq(len(options['options']),1)
    eq(options['options'][0]['mode'],'tracked')
    eq(options['options'][0]['shipping_cents'],500)
    eq(options['options'][0]['total_cents'],3500)
    eq(options['options'][0]['tax_cents'],583)  # Included in TTC, never added again.
    no_private_projection(options)
    eq(sql('select count(*)::int n from commerce_quotes where cart_id=$1',[cart_id])[0]['n'],0)
    eq(sql('select count(*)::int n from orders where cart_id=$1',[cart_id])[0]['n'],0)
    request('/cart/delivery-options','POST',{'destination':{**destination,'country':'BE'}},guest,status=409)
    request('/cart/delivery-options','POST',{'destination':destination,'shipping_cents':1},guest,status=422)
    request('/cart/delivery-options','POST',{'destination':destination},
        {**guest,'Authorization':'Bearer invalid-synthetic-token'},status=401)
    for authorization in ('Basic invalid','Bearer'):
        request('/cart/delivery-options','POST',{'destination':destination},
            {**guest,'Authorization':authorization},status=401)
    for postal_code in ('ABC','1234','123456'):
        request('/cart/delivery-options','POST',
            {'destination':{**destination,'postal_code':postal_code}},guest,status=422)
    quote_input = {'request_key': str(uuid4()), 'mode': 'tracked', 'destination': destination}
    quote = request('/cart/quote', 'POST', quote_input, guest)
    eq(quote['checkout_available'], True)
    eq(quote['total_cents'], 3500)
    eq(quote['tax_cents'],583)
    eq(quote['mode'],'tracked'); eq(quote['country'],'FR')
    eq(request('/cart/quote', 'POST', quote_input, guest)['quote_id'], quote['quote_id'])
    checkout_path = '/cart/quote/' + quote['quote_id'] + '/checkout'
    checkout_input = {'request_key': str(uuid4())}
    # Negative requests happen before any order/provider creation.
    request(checkout_path, 'POST', checkout_input,
        {**guest, 'Authorization': 'Bearer invalid-synthetic-token'}, status=401)
    request(checkout_path, 'POST', {**checkout_input, 'total_cents': 1}, guest, status=422)
    request(checkout_path, 'POST', {**checkout_input, 'p_user_id': ADMIN}, guest, status=422)
    request('/cart', headers=wrong_guest)
    request(checkout_path, 'POST', checkout_input, wrong_guest, status=409)
    eq(counters()['create_calls'], 0)
    # This request has NO admin Authorization header. All six owner RPCs run.
    opened = request(checkout_path, 'POST', checkout_input, guest)
    eq(set(opened), {'order_id','order_number','quote_id','session_id','status','is_test','url'})
    eq(opened['quote_id'],quote['quote_id'])
    eq(opened['status'], 'open')
    eq(opened['is_test'], True)
    order_id = opened['order_id']
    attempt = sql('select * from commerce_checkout_attempts where order_id=$1', [order_id])[0]
    binding = sql('select * from commerce_test_sessions where attempt_id=$1', [attempt['id']])[0]
    # The reserved attempt column is intentionally not the session authority.
    # Exercise the actual persisted schema join used by the sandbox runner.
    eq(attempt['session_id'], None)
    joined = sql('''select a.id,s.session_id from commerce_checkout_attempts a
        join commerce_test_sessions s on s.attempt_id=a.id where a.order_id=$1''', [order_id])
    eq(len(joined), 1)
    eq(joined[0]['id'], attempt['id'])
    eq(joined[0]['session_id'], binding['session_id'])
    parsed = urlsplit(opened['url'])
    eq(parsed.scheme, 'https'); eq(parsed.hostname, 'checkout.stripe.com')
    eq(parsed.path, '/c/pay/' + binding['session_id'])
    eq(binding['session_id'].startswith('cs_test_customer_fixture_'), True)
    eq(opened['session_id'],binding['session_id'])
    eq(attempt['state'], 'creating')
    eq(request(checkout_path, 'POST', checkout_input, guest), opened)
    eq(request(checkout_path, 'POST', {'request_key': str(uuid4())}, guest), opened)
    eq(counters()['create_calls'], 1)
    eq(sql('select count(*)::integer n from orders where commerce_quote_id=$1', [quote['quote_id']])[0]['n'], 1)
    eq(sql('select count(*)::integer n from commerce_checkout_attempts where order_id=$1', [order_id])[0]['n'], 1)
    eq(sql('select idempotency_key from commerce_checkout_attempts where id=$1', [attempt['id']])[0]['idempotency_key'], attempt['idempotency_key'])
    no_private_projection(opened)
    # New quote/request key, SAME basket, plenty of stock: still no second create.
    quote2 = request('/cart/quote', 'POST', {**quote_input, 'request_key': str(uuid4())}, guest)
    eq(quote2['quote_id'] != quote['quote_id'], True)
    request('/cart/quote/' + quote2['quote_id'] + '/checkout', 'POST',
        {'request_key': str(uuid4())}, guest, status=409)
    eq(counters()['create_calls'], 1)
    eq(sql('select count(*)::integer n from orders where cart_id=$1', [cart_id])[0]['n'], 1)
    # Return-to-store can precede the signed webhook: render pending, not 404,
    # and never settle from this GET or expose another owner's receipt.
    receipt_path = '/checkout-session/' + binding['session_id']
    receipt = request(receipt_path, headers=guest)
    eq(receipt['paid'], False); eq(receipt['payment_status'], 'unpaid')
    eq(receipt['order_reference'], opened['order_number'])
    request(receipt_path, headers=wrong_guest, status=404)
    no_private_projection(receipt)
    order = sql('select * from orders where id=$1', [order_id])[0]
    session = {'object':'checkout.session','id':binding['session_id'],'mode':'payment','livemode':False,
        'currency':'eur','client_reference_id':order_id,'expires_at':int(attempt['expires_at']),
        'metadata':{'order_id':order_id,'quote_id':quote['quote_id'],'attempt_id':attempt['id']},
        'amount_subtotal':3000,'amount_total':3500,
        'total_details':{'amount_discount':0,'amount_tax':0,'amount_shipping':500},
        'automatic_tax':{'enabled':False},'status':'complete','payment_status':'paid',
        'payment_intent':'pi_customer_http_'+uuid4().hex,
        'shipping_details':{'address':deepcopy(order['shipping_address'])},
        'customer_details':{'email':'synthetic.customer@example.com'}}
    event = {'object':'event','id':'evt_customer_http_'+uuid4().hex,
        'type':'checkout.session.completed','livemode':False,'data':{'object':session}}
    webhook(event, valid=False, expected=400)
    eq(sql('select payment_status from orders where id=$1', [order_id])[0]['payment_status'], 'unpaid')
    eq(webhook(event)['duplicate'], False)
    eq(webhook(event)['duplicate'], True)
    eq(request(receipt_path, headers=guest)['paid'], True)
    paid = request(checkout_path, 'POST', {'request_key': str(uuid4())}, guest)
    eq(paid['status'], 'paid'); eq(paid['url'], None)
    eq(counters()['create_calls'], 1)
    tasks = sql('select * from commerce_test_tasks where order_id=$1', [order_id])
    eq(len(tasks), 1)
    task = tasks[0]
    eq(task['agent_id'], agent['id']); eq(task['supplier_id'], supplier)
    eq(task['supplier_sku'], offer['supplier_sku'])
    eq(task['snapshot']['offer']['unit_cost_cents'], 1000)
    eq(task['snapshot']['rate']['shipping_cost_cents'], 200)
    internal = request('/admin/commerce/hypersku/tasks/' + task['id'] + '/prepare', 'POST',
        {'mapping_id': mapping['id']}, HEADERS)
    eq(internal['state'], 'awaiting_human_review')
    eq(internal['external_send_allowed'], False); eq(internal['expenses_authorized'], False)
    packet = request('/admin/commerce/hypersku/preparations/' + internal['id'], headers=HEADERS)
    eq(packet['packet']['certified_provider_import'], False)
    eq(packet['packet']['responsible_agent_id'], agent['id'])
    for previous, following in [('prepared','received_by_agent'),('received_by_agent','quality_checked'),
        ('quality_checked','shipped'),('shipped','delivered')]:
        body = {'expected': previous, 'next': following}
        if following == 'shipped':
            body['tracking_number'] = 'SIM-CUSTOMER-' + marker
        changed = request('/admin/commerce/test-tasks/' + task['id'] + '/simulate', 'POST', body, HEADERS)
        eq(changed['state'], following)
        eq(request('/admin/commerce/test-tasks/' + task['id'] + '/simulate', 'POST', body, HEADERS), changed)
    public_tracking = request('/order-tracking', 'POST',
        {'order_number': order['order_number'], 'email': 'synthetic.customer@example.com'})
    eq(public_tracking['simulation']['aggregate_state'], 'delivered')
    eq(public_tracking['simulation']['scope'], 'simulation_only_not_real_shipment')
    eq(public_tracking['simulation']['parcels'][0]['tracking_number'], 'SIM-CUSTOMER-' + marker)
    no_private_projection(public_tracking)
    request('/order-tracking', 'POST', {'order_number': order['order_number'], 'email': 'wrong@example.com'}, status=404)
    audit = sql("select admin_user_id,metadata from admin_audit where action='commerce.checkout.claimed' and resource=$1", [attempt['id']])
    eq(len(audit), 1); eq(audit[0]['admin_user_id'], None)
    eq(audit[0]['metadata']['authority'], 'customer_guest')
    eq(json.dumps(audit).find(guest['X-Session-Id']), -1)
    eq(sql('select fulfillment_status from orders where id=$1', [order_id])[0]['fulfillment_status'], 'requires_review')
    eq(sql('select count(*)::integer n from supplier_orders where order_id=$1', [order_id])[0]['n'], 0)
    eq(sql('select stock from product_variants where id=$1', [variant['id']])[0]['stock'], 10)
    eq(sql('select available_quantity from supplier_offers where id=$1', [offer['id']])[0]['available_quantity'], 10)
    eq(sql('select count(*)::integer n from orders where cart_id=$1', [cart_id])[0]['n'], 1)
    final_counts = counters()
    print(json.dumps({'checks': probe.checks, 'result': 'passed', 'public_owner_checkout': 'guest',
        'stripe_transport': 'FAKE', 'provider_create_calls': final_counts['create_calls'],
        'signature_verification': 'real SDK with synthetic local HMAC secret',
        'real_stripe_payment': False, 'commercial_products_validated': 0,
        'real_supplier_orders': 0, 'hypersku_external_send': False, 'simulated_parcels': 1}))


if __name__ == '__main__':
    main()
