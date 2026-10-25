"""Loopback FastAPI -> disposable PostgreSQL quotes; NOT Stripe/hosted QA.

Start admin_database.mjs --serve and python -m tests.serve_admin_fixture.
Fixtures and tokens belong only to that explicitly synthetic local environment.
"""
from uuid import uuid4

from tests.commerce_http_probe import request, sql, save, eq, HEADERS, ADMIN
import tests.commerce_http_probe as probe


def main():
    marker = uuid4().hex[:10]
    product = sql("select id from products where sku='TEST-001' and status='active'")[0]['id']
    sql("insert into commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,derivatives_use,product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at) select product_id,url,'verified','SYNTHETIC GRANT ONLY',true,true,true,'not_present',array['FR'],now()+interval '1 year',$2,now() from product_images where product_id=$1 on conflict(product_id,image_url) do nothing",[product,ADMIN])
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    before_orders = int(sql('select count(*) n from orders')[0]['n'])
    actor = save('agent', {'profile_id': ADMIN, 'name': 'Quote fixture operator', 'role': 'orders', 'is_active': True})
    guest = {'X-Session-Id': 'quote_probe_guest_' + marker}
    variants, rates, offers, offer_data = [], [], [], []
    for number, price in enumerate([3000, 6000]):
        variant = save('variant', {'product_id': product, 'sku': 'QUOTE-' + marker + '-' + str(number),
            'name': 'Synthetic quote variant ' + str(number), 'price_cents': price, 'stock': 10,
            'status': 'active', 'is_verified': True, 'requires_vehicle': False, 'evidence_ref': 'local-fixture'})
        variants.append(variant)
        terms = {'variant_id': variant['id'], 'supplier_id': supplier, 'supplier_sku': 'PRIVATE-SUPPLIER-' + marker,
            'supplier_variant': 'Synthetic exact variant ' + str(number), 'url': 'https://supplier.example.test/' + marker,
            'verification_state': 'verified', 'evidence_ref': 'local-synthetic-only', 'is_primary': True,
            'availability': 'available', 'available_quantity': 10, 'valid_until': '2099-01-01T00:00:00Z',
            'unit_cost_cents': 1000, 'recoverable_tax_cents': 0, 'currency': 'EUR',
            'preparation_days_min': 1, 'preparation_days_max': 2, 'responsible_agent_id': actor['id']}
        offer_data.append(terms)
        offer = save('offer', terms)
        offers.append(offer)
        rate_data = {'offer_id': offer['id'], 'country': 'FR', 'mode': 'tracked', 'max_quantity': 10,
            'shipping_cost_cents': 300, 'shipping_recoverable_tax_cents': 0, 'customer_shipping_cents': 500,
            'goods_tax_bps': 2000, 'shipping_tax_bps': 2000, 'agent_fee_cents': 0, 'import_duty_cents': 0,
            'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0, 'verification_state': 'verified',
            'evidence_ref': 'local-synthetic-only', 'valid_until': '2099-01-01T00:00:00Z',
            'delivery_days_min': 3, 'delivery_days_max': 5}
        rate = save('shipping_rate', rate_data)
        rates.append((rate, rate_data))
        request('/cart', 'POST', {'product_id': product, 'variant_id': variant['id'], 'quantity': 2}, guest)
    payload = {'request_key': str(uuid4()), 'mode': 'tracked', 'destination': {
        'name': 'Synthetic recipient', 'line1': '1 Local fixture street', 'city': 'Paris',
        'postal_code': '75001', 'country': 'FR'}}
    blocked = request('/cart/quote', 'POST', payload, guest, status=409)
    eq(blocked['detail']['code'], 'shipping_consolidation_unconfirmed')
    for rate, data in rates:
        request('/admin/commerce/shipping_rate/' + rate['id'], 'PUT', {
            'expected_updated_at': rate['updated_at'], 'data': {**data, 'multi_variant_policy': 'independent_parcels'}}, HEADERS)
    quoted = request('/cart/quote', 'POST', payload, guest)
    eq(quoted['subtotal_cents'], 18000)
    eq(quoted['shipping_cents'], 1000)
    eq(quoted['tax_cents'], 3166)
    eq(quoted['total_cents'], 19000)
    eq(quoted['checkout_available'], False)
    eq(quoted['requires_revalidation'], True)
    eq(len(quoted['items']), 2)
    assert 'PRIVATE-SUPPLIER' not in str(quoted) and 'landed_cost' not in str(quoted)
    quote_id = quoted['quote_id']
    eq(request('/cart/quote', 'POST', payload, guest), quoted)
    eq(request('/cart/quote/' + quote_id, headers=guest), quoted)
    request('/cart/quote/' + quote_id, headers={'X-Session-Id': 'quote_stranger_' + marker}, status=404)
    changed = request('/admin/commerce/offer/' + offers[0]['id'], 'PUT', {
        'data': {**offer_data[0], 'unit_cost_cents': 1100}, 'expected_updated_at': offers[0]['updated_at']}, HEADERS)
    # A stale source can still be restored as a snapshot, never as a new order.
    eq(request('/cart/quote', 'POST', payload, guest), quoted)
    request('/admin/commerce/quotes/' + quote_id + '/prepare-test-order', 'POST', headers=HEADERS, status=409)
    eq(int(sql('select count(*) n from orders')[0]['n']), before_orders)
    payload['request_key'] = str(uuid4())
    fresh = request('/cart/quote', 'POST', payload, guest)
    eq(request('/cart/quote/' + quote_id, headers=guest)['status'], 'superseded')
    order_path = '/admin/commerce/quotes/' + fresh['quote_id'] + '/prepare-test-order'
    request(order_path, 'POST', headers=guest, status=401)
    prepared = request(order_path, 'POST', headers=HEADERS)
    eq(prepared['is_test'], True)
    eq(request(order_path, 'POST', headers=HEADERS), prepared)
    eq(int(sql('select count(*) n from orders')[0]['n']), before_orders + 1)
    rows = sql('select * from commerce_order_lines where order_id=$1 order by source_cart_item_id', [prepared['order_id']])
    eq(len(rows), 2)
    eq({row['offer_snapshot']['supplier_sku'] for row in rows}, {'PRIVATE-SUPPLIER-' + marker})
    eq({row['agent_snapshot']['id'] for row in rows}, {actor['id']})
    order = sql('select * from orders where id=$1', [prepared['order_id']])[0]
    eq(order['total_cents'], 19000)
    eq(order['payment_status'], 'unpaid')
    eq(order['is_test'], True)
    eq(order['stripe_session_id'], None)
    eq(int(sql('select count(*) n from supplier_orders where order_id=$1', [prepared['order_id']])[0]['n']), 0)
    # Later commercial changes must not rewrite the saved supplier conditions.
    request('/admin/commerce/offer/' + changed['id'], 'PUT', {
        'data': {**offer_data[0], 'unit_cost_cents': 1200}, 'expected_updated_at': changed['updated_at']}, HEADERS)
    after = sql('select * from commerce_order_lines where order_id=$1 order by source_cart_item_id', [prepared['order_id']])
    eq(after, rows)
    eq(request(order_path, 'POST', headers=HEADERS), prepared)
    eq({row['stock'] for row in sql('select stock from product_variants where id in($1,$2)', [v['id'] for v in variants])}, {10})
    print(f'{probe.checks} HTTP/SQL quote assertions passed; pending test order only, no Stripe call or stock mutation.')


if __name__ == '__main__':
    main()
