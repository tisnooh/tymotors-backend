from copy import deepcopy
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.commerce_fulfillment import summarize_test_fulfillment, FulfillmentPlanError
from tests.test_commerce_operations_api import operations, HEADERS  # noqa: F401
import server


@pytest.fixture
def parcels():
    order = {'id':str(uuid4()),'is_test':True,'status':'paid','payment_status':'paid','refunded_amount_cents':0}
    tasks = [{'id':str(uuid4()),'order_id':order['id'],'is_test':True,'group_key':str(n),
        'state':'prepared','tracking_number':None,'supplier_sku':'PRIVATE-SKU','cost':999} for n in range(2)]
    return order, tasks, {'0','1'}


@pytest.mark.parametrize('states,expected',[
    (['prepared','prepared'],'prepared'), (['received_by_agent','prepared'],'in_progress'),
    (['quality_checked','received_by_agent'],'in_progress'), (['shipped','prepared'],'partially_shipped'),
    (['shipped','shipped'],'shipped'), (['delivered','shipped'],'partially_delivered'),
    (['delivered','prepared'],'partially_delivered'), (['delivered','delivered'],'delivered'),
])
def test_simulated_aggregate_has_complete_coverage_without_private_data(parcels, states, expected):
    order,tasks,groups = parcels
    for n,state in enumerate(states):
        tasks[n].update(state=state,tracking_number='SIM-PARCEL-'+str(n) if state in {'shipped','delivered'} else None)
    before=deepcopy(parcels)
    result=summarize_test_fulfillment(order,tasks,groups)
    assert result['aggregate_state']==expected and result['simulated_parcel_count']==2
    assert result['scope']=='simulation_only_not_real_shipment'
    assert all(set(row)=={'reference','state','tracking_number'} for row in result['parcels'])
    assert 'PRIVATE' not in str(result) and '999' not in str(result)
    assert parcels==before


@pytest.mark.parametrize('change', ['live','crossorder','duplicate','group','missing','state','missing_tracking','real_tracking','early_tracking','malformed'])
def test_incomplete_or_inconsistent_projection_rejected(parcels,change):
    order,tasks,groups=parcels
    if change=='live': order['is_test']=False
    elif change=='crossorder': tasks[0]['order_id']=str(uuid4())
    elif change=='duplicate': tasks.append(deepcopy(tasks[0]))
    elif change=='group': tasks[0]['group_key']='foreign'
    elif change=='missing': tasks.pop()
    elif change=='state': tasks[0]['state']='real_shipped'
    elif change=='missing_tracking': tasks[0]['state']='shipped'
    elif change=='real_tracking': tasks[0].update(state='shipped',tracking_number='REAL-CARRIER')
    elif change=='early_tracking': tasks[0]['tracking_number']='SIM-EARLY'
    elif change=='malformed': tasks[0]=None
    with pytest.raises(FulfillmentPlanError): summarize_test_fulfillment(order,tasks,groups)


@pytest.mark.parametrize('changes,expected',[
    ({'payment_status':'unpaid'},'awaiting_payment'), ({'status':'cancelled'},'held'),
    ({'status':'refunded'},'held'), ({'refunded_amount_cents':1},'held'), ({},'requires_review')])
def test_no_tasks_does_not_claim_delivery(parcels,changes,expected):
    order,_,groups=parcels
    assert summarize_test_fulfillment({**order,**changes},[],groups)['aggregate_state']==expected


def test_private_simulation_route_requires_admin_before_storage(operations):
    response=operations.get('/api/admin/commerce/orders/'+str(uuid4())+'/simulation-status')
    assert response.status_code==401
    server.db.select.assert_not_awaited()


@pytest.mark.parametrize('incomplete',[False,True])
def test_private_simulation_route_enforces_complete_pages(operations,monkeypatch,parcels,incomplete):
    order,tasks,groups=parcels
    original=server.db.select
    async def select(table,**kwargs):
        if table=='orders': return [order]
        return await original(table,**kwargs)
    async def page(table,**kwargs):
        rows=[{'group_key':x} for x in sorted(groups)] if table=='commerce_order_lines' else tasks
        return {'items':rows,'total':len(rows)+(1 if incomplete else 0)}
    monkeypatch.setattr(server.db,'select',AsyncMock(side_effect=select))
    monkeypatch.setattr(server.db,'page',AsyncMock(side_effect=page))
    response=operations.get('/api/admin/commerce/orders/'+order['id']+'/simulation-status',headers=HEADERS)
    assert response.status_code==(409 if incomplete else 200)
    server.db.rpc.assert_not_awaited()
