from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from app.catalog_availability import purchase_availability, purchasable
from app.site_config import public_site_configuration


def draft(**overrides):
    return {'id': '10000000-0000-4000-8000-000000000020', 'slug': 'fixture', 'sku': 'TEST',
            'name': 'Fixture', 'status': 'draft', 'stock': 0, 'price_cents': 1999, 'price': 0.01,
            'currency': 'EUR', 'images': [], 'compatible_brands': ['bmw'], 'compatibilities': [],
            'is_verified': False, **overrides}


def test_public_catalogue_stays_visible_without_demo_checkout(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test',
                                                   test_catalog_enabled=True, public_test_checkout_enabled=False))
    monkeypatch.setattr(server.catalog, 'product_rows', AsyncMock(return_value=[draft()]))
    monkeypatch.setattr(server.catalog, 'hydrate_products', AsyncMock(return_value=[draft()]))
    monkeypatch.setattr(server.catalog, 'product_by', AsyncMock(return_value=draft()))
    client = TestClient(server.app)
    listed = client.get('/api/products').json()['items'][0]
    detail = client.get('/api/products/fixture').json()
    for product in (listed, detail):
        assert product['status'] == 'draft'
        assert product['test_purchase'] is False
        assert product['purchase_available'] is False
        assert product['max_order_quantity'] == 0
    assert not purchasable(draft(), server.settings)


def test_public_checkout_cannot_open_test_stripe_even_with_active_inventory(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test',
                                                   test_catalog_enabled=True, public_test_checkout_enabled=False))
    active = draft(status='active', stock=3)
    assert not purchasable(active, server.settings)
    insert = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', insert)
    response = TestClient(server.app).post('/api/create-checkout-session',
                                           headers={'X-Session-Id': 'isolated_public_checkout_gate'})
    assert response.status_code == 503
    insert.assert_not_called()


def test_live_checkout_rejects_unconfirmed_vehicle_before_payment(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live', public_test_checkout_enabled=False))
    monkeypatch.setattr(server, 'legal_ready', lambda: True)
    create = AsyncMock()
    monkeypatch.setattr(server, 'stripe_client', SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(
        sessions=SimpleNamespace(create_async=create)))))
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': 'cart'}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'currency': 'EUR', 'items': [
        draft(status='active', stock=1, quantity=1, test_purchase=False)]}))
    insert = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', insert)
    response = TestClient(server.app).post('/api/create-checkout-session',
                                           headers={'X-Session-Id': 'isolated_live_fitment_gate'})
    assert response.status_code == 409
    assert 'Compatibilité non confirmée' in response.json()['detail']
    create.assert_not_called()
    insert.assert_not_called()


def test_live_checkout_requires_confirmed_supplier_offer_and_shipping(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='live', public_test_checkout_enabled=False))
    monkeypatch.setattr(server, 'legal_ready', lambda: True)
    monkeypatch.setattr(server, 'check_compatibility', lambda *_: {'status': 'compatible', 'reason': 'verified fixture'})
    create = AsyncMock()
    monkeypatch.setattr(server, 'stripe_client', SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(
        sessions=SimpleNamespace(create_async=create)))))
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': 'cart'}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'currency': 'EUR', 'items': [
        draft(status='active', stock=1, quantity=1, test_purchase=False,
              selected_vehicle={'brand_slug': 'bmw'})]}))
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[{
        'supplier_name': 'Supplier', 'supplier_reference': 'SKU', 'cost_price_cents': 1000,
        'shipping_cost_cents': None, 'supplier_verified': True}]))
    insert = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', insert)
    response = TestClient(server.app).post('/api/create-checkout-session',
                                           headers={'X-Session-Id': 'isolated_live_supplier_gate'})
    assert response.status_code == 409
    assert 'Offre fournisseur ou livraison non confirmée' in response.json()['detail']
    create.assert_not_called()
    insert.assert_not_called()


@pytest.mark.parametrize('mode,enabled,allowed', [('test', True, True), ('test', False, False), ('live', True, False)])
def test_test_availability_cannot_publish_or_fake_inventory(mode, enabled, allowed):
    config = replace(server.settings, stripe_mode=mode, test_catalog_enabled=enabled, public_test_checkout_enabled=True)
    original = draft()
    view = purchase_availability(original, config)
    assert view['purchase_available'] is allowed
    assert view['test_purchase'] is allowed
    assert view['max_order_quantity'] == (20 if allowed else 0)
    assert view['stock'] == original['stock'] == 0
    assert view['status'] == original['status'] == 'draft'
    assert view['is_verified'] is False
    assert public_site_configuration(config)['test_catalog_available'] is allowed


def test_archived_products_never_become_test_purchases():
    config = replace(server.settings, stripe_mode='test', test_catalog_enabled=True, public_test_checkout_enabled=True)
    assert not purchasable(draft(status='archived', test_purchase=True), config)
    assert not purchasable(draft(), config, 21)
    assert not purchasable(draft(), config, 0)


def test_active_inventory_limits_are_unchanged():
    config = replace(server.settings, stripe_mode='test', test_catalog_enabled=True, public_test_checkout_enabled=True)
    assert not purchasable(draft(status='active', stock=0), config)
    assert purchasable(draft(status='active', stock=3), config, 3)
    assert not purchasable(draft(status='active', stock=3), config, 4)


@pytest.mark.parametrize('mode,expected', [('test', 200), ('live', 404)])
def test_draft_cart_server_gate_not_browser_flag(monkeypatch, mode, expected):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode=mode, test_catalog_enabled=True, public_test_checkout_enabled=True))
    monkeypatch.setattr(server.catalog, 'product_by', AsyncMock(return_value=draft()))
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': 'cart'}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'items': [draft()]}))
    monkeypatch.setattr(server.db, 'select', AsyncMock(return_value=[]))
    insert = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', insert)
    response = TestClient(server.app).post('/api/cart', json={'product_id': draft()['id'], 'quantity': 2},
                                          headers={'X-Session-Id': 'isolated_test_catalog_capability'})
    assert response.status_code == expected
    assert insert.await_count == (1 if mode == 'test' else 0)


@pytest.mark.parametrize('enabled,expected', [(True, 200), (False, 409)])
def test_checkout_recomputes_test_gate_and_prices(monkeypatch, enabled, expected):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test', test_catalog_enabled=enabled, public_test_checkout_enabled=True))
    monkeypatch.setattr(server, 'checkout_attempts', {})
    create = AsyncMock(return_value=SimpleNamespace(id='cs_test_fixture', url='https://checkout.stripe.com/test'))
    monkeypatch.setattr(server, 'stripe_client', SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=create)))))
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': 'cart'}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'currency': 'EUR', 'items': [draft(quantity=2, test_purchase=True)]}))
    insert = AsyncMock(side_effect=[[{'id': 'order_fixture', 'order_number': 'TY-TEST'}], []])
    monkeypatch.setattr(server.db, 'insert', insert)
    monkeypatch.setattr(server.db, 'update', AsyncMock())
    response = TestClient(server.app).post('/api/create-checkout-session', headers={'X-Session-Id': 'isolated_test_catalog_capability'})
    assert response.status_code == expected
    if enabled:
        assert insert.call_args_list[0].args[1]['is_test'] is True
        assert insert.call_args_list[0].args[1]['requires_compatibility_review'] is True
        assert create.call_args.kwargs['params']['line_items'][0]['price_data']['unit_amount'] == 1999
    else:
        create.assert_not_called()
        insert.assert_not_called()


def test_test_purchase_does_not_bypass_incompatible_vehicle(monkeypatch):
    monkeypatch.setattr(server, 'settings', replace(server.settings, stripe_mode='test', test_catalog_enabled=True, public_test_checkout_enabled=True))
    monkeypatch.setattr(server, 'checkout_attempts', {})
    monkeypatch.setattr(server, 'stripe_client', object())
    monkeypatch.setattr(server, '_cart_for', AsyncMock(return_value={'id': 'cart'}))
    monkeypatch.setattr(server, '_cart_response', AsyncMock(return_value={'currency': 'EUR', 'items': [draft(quantity=1, selected_vehicle={'brand_slug': 'toyota'})]}))
    insert = AsyncMock()
    monkeypatch.setattr(server.db, 'insert', insert)
    response = TestClient(server.app).post('/api/create-checkout-session', headers={'X-Session-Id': 'isolated_test_catalog_capability'})
    assert response.status_code == 409
    insert.assert_not_called()
