"""Five SYNTHETIC variants through real HTTP/SQL logic, fake provider only.

Not five commercially verified catalogue products or a real Stripe sandbox run.
Requires disposable admin_database.mjs --serve and tests.serve_admin_fixture.
"""
from copy import deepcopy
import hashlib
import hmac
import json
import time
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.commerce_http_probe import request, sql, save, eq, HEADERS, ADMIN
import tests.commerce_http_probe as probe


def webhook(event, *, valid=True, expected=200):
    body = json.dumps(event, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(b'whsec_synthetic_fixture_not_a_credential', stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
    if not valid:
        signature = '0'*64
    from urllib.error import HTTPError
    req = Request(probe.API + '/stripe/webhook', method='POST', data=body,
                  headers={'Content-Type': 'application/json', 'Stripe-Signature': f't={stamp},v1={signature}'})
    try:
        with urlopen(req, timeout=30) as response:
            status, result = response.status, json.load(response)
    except HTTPError as error:
        status, result = error.code, json.load(error)
    eq(status, expected)
    return result


def main():
    for table in ('commerce_test_sessions','commerce_test_payment_events','commerce_test_tasks','commerce_test_task_events'):
        eq(sql('select relrowsecurity rls from pg_class where oid=$1::regclass',['public.'+table])[0]['rls'],True)
        for role in ('anon','authenticated'):
            for permission in ('SELECT','INSERT','UPDATE','DELETE','TRUNCATE'):
                eq(sql('select has_table_privilege($1,$2,$3) allowed',[role,'public.'+table,permission])[0]['allowed'],False)
    for fn in ('commerce_bind_test_session(uuid,text)','commerce_settle_test_checkout(text,text,jsonb,boolean)',
               'commerce_advance_test_task(uuid,uuid,text,text,text)'):
        for role in ('anon','authenticated'):
            eq(sql('select has_function_privilege($1,$2,$3) allowed',[role,'public.'+fn,'EXECUTE'])[0]['allowed'],False)
    marker = uuid4().hex[:8]
    product = sql("select id from products where sku='TEST-001' and status='active'")[0]['id']
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    rule = sql("select * from product_compatibilities where product_id=$1 and verification_state='verified' order by id", [product])[0]
    sql("update product_images set url='https://cdn.example.com/isolated-fixture.webp' where product_id=$1", [product])
    actor = save('agent', {'profile_id': ADMIN,'name': 'Synthetic pipeline agent','role': 'orders','is_active': True})
    vehicle = {'brand_slug': 'bmw', 'model': rule['model_name'], 'chassis': rule['chassis'],
               'year': rule['year_from'], 'facelift': 'pre-lci', 'body_type': 'sedan'}
    used_intent = None
    for number in range(8):
        label = f'PIPELINE-{marker}-{number}'
        variant = save('variant', {'product_id': product,'sku': label,'name': 'Synthetic pilot '+str(number),
            'price_cents': 3000,'stock': 3,'status': 'active','is_verified': True,'requires_vehicle': True,
            'evidence_ref': 'SYNTHETIC ONLY','compatibility_ids': [rule['id']]})
        offer = save('offer', {'variant_id': variant['id'],'supplier_id': supplier,'supplier_sku': 'SOURCE-'+label,
            'supplier_variant': 'Synthetic exact black','url': 'https://supplier.example.test/'+label,
            'verification_state': 'verified','evidence_ref': 'SYNTHETIC ONLY','is_primary': True,
            'availability': 'available','available_quantity': 3,'valid_until': '2099-01-01T00:00:00Z',
            'unit_cost_cents': 1000,'recoverable_tax_cents': 0,'currency': 'EUR',
            'preparation_days_min': 1,'preparation_days_max': 2,'responsible_agent_id': actor['id']})
        rate = save('shipping_rate', {'offer_id': offer['id'],'country': 'FR','mode': 'tracked','max_quantity': 3,
            'shipping_cost_cents': 200,'shipping_recoverable_tax_cents': 0,'customer_shipping_cents': 500,
            'goods_tax_bps': 0,'shipping_tax_bps': 0,'agent_fee_cents': 0,'import_duty_cents': 0,
            'nonrecoverable_tax_cents': 0,'other_cost_cents': 0,'verification_state': 'verified',
            'evidence_ref': 'SYNTHETIC ONLY','valid_until': '2099-01-01T00:00:00Z',
            'delivery_days_min': 3,'delivery_days_max': 5})
        guest = {'X-Session-Id': 'pipeline_'+label}
        request('/cart','POST',{'product_id':product,'variant_id':variant['id'],'quantity':1,
                              'selected_vehicle': vehicle},guest)
        cart = request('/cart',headers=guest)
        quote = request('/cart/quote','POST',{'request_key':str(uuid4()),'mode':'tracked',
            'destination':{'name':'Synthetic recipient','line1':'1 Synthetic street','city':'Paris',
                           'country':'FR','postal_code':'75001'}},guest)
        prepared = request('/admin/commerce/quotes/'+quote['quote_id']+'/prepare-test-order','POST',headers=HEADERS)
        oid = prepared['order_id']
        attempt = request('/admin/commerce/orders/'+oid+'/checkout-attempt','POST',headers=HEADERS)
        aid = attempt['attempt_id']
        plan = request('/admin/commerce/orders/'+oid+'/fulfillment-plan',headers=HEADERS)
        eq(len(plan['tasks']),1)
        eq(plan['tasks'][0]['supplier_sku'],'SOURCE-'+label)
        eq(plan['tasks'][0]['agent_id'],actor['id'])
        eq(plan['tasks'][0]['shipping_cost_cents'],200)
        req = Request('http://127.0.0.1:8765/qa-payment-attempt/'+aid,method='POST',headers=HEADERS)
        with urlopen(req,timeout=30) as response:
            sid = json.load(response)['session_id']
        eq(sql('select state from commerce_checkout_attempts where id=$1',[aid])[0]['state'],'creating')
        order = sql('select * from orders where id=$1',[oid])[0]
        rawattempt = sql('select * from commerce_checkout_attempts where id=$1',[aid])[0]
        session = {'object':'checkout.session','id':sid,'mode':'payment','livemode':False,'currency':'eur',
            'client_reference_id':oid,'expires_at':int(rawattempt['expires_at']),
            'metadata':{'order_id':oid,'quote_id':quote['quote_id'],'attempt_id':aid},
            'amount_subtotal':3000,'amount_total':3500,'total_details':{'amount_discount':0,'amount_tax':0,'amount_shipping':500},
            'automatic_tax':{'enabled':False},'status':'complete','payment_status':'unpaid','payment_intent':None,
            'shipping_details':{'address':order['shipping_address']},
            'customer_details':{'email':'recipient@example.com'}}
        event = {'object':'event','id':'evt_'+uuid4().hex,'type':'checkout.session.completed','livemode':False,'data':{'object':session}}
        webhook(event,valid=False,expected=400)
        eq(webhook(event)['awaiting_payment'],True)
        eq(sql('select count(*) n from commerce_test_tasks where order_id=$1',[oid])[0]['n'],0)
        session.update(payment_status='paid',payment_intent='pi_'+uuid4().hex)
        if number==0:
            used_intent = session['payment_intent']
        if number==7:
            session['payment_intent'] = used_intent
        if number==5:
            session['shipping_details']['address']={**order['shipping_address'],'line1':'Unexpected address'}
        event.update(id='evt_'+uuid4().hex,type='checkout.session.async_payment_succeeded')
        # Catalogue may change AFTER remote claim: paid truth uses frozen data.
        sql('update supplier_offers set unit_cost_cents=1500 where id=$1',[offer['id']])
        if number==0:
            sql('delete from shipping_rates where id=$1',[rate['id']])
        if number==2:
            sql('delete from carts where id=$1',[order['cart_id']])
        if number==7:
            webhook(event,expected=500)
            eq(sql('select payment_status from orders where id=$1',[oid])[0]['payment_status'],'unpaid')
            eq(sql('select count(*) n from commerce_test_tasks where order_id=$1',[oid])[0]['n'],0)
            continue
        result = webhook(event)
        eq(result['duplicate'],False)
        eq(webhook(event)['duplicate'],True)
        same_payment = deepcopy(event)
        same_payment.update(id='evt_'+uuid4().hex,type='checkout.session.completed')
        eq(webhook(same_payment)['duplicate'],True)
        tasks = sql('select * from commerce_test_tasks where order_id=$1',[oid])
        if number==5:
            eq(result['fulfillment_held'],True)
            eq(tasks,[])
            eq(sql('select payment_status from orders where id=$1',[oid])[0]['payment_status'],'paid')
            eq(sql('select stock from product_variants where id=$1',[variant['id']])[0]['stock'],3)
            continue
        eq(len(tasks),1)
        task = tasks[0]
        eq(task['snapshot']['offer']['unit_cost_cents'],1000)
        eq(task['supplier_id'],supplier)
        eq(task['agent_id'],actor['id'])
        eq(task['supplier_sku'],'SOURCE-'+label)
        if number==6:
            sql("update orders set status='cancelled' where id=$1",[oid])
            request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',
                {'expected':'prepared','next':'received_by_agent'},HEADERS,status=409)
            eq(sql('select state from commerce_test_tasks where id=$1',[task['id']])[0]['state'],'prepared')
            # Adversarial local fixtures, NOT external refunds or real orders.
            sql("update orders set status='refunded' where id=$1",[oid])
            request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',
                {'expected':'prepared','next':'received_by_agent'},HEADERS,status=409)
            eq(sql('select state from commerce_test_tasks where id=$1',[task['id']])[0]['state'],'prepared')
            sql("update orders set status='paid',refunded_amount_cents=1 where id=$1",[oid])
            request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',
                {'expected':'prepared','next':'received_by_agent'},HEADERS,status=409)
            eq(sql('select state from commerce_test_tasks where id=$1',[task['id']])[0]['state'],'prepared')
            continue
        request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',
                {'expected':'prepared','next':'shipped','tracking_number':'SIM-'+label},HEADERS,status=409)
        for previous, following in [('prepared','received_by_agent'),('received_by_agent','quality_checked'),
                                    ('quality_checked','shipped'),('shipped','delivered')]:
            body = {'expected':previous,'next':following,'tracking_number':'SIM-'+label if following in ('shipped','delivered') else None}
            state = request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',body,HEADERS)
            eq(state['state'],following)
            eq(request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',body,HEADERS),state)
        eq(sql('select count(*) n from commerce_test_task_events where task_id=$1',[task['id']])[0]['n'],5)
        tracking = request('/order-tracking','POST',{'order_number':order['order_number'],'email':'recipient@example.com'})
        eq(any(x['title']=='Simulation : delivered' for x in tracking['tracking_events']),True)
        eq('supplier_sku' in json.dumps(tracking),False)
        eq(sql('select count(*) n from supplier_orders where order_id=$1',[oid])[0]['n'],0)
        eq(sql('select stock from product_variants where id=$1',[variant['id']])[0]['stock'],3)
        eq(sql('select available_quantity from supplier_offers where id=$1',[offer['id']])[0]['available_quantity'],3)
        eq(sql('select payment_status from orders where id=$1',[oid])[0]['payment_status'],'paid')
        eq(sql('select count(*) n from cart_items where cart_id=$1',[order['cart_id']])[0]['n'],0 if number==2 else 1)
    print(json.dumps({'checks':probe.checks,'synthetic_pilots':5,'redirected_payment_held':1,
                     'cancelled_task_blocked':1,'cross_order_payment_reuse_rejected':1,
                     'result':'passed','stripe_transport':'FAKE',
                     'signature_verification':'real SDK, local test signing secret','real_stripe_payment':False,
                     'commercial_products_validated':0,'real_supplier_orders':0,'production_access':False}))


if __name__=='__main__':
    main()
