import asyncio
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import server
from app.cart_service import CartService
from tests.test_commerce_pricing import PRODUCT, VARIANT, VARIANT2, RULE, PROFILE

CART = '10000000-0000-4000-8000-000000000050'
LINE = '10000000-0000-4000-8000-000000000051'
LINE2 = '10000000-0000-4000-8000-000000000052'


@pytest.fixture
def cart_case():
    product = {'id': PRODUCT, 'name': 'Synthetic', 'slug': 'fixture', 'sku': 'BASE', 'stock': 0,
               'price_cents': 100, 'price': 1, 'currency': 'EUR', 'status': 'active', 'is_verified': True,
               'images': ['https://example.test/unchanged.png'],
               'compatibilities': [{'id': RULE, 'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30',
                                    'year_from': 2012, 'year_to': 2018, 'is_verified': True}]}
    variant = {'id': VARIANT, 'product_id': PRODUCT, 'sku': 'BLACK', 'name': 'Black', 'price_cents': 12000,
               'currency': 'EUR', 'stock': 3, 'status': 'active', 'is_verified': True, 'evidence_ref': 'fixture', 'requires_vehicle': True}
    vehicle = {'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30', 'generation': 'F30', 'year': 2016,
               'facelift': 'lci', 'has_camera': False, 'has_parking_sensors': False,
               'compatibility_status': 'incompatible'}  # display metadata is never authoritative
    data = {'products': [product], 'product_variants': [variant],
            'cart_items': [{'id': LINE, 'product_id': PRODUCT, 'variant_id': VARIANT, 'quantity': 2, 'selected_vehicle': vehicle}],
            'variant_compatibilities': [{'variant_id': VARIANT, 'compatibility_id': RULE}]}
    async def page(table, **kwargs):
        return {'items': deepcopy(data[table]), 'total': len(data[table])}
    async def select(table, **kwargs):
        return deepcopy(data[table])
    db = SimpleNamespace(page=page, select=select)
    catalog = SimpleNamespace(hydrate_products=AsyncMock(side_effect=lambda rows: rows))
    config = replace(server.settings, stripe_mode='test', test_catalog_enabled=True)
    return data, CartService(db, catalog, config)


def render(case):
    return asyncio.run(case.response({'id': CART, 'currency': 'EUR'}))


def test_variant_price_sku_vehicle_and_line_identity_come_from_server(cart_case):
    data, service = cart_case
    before = deepcopy(data)
    cart = render(service)
    item = cart['items'][0]
    assert item['product_id'] == PRODUCT and item['cart_item_id'] == LINE and item['variant_id'] == VARIANT
    assert item['sku'] == 'BLACK' and item['price_cents'] == 12000 and item['line_total'] == 240
    assert cart['subtotal'] == 240
    assert item['images'] == data['products'][0]['images']
    assert item['selected_vehicle']['facelift'] == 'lci' and item['selected_vehicle']['has_camera'] is False
    assert item['compatibility_result']['status'] == 'compatible'
    assert item['purchase_available'] is True  # variant stock, not the old base stock
    assert cart['shipping'] is None and cart['total'] is None
    assert cart['shipping_status'] == 'requires_quote' and cart['checkout_available'] is False
    assert data == before


def test_distinct_vehicles_keep_distinct_lines_and_aggregate_stock_limit(cart_case):
    data, service = cart_case
    data['cart_items'].append({**data['cart_items'][0], 'id': LINE2, 'quantity': 1,
                               'selected_vehicle': {**data['cart_items'][0]['selected_vehicle'], 'year': 2017}})
    items = render(service)['items']
    assert [item['cart_item_id'] for item in items] == [LINE, LINE2]
    assert [item['max_order_quantity'] for item in items] == [2, 1]
    assert [item['selected_vehicle']['year'] for item in items] == [2016, 2017]


def test_removed_or_foreign_variant_never_falls_back_to_base_price(cart_case):
    data, service = cart_case
    data['product_variants'] = []
    with pytest.raises(HTTPException) as exc:
        render(service)
    assert exc.value.status_code == 409


def test_archived_variant_remains_removable_as_its_exact_blocked_line(cart_case):
    data, service = cart_case
    data['product_variants'][0]['status'] = 'archived'
    cart = render(service)
    assert cart['items'][0]['cart_item_id'] == LINE
    assert cart['items'][0]['price_cents'] == 12000
    assert cart['items'][0]['purchase_available'] is False
    assert cart['items'][0]['line_blocked_reason'] == 'variant_not_verified_active'
    assert cart['checkout_available'] is False


def test_variant_fitment_is_scoped_not_inherited_from_other_variant(cart_case):
    data, service = cart_case
    data['variant_compatibilities'][0]['compatibility_id'] = VARIANT2
    assert render(service)['items'][0]['compatibility_result']['status'] != 'compatible'


def test_changed_stock_and_currency_are_not_silently_purchasable(cart_case):
    data, service = cart_case
    data['product_variants'][0]['stock'] = 1
    assert render(service)['items'][0]['purchase_available'] is False
    data['product_variants'][0].update(stock=3, currency='USD')
    item = render(service)['items'][0]
    assert item['line_blocked_reason'] == 'cart_currency_mismatch'


def test_legacy_test_totals_remain_and_live_shipping_cannot_be_invented(cart_case):
    data, service = cart_case
    data['product_variants'] = []
    data['cart_items'][0]['variant_id'] = None
    data['products'][0].update(status='draft', is_verified=False)
    cart = render(service)
    assert cart['subtotal'] == 2
    assert cart['shipping'] == service.settings.shipping_rate_cents / 100
    assert cart['total'] == cart['subtotal'] + cart['shipping']
    assert cart['checkout_available'] is True
    service.settings = replace(service.settings, stripe_mode='live')
    cart = render(service)
    assert cart['shipping'] is None and cart['checkout_available'] is False


def test_sandbox_drafts_keep_per_line_cap_without_inventing_inventory(cart_case):
    data, service = cart_case
    data['product_variants'] = []
    data['products'][0].update(status='draft', is_verified=False)
    data['cart_items'][0].update(variant_id=None, quantity=20)
    data['cart_items'].append({**data['cart_items'][0], 'id': LINE2,
                               'selected_vehicle': {**data['cart_items'][0]['selected_vehicle'], 'year': 2017}})
    cart = render(service)
    assert [line['max_order_quantity'] for line in cart['items']] == [20, 20]
    assert cart['checkout_available'] is True
    assert data['products'][0]['stock'] == 0


def test_truncated_cart_is_not_presented_as_complete(cart_case):
    data, service = cart_case
    service.db.page = AsyncMock(return_value={'items': data['cart_items'], 'total': 2})
    with pytest.raises(HTTPException):
        render(service)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': CART}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'items': []}))
    monkeypatch.setattr(server, '_purchasable_product', AsyncMock(return_value={'id': PRODUCT, 'status': 'active', 'stock': 10}))
    monkeypatch.setattr(server.db, 'rpc', AsyncMock(return_value=LINE))
    return TestClient(server.app)


def test_add_and_update_exact_identity_use_owner_scoped_atomic_rpc(client):
    headers = {'X-Session-Id': 'synthetic_session_cart_123'}
    response = client.post('/api/cart', json={'product_id': PRODUCT, 'variant_id': VARIANT, 'quantity': 2,
                                             'selected_vehicle': {'brand_slug': 'bmw', 'has_camera': False}}, headers=headers)
    assert response.status_code == 200
    name, payload = server.db.rpc.call_args.args
    assert name == 'commerce_cart_add' and payload['p_variant_id'] == VARIANT
    assert payload['p_vehicle']['has_camera'] is False
    assert payload['p_user_id'] is None and payload['p_guest_session'] == headers['X-Session-Id']
    response = client.put('/api/cart', json={'product_id': PRODUCT, 'cart_item_id': LINE, 'quantity': 1}, headers=headers)
    assert response.status_code == 200
    assert server.db.rpc.call_args.args[0] == 'commerce_cart_update'
    assert server.db.rpc.call_args.args[1]['p_line_id'] == LINE
    response = client.delete('/api/cart/' + PRODUCT + '?cart_item_id=' + LINE2, headers=headers)
    assert response.status_code == 200
    assert server.db.rpc.call_args.args[1]['p_line_id'] == LINE2
    assert server.db.rpc.call_args.args[1]['p_quantity'] == 0


def test_request_cannot_supply_price_or_supplier_and_bad_line_id(client):
    headers = {'X-Session-Id': 'synthetic_session_cart_123'}
    assert client.post('/api/cart', headers=headers, json={'product_id': PRODUCT, 'variant_id': VARIANT,
                                                         'price_cents': 1}).status_code == 422
    assert client.delete('/api/cart/' + PRODUCT + '?cart_item_id=bad', headers=headers).status_code == 422
    server.db.rpc.assert_not_awaited()


def test_variant_cannot_reach_old_checkout_and_charge_base_reference(client, monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test',
        stripe_webhook_secret='whsec_synthetic_fixture_not_a_credential'))
    monkeypatch.setattr(server, 'stripe_client', object())
    monkeypatch.setattr(server, 'checkout_attempts', {})
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'items': [{'variant_id': VARIANT}], 'checkout_available': False}))
    create_order = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', create_order)
    response = client.post('/api/create-checkout-session', headers={'X-Session-Id': 'synthetic_session_cart_123'})
    assert response.status_code == 409
    create_order.assert_not_awaited()
