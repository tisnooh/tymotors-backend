"""A truncated database response must never produce a partial agent dossier."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.commerce_fulfillment_api import create_test_fulfillment_router


@pytest.mark.parametrize('total,returned', [(2,1),(101,100),(0,1)])
def test_partial_order_plan_is_rejected_before_planning(total, returned):
    db = SimpleNamespace(select=AsyncMock(return_value=[{'id':'order'}]),
        page=AsyncMock(return_value={'total':total,'items':[{} for _ in range(returned)]}))
    app = FastAPI()
    app.include_router(create_test_fulfillment_router(db, lambda: {'id':'admin'}, lambda: None))
    with patch('app.commerce_fulfillment_api.plan_test_fulfillment') as planner:
        response = TestClient(app).get('/api/admin/commerce/orders/10000000-0000-4000-8000-000000000001/fulfillment-plan')
    assert response.status_code == 409
    assert response.json()['detail'] == 'incomplete_fulfillment_plan_source'
    planner.assert_not_called()


def test_complete_order_is_planned_once_with_exact_lines():
    order, lines = {'id':'order'}, [{'order_item_id':'first'},{'order_item_id':'second'}]
    db = SimpleNamespace(select=AsyncMock(return_value=[order]),
        page=AsyncMock(return_value={'total':2,'items':lines}))
    app = FastAPI()
    app.include_router(create_test_fulfillment_router(db, lambda: {'id':'admin'}, lambda: None))
    with patch('app.commerce_fulfillment_api.plan_test_fulfillment', return_value=[{'quantity':2}]) as planner:
        response = TestClient(app).get('/api/admin/commerce/orders/10000000-0000-4000-8000-000000000001/fulfillment-plan')
    assert response.status_code == 200
    assert response.json()['external_send_allowed'] is False
    planner.assert_called_once_with(order, lines)
    assert db.page.await_args.kwargs['limit'] == 100
