"""Two synthetic suppliers/agents/parcels. FAKE Stripe; no real fulfillment."""
from copy import deepcopy
import json
from urllib.request import Request, urlopen
from uuid import uuid4

from tests.commerce_http_probe import request, sql, save, eq, HEADERS, ADMIN
from tests.commerce_pipeline_http_probe import webhook
import tests.commerce_http_probe as probe


def main():
    marker=uuid4().hex[:8]
    product=sql("select id from products where sku='TEST-001' and status='active'")[0]['id']
    rule=sql("select * from product_compatibilities where product_id=$1 and verification_state='verified' order by id",[product])[0]
    sql("update product_images set url='https://cdn.example.com/isolated-fixture.webp' where product_id=$1",[product])
    sql("""insert into commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,
        derivatives_use,product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
        values($1,'https://cdn.example.com/isolated-fixture.webp','verified','SYNTHETIC ONLY',true,true,true,
          'not_present',array['FR'],now()+interval '1 year',$2,now())""",[product,ADMIN])
    vehicle={'brand_slug':'bmw','model':rule['model_name'],'chassis':rule['chassis'],
             'year':rule['year_from'],'facelift':'pre-lci','body_type':'sedan'}
    guest={'X-Session-Id':'multigroup_'+marker}
    sources=[]
    for n in range(2):
        label=f'MULTIGROUP-{marker}-{n}'
        supplier=sql('insert into suppliers(name,url) values($1,$2) returning id',
            ['SYNTHETIC supplier '+label,'https://supplier.example.test/'+label])[0]['id']
        agent=save('agent',{'profile_id':ADMIN,'name':'SYNTHETIC operator '+label,'role':'orders','is_active':True})
        variant=save('variant',{'product_id':product,'sku':label,'name':'SYNTHETIC variant '+str(n),
            'price_cents':3000+1000*n,'stock':3,'status':'active','is_verified':True,'requires_vehicle':True,
            'evidence_ref':'SYNTHETIC ONLY','compatibility_ids':[rule['id']]})
        offer=save('offer',{'variant_id':variant['id'],'supplier_id':supplier,'supplier_sku':'SOURCE-'+label,
            'supplier_variant':'Synthetic exact black','url':'https://supplier.example.test/'+label,
            'verification_state':'verified','evidence_ref':'SYNTHETIC ONLY','is_primary':True,
            'availability':'available','available_quantity':3,'valid_until':'2099-01-01T00:00:00Z',
            'unit_cost_cents':1000+500*n,'recoverable_tax_cents':0,'currency':'EUR',
            'preparation_days_min':1,'preparation_days_max':2,'responsible_agent_id':agent['id']})
        rate=save('shipping_rate',{'offer_id':offer['id'],'country':'FR','mode':'tracked','max_quantity':3,
            'shipping_cost_cents':200+100*n,'shipping_recoverable_tax_cents':0,'customer_shipping_cents':500+200*n,
            'goods_tax_bps':0,'shipping_tax_bps':0,'agent_fee_cents':0,'import_duty_cents':0,
            'nonrecoverable_tax_cents':0,'other_cost_cents':0,'verification_state':'verified',
            'multi_variant_policy':'independent_parcels','evidence_ref':'SYNTHETIC ONLY',
            'valid_until':'2099-01-01T00:00:00Z','delivery_days_min':3,'delivery_days_max':5})
        mapping=request('/admin/commerce/hypersku/mappings','POST',{'data':{
            'offer_id':offer['id'],'shipping_rate_id':rate['id'],'is_test':True,'state':'verified',
            'hypersku_product_ref':'SYNTHETIC-PRODUCT-'+label,'hypersku_variant_ref':'SYNTHETIC-VARIANT-'+label,
            'equivalence_evidence_ref':'SYNTHETIC ONLY','provider_quote_ref':'SYNTHETIC ONLY',
            'valid_until':'2098-01-01T00:00:00Z'}},HEADERS)
        request('/cart','POST',{'product_id':product,'variant_id':variant['id'],'quantity':1,'selected_vehicle':vehicle},guest)
        sources.append({'supplier_id':supplier,'agent':agent,'variant':variant,'offer':offer,'rate':rate,'mapping':mapping})
    quote=request('/cart/quote','POST',{'request_key':str(uuid4()),'mode':'tracked','destination':{
        'name':'Synthetic recipient','line1':'1 Synthetic street','city':'Paris','country':'FR','postal_code':'75001'}},guest)
    prepared=request('/admin/commerce/quotes/'+quote['quote_id']+'/prepare-test-order','POST',headers=HEADERS)
    oid=prepared['order_id']
    attempt=request('/admin/commerce/orders/'+oid+'/checkout-attempt','POST',headers=HEADERS)
    with urlopen(Request('http://127.0.0.1:8765/qa-payment-attempt/'+attempt['attempt_id'],method='POST',headers=HEADERS),timeout=30) as response:
        sid=json.load(response)['session_id']
    order=sql('select * from orders where id=$1',[oid])[0]
    raw=sql('select * from commerce_checkout_attempts where id=$1',[attempt['attempt_id']])[0]
    eq(order['subtotal_cents'],7000);eq(order['shipping_amount_cents'],1200);eq(order['total_cents'],8200)
    session={'object':'checkout.session','id':sid,'mode':'payment','livemode':False,'currency':'eur',
        'client_reference_id':oid,'expires_at':int(raw['expires_at']),
        'metadata':{'order_id':oid,'quote_id':quote['quote_id'],'attempt_id':attempt['attempt_id']},
        'amount_subtotal':7000,'amount_total':8200,'total_details':{'amount_discount':0,'amount_tax':0,'amount_shipping':1200},
        'automatic_tax':{'enabled':False},'status':'complete','payment_status':'paid','payment_intent':'pi_'+uuid4().hex,
        'shipping_details':{'address':deepcopy(order['shipping_address'])},'customer_details':{'email':'recipient@example.com'}}
    event={'object':'event','id':'evt_'+uuid4().hex,'type':'checkout.session.completed','livemode':False,'data':{'object':session}}
    eq(webhook(event)['duplicate'],False);eq(webhook(event)['duplicate'],True)
    tasks=sql('select * from commerce_test_tasks where order_id=$1 order by variant_id',[oid])
    eq(len(tasks),2);eq(len({t['supplier_id'] for t in tasks}),2);eq(len({t['agent_id'] for t in tasks}),2)
    for source in sources:
        task=next(t for t in tasks if t['variant_id']==source['variant']['id'])
        eq(task['supplier_id'],source['supplier_id']);eq(task['agent_id'],source['agent']['id'])
        eq(task['supplier_sku'],source['offer']['supplier_sku'])
        eq(task['snapshot']['rate']['shipping_cost_cents'],source['rate']['shipping_cost_cents'])
        internal=request('/admin/commerce/hypersku/tasks/'+task['id']+'/prepare','POST',{'mapping_id':source['mapping']['id']},HEADERS)
        eq(internal['external_send_allowed'],False);eq(internal['expenses_authorized'],False)
    def aggregate(expected):
        result=request('/admin/commerce/orders/'+oid+'/simulation-status',headers=HEADERS)
        eq(result['aggregate_state'],expected);eq(result['simulated_parcel_count'],2)
        eq(result['scope'],'simulation_only_not_real_shipment')
        return result
    aggregate('prepared')
    for n,task in enumerate(tasks):
        for previous,following in [('prepared','received_by_agent'),('received_by_agent','quality_checked'),('quality_checked','shipped')]:
            body={'expected':previous,'next':following}
            if following=='shipped': body['tracking_number']='SIM-MULTI-'+marker+'-'+str(n)
            request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',body,HEADERS)
        aggregate('partially_shipped' if n==0 else 'shipped')
    for n,task in enumerate(tasks):
        # A conflicting number is forbidden; omission retains the stored one.
        request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',
            {'expected':'shipped','next':'delivered','tracking_number':'SIM-WRONG'},HEADERS,status=409)
        body={'expected':'shipped','next':'delivered'}
        delivered=request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',body,HEADERS)
        eq(delivered['tracking_number'],'SIM-MULTI-'+marker+'-'+str(n))
        eq(request('/admin/commerce/test-tasks/'+task['id']+'/simulate','POST',body,HEADERS),delivered)
        aggregate('partially_delivered' if n==0 else 'delivered')
    public=request('/order-tracking','POST',{'order_number':order['order_number'],'email':'recipient@example.com'})
    eq(public['simulation']['aggregate_state'],'delivered')
    eq(len({p['tracking_number'] for p in public['simulation']['parcels']}),2)
    eq(set(public['simulation']['parcels'][0]),{'reference','state','tracking_number'})
    for private in ('supplier_id','supplier_sku','offer_id','agent_id','cost_price_cents','commerce_quote_id'):
        eq(private in json.dumps(public),False)
    eq(sql('select fulfillment_status from orders where id=$1',[oid])[0]['fulfillment_status'],'requires_review')
    eq(webhook(event)['duplicate'],True)
    eq(sql('select count(*)::int n from orders where commerce_quote_id=$1',[quote['quote_id']])[0]['n'],1)
    eq(sql('select count(*)::int n from commerce_test_tasks where order_id=$1',[oid])[0]['n'],2)
    eq(sql('select count(*)::int n from supplier_orders where order_id=$1',[oid])[0]['n'],0)
    print(json.dumps({'checks':probe.checks,'result':'passed','suppliers':2,'agents':2,'simulated_parcels':2,
        'stripe_transport':'FAKE','real_stripe_payment':False,'real_supplier_orders':0,'commercial_products_validated':0}))


if __name__=='__main__': main()
