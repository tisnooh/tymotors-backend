from copy import deepcopy
from uuid import uuid4
import pytest
from app.commerce_fulfillment import plan_test_fulfillment, FulfillmentPlanError


@pytest.fixture
def snapshots():
    ids=[str(uuid4()) for _ in range(9)]
    oid,qid,supplier,agent,offer,rate,variant,item1,item2=ids
    order={'id':oid,'commerce_quote_id':qid,'is_test':True,'currency':'EUR'}
    group={'variant_id':variant,'supplier_id':supplier,'responsible_agent_id':agent,
           'offer_id':offer,'shipping_rate_id':rate,'lines':[{'quantity':1},{'quantity':2}],
           'evaluation':{'status':'ready','currency':'EUR','supplier_gross_cents':300,
                         'acquisition_net_cents':300,'shipping_net_cents':500,'landed_cost_cents':800}}
    common={'order_id':oid,'quote_id':qid,'group_snapshot':group,
        'offer_snapshot':{'id':offer,'supplier_id':supplier,'responsible_agent_id':agent,'variant_id':variant,
                          'supplier_sku':'EXACT-BLACK','currency':'EUR','unit_cost_cents':100},
        'rate_snapshot':{'id':rate,'offer_id':offer,'shipping_cost_cents':500},
        'agent_snapshot':{'id':agent},'supplier_snapshot':{'id':supplier}}
    lines=[{**deepcopy(common),'order_item_id':item1,'line_snapshot':{'variant_id':variant,'quantity':1}},
           {**deepcopy(common),'order_item_id':item2,'line_snapshot':{'variant_id':variant,'quantity':2}}]
    return order,lines


def test_vehicle_lines_group_without_double_shipping_and_preserve_exact_references(snapshots):
    before=deepcopy(snapshots)
    result=plan_test_fulfillment(*snapshots)
    assert len(result)==1 and result[0]['quantity']==3
    assert result[0]['shipping_cost_cents']==500 and result[0]['acquisition_net_eur_cents']==300
    assert result[0]['supplier_sku']=='EXACT-BLACK' and result[0]['external_send_allowed'] is False
    assert snapshots==before


def test_foreign_supplier_cost_not_mislabelled_eur(snapshots):
    for line in snapshots[1]:
        line['offer_snapshot'].update(currency='USD',unit_cost_cents=200)
    task=plan_test_fulfillment(*snapshots)[0]
    assert task['supplier_currency']=='USD' and task['supplier_total_cost_minor']==600
    assert task['acquisition_net_eur_cents']==300  # Frozen confirmed conversion, never reconverted here.


@pytest.mark.parametrize('change',['real','currency','missing_line','duplicate','agent','unknown_cost','variant'])
def test_inconsistent_or_unverified_plan_refused(snapshots,change):
    order,lines=snapshots
    if change=='real': order['is_test']=False
    if change=='currency': order['currency']='USD'
    if change=='missing_line': lines.pop()
    if change=='duplicate': lines.append(deepcopy(lines[0]))
    if change=='agent': lines[0]['agent_snapshot']['id']=str(uuid4())
    if change=='unknown_cost': lines[0]['offer_snapshot']['unit_cost_cents']=None
    if change=='variant': lines[0]['line_snapshot']['variant_id']=str(uuid4())
    with pytest.raises(FulfillmentPlanError): plan_test_fulfillment(order,lines)
