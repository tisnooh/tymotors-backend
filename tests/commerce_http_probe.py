"""Opt-in loopback API -> disposable PostgreSQL probe, never Stripe/production.

Run admin_database.mjs --serve and python -m tests.serve_admin_fixture first.
Synthetic admin tokens are recognized ONLY by that explicitly test-only server.
"""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

API = 'http://127.0.0.1:8765/api'
SQL = 'http://127.0.0.1:8766/query'
ADMIN = '10000000-0000-4000-8000-000000000001'
HEADERS = {'Authorization': 'Bearer admin-test-token'}
checks = 0


def request(path, method='GET', payload=None, headers=None, status=200):
    global checks
    req = Request(API + path, method=method, headers={'Content-Type': 'application/json', **(headers or {})},
                  data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req, timeout=30) as response:
            code, data = response.status, json.load(response)
    except HTTPError as error:
        code, data = error.code, json.load(error)
    assert code == status, (path, code, data)
    checks += 1
    return data


def sql(statement, params=None):
    req = Request(SQL, method='POST', headers={'Content-Type': 'application/json'},
                  data=json.dumps({'sql': statement, 'params': params or []}).encode())
    with urlopen(req, timeout=30) as response:
        return json.load(response)['rows']


def eq(actual, expected):
    global checks
    assert actual == expected, (actual, expected)
    checks += 1


def save(kind, data):
    return request('/admin/commerce/' + kind, 'POST', {'data': data}, HEADERS)


def main():
    marker = uuid4().hex[:10]
    fixture = sql("select id,status from products where sku='TEST-001'")
    assert len(fixture) == 1 and fixture[0]['status'] == 'active', 'Disposable fixture is required'
    product = fixture[0]['id']
    before_orders = sql('select count(*)::integer n from orders')[0]['n']
    request('/cart', 'DELETE', headers={'Authorization': 'Bearer customer-test-token'})
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    base = {'product_id': product, 'sku': 'HTTP-BLACK-' + marker, 'name': 'Synthetic black', 'price_cents': 3000,
            'stock': 3, 'status': 'active', 'is_verified': True, 'requires_vehicle': False,
            'evidence_ref': 'local-synthetic-probe:' + marker}
    black = save('variant', base)
    carbon = save('variant', {**base, 'sku': 'HTTP-CARBON-' + marker, 'name': 'Synthetic carbon', 'price_cents': 6000})
    actor = save('agent', {'profile_id': ADMIN, 'name': 'Synthetic order operator', 'role': 'orders', 'is_active': True})
    offer_data = {'variant_id': black['id'], 'supplier_id': supplier, 'supplier_sku': 'SUP-BLACK-' + marker,
                  'supplier_variant': 'Exact synthetic black', 'url': 'https://supplier.example.test/' + marker,
                  'verification_state': 'verified', 'evidence_ref': 'local-synthetic-terms:' + marker,
                  'is_primary': True, 'availability': 'available', 'available_quantity': 3,
                  'valid_until': '2099-01-01T00:00:00Z', 'unit_cost_cents': 2000, 'recoverable_tax_cents': 0,
                  'currency': 'EUR', 'preparation_days_min': 1, 'preparation_days_max': 2, 'responsible_agent_id': actor['id']}
    offer = save('offer', offer_data)
    save('shipping_rate', {'offer_id': offer['id'], 'country': 'FR', 'mode': 'tracked', 'max_quantity': 3,
                           'shipping_cost_cents': 300, 'shipping_recoverable_tax_cents': 0, 'customer_shipping_cents': 500,
                           'goods_tax_bps': 0, 'shipping_tax_bps': 0, 'agent_fee_cents': 0, 'import_duty_cents': 0,
                           'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0, 'verification_state': 'verified',
                           'evidence_ref': 'local-synthetic-rate:' + marker, 'valid_until': '2099-01-01T00:00:00Z',
                           'delivery_days_min': 3, 'delivery_days_max': 5})
    quote_request = {'variant_id': black['id'], 'quantity': 2, 'country': 'FR', 'postal_code': '75001', 'mode': 'tracked'}
    before = request('/admin/commerce/quote', 'POST', quote_request, HEADERS)
    eq(before['status'], 'ready')
    eq(before['offers'][0]['supplier_sku'], offer_data['supplier_sku'])
    eq(before['offers'][0]['landed_cost_cents'], 4300)
    eq(before['offers'][0]['customer_total_cents'], 6500)
    eq(before['offers'][0]['contribution_margin_cents'], 2200)
    request('/admin/commerce/quote', 'POST', quote_request, status=401)
    changed = request('/admin/commerce/offer/' + offer['id'], 'PUT',
                      {'data': {**offer_data, 'unit_cost_cents': 2100}, 'expected_updated_at': offer['updated_at']}, HEADERS)
    after = request('/admin/commerce/quote', 'POST', quote_request, HEADERS)
    eq(after['offers'][0]['landed_cost_cents'], 4500)
    eq(before['offers'][0]['landed_cost_cents'], 4300)
    request('/admin/commerce/offer/' + offer['id'], 'PUT',
            {'data': offer_data, 'expected_updated_at': offer['updated_at']}, HEADERS, status=409)
    guest = {'X-Session-Id': 'synthetic_probe_guest_' + marker}
    vehicle = {'brand_slug': 'bmw', 'model': 'Series 3', 'chassis': 'F30', 'year': 2016,
               'facelift': 'lci', 'has_camera': False}
    def add(variant_id, quantity, selected=vehicle, headers=guest):
        return request('/cart', 'POST', {'product_id': product, 'variant_id': variant_id, 'quantity': quantity,
                                        'selected_vehicle': selected}, headers)
    cart = add(black['id'], 2)
    first = cart['items'][0]['cart_item_id']
    cart = add(carbon['id'], 1)
    eq(len(cart['items']), 2)
    cart = add(black['id'], 1, {**vehicle, 'year': 2017})
    eq(len(cart['items']), 3)
    eq(cart['subtotal'], 150)
    eq(cart['shipping'], None)
    eq(cart['total'], None)
    eq(cart['checkout_available'], False)
    eq(next(line for line in cart['items'] if line['cart_item_id'] == first)['selected_vehicle']['has_camera'], False)
    request('/cart', 'POST', {'product_id': product, 'variant_id': black['id'], 'quantity': 1}, guest, status=409)
    request('/cart', 'PUT', {'product_id': product, 'quantity': 1}, guest, status=409)
    other = next(line['cart_item_id'] for line in cart['items'] if line['variant_id'] == black['id'] and line['cart_item_id'] != first)
    cart = request('/cart/' + product + '?cart_item_id=' + other, 'DELETE', headers=guest)
    eq(len(cart['items']), 2)
    eq(next(line for line in cart['items'] if line['cart_item_id'] == first)['quantity'], 2)
    stranger = {'X-Session-Id': 'synthetic_probe_stranger_' + marker}
    request('/cart/' + product + '?cart_item_id=' + first, 'DELETE', headers=stranger)
    eq(len(request('/cart', headers=guest)['items']), 2)
    customer = {**guest, 'Authorization': 'Bearer customer-test-token'}
    cart = request('/cart/claim', 'POST', headers=customer)
    eq(len(cart['items']), 2)
    cart = request('/cart/claim', 'POST', headers=customer)
    eq(len(cart['items']), 2)
    request('/create-checkout-session', 'POST', headers=customer, status=409)
    # Retirement preserves a removable exact line; the base price is not substituted.
    request('/admin/commerce/variant/' + black['id'], 'PUT',
            {'data': {**base, 'status': 'archived'}, 'expected_updated_at': black['updated_at']}, HEADERS)
    cart = request('/cart', headers=customer)
    retired = next(line for line in cart['items'] if line['variant_id'] == black['id'])
    eq(retired['price_cents'], 3000)
    eq(retired['purchase_available'], False)
    cart = request('/cart/' + product + '?cart_item_id=' + retired['cart_item_id'], 'DELETE', headers=customer)
    eq(len(cart['items']), 1)
    eq(sql('select price_cents from products where id=$1', [product])[0]['price_cents'], 1000)
    eq(sql('select count(*)::integer n from orders')[0]['n'], before_orders)
    print(json.dumps({'result': 'passed', 'checks': checks, 'path': 'HTTP API -> local SQL bridge -> PostgreSQL/PGlite',
                      'real_auth': False, 'real_postgrest': False, 'payment_test': 'not run; variant checkout intentionally gated',
                      'production_access': False, 'synthetic_marker': marker}))


if __name__ == '__main__':
    main()
