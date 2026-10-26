"""Finish a REAL Stripe sandbox case with SIM-only supplier/logistics steps.

Only the owned disposable loopback fixture is accepted. No HyperSKU/provider
API, order upload, real purchase or carrier operation exists in this script.
"""
import argparse
import json
from urllib.request import urlopen
from uuid import UUID

import tests.commerce_http_probe as probe
from tests.commerce_http_probe import request, sql, HEADERS


def run(order_id, preparation_id):
    if probe.API!='http://127.0.0.1:8765/api' or probe.SQL!='http://127.0.0.1:8766/query':
        raise RuntimeError('Literal loopback fixture required')
    with urlopen('http://127.0.0.1:8765/qa-stripe-sandbox-status',timeout=10) as response:
        identity=json.load(response)
    assert identity['fixture']=='real_stripe_sandbox_disposable_database' and identity['is_test'] is True
    order=sql('select * from orders where id=$1',[order_id])[0]
    assert order['is_test'] is True and order['payment_status']=='paid'
    lines=sql('select line_snapshot from commerce_order_lines where order_id=$1',[order_id])
    assert lines and all(line['line_snapshot']['sku'].startswith('SANDBOX-SYNTHETIC-') for line in lines)
    tasks=sql('select * from commerce_test_tasks where order_id=$1',[order_id])
    assert len(tasks)==1
    task=tasks[0]
    prepared=request('/admin/commerce/hypersku/preparations/'+preparation_id,headers=HEADERS)
    assert prepared['order_id']==order_id and prepared['task_id']==task['id']
    assert prepared['is_test'] is True and prepared['state']=='awaiting_human_review'
    assert prepared['external_send_allowed'] is False and prepared['expenses_authorized'] is False
    assert prepared['packet']['certified_provider_import'] is False
    tracking_number='SIM-SUPPLIER-DRY-'+UUID(order_id).hex[:10]
    steps=[]
    for previous,following in [('prepared','received_by_agent'),('received_by_agent','quality_checked'),
                               ('quality_checked','shipped'),('shipped','delivered')]:
        payload={'expected':previous,'next':following}
        if following=='shipped':payload['tracking_number']=tracking_number
        endpoint='/admin/commerce/test-tasks/'+task['id']+'/simulate'
        first=request(endpoint,'POST',payload,HEADERS)
        repeat=request(endpoint,'POST',payload,HEADERS)
        assert first==repeat and first['state']==following
        steps.append({'state':following,'repeat_idempotent':True,'scope':'SIM_ONLY'})
    tracking=request('/order-tracking','POST',{'order_number':order['order_number'],'email':order['customer_email']})
    assert tracking['simulation']['scope']=='simulation_only_not_real_shipment'
    assert tracking['simulation']['aggregate_state']=='delivered'
    assert tracking['simulation']['parcels'][0]['tracking_number']==tracking_number
    real_orders=sql('select count(*)::int n from supplier_orders where order_id=$1',[order_id])[0]['n']
    actual=sql('select fulfillment_status from orders where id=$1',[order_id])[0]['fulfillment_status']
    assert real_orders==0 and actual=='requires_review'
    offer,rate=task['snapshot']['offer'],task['snapshot']['rate']
    assert offer['currency']=='EUR'
    quantity=sum(line['line_snapshot']['quantity'] for line in lines)
    return {'result':'passed','scope':'supplier_purchase_dry_run_and_simulated_shipping_only',
        'order_number':order['order_number'],'order_id':order_id,'preparation_id':preparation_id,
        'provider_order_submitted':False,'provider_purchase_paid':False,'real_supplier_orders':real_orders,
        'packet_state':prepared['state'],'certified_provider_import':False,
        'fictitious_purchase':{'supplier_sku':task['supplier_sku'],'variant':offer['supplier_variant'],
            'quantity':quantity,'currency':'EUR','unit_cost_cents':offer['unit_cost_cents'],
            'shipping_cost_cents':rate['shipping_cost_cents'],
            'total_cents':offer['unit_cost_cents']*quantity+rate['shipping_cost_cents'],
            'source':'SYNTHETIC FIXTURE NOT A VERIFIED COMMERCIAL QUOTE'},
        'steps':steps,'customer_tracking_number':tracking_number,'actual_fulfillment_status':actual}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-id',type=UUID,required=True)
    parser.add_argument('--preparation-id',type=UUID,required=True)
    args=parser.parse_args()
    print(json.dumps(run(str(args.order_id),str(args.preparation_id)),ensure_ascii=False))


if __name__=='__main__':main()
