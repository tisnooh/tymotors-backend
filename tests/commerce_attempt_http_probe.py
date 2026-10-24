"""Loopback HTTP -> disposable PostgreSQL shadow reservations; no Stripe call.

Start admin_database.mjs --serve and python -m tests.serve_admin_fixture first.
Run --restore after restarting ONLY the API process while retaining that DB.
"""
import sys
from uuid import uuid4

from tests.commerce_http_probe import request, sql, save, eq, HEADERS, ADMIN
import tests.commerce_http_probe as probe


def restore():
    rows = sql("select a.* from commerce_checkout_attempts a join orders o on o.id=a.order_id "
               "where a.state='unknown' and exists(select 1 from order_items i where i.order_id=o.id "
               "and i.sku like 'ATTEMPT-HTTP-%') order by a.created_at desc limit 1")
    assert rows, 'This disposable probe must have created its unknown attempt first'
    attempt = rows[0]
    view = request('/admin/commerce/checkout-attempts/' + attempt['id'], headers=HEADERS)
    eq(view['state'], 'unknown')
    eq(view['requires_reconciliation'], True)
    eq(view['payment_available'], False)
    eq(int(sql("select sum(quantity) n from commerce_variant_reservations where attempt_id=$1 and state='held'", [attempt['id']])[0]['n']), 2)
    eq(int(sql('select stock from product_variants where id=(select variant_id from commerce_variant_reservations where attempt_id=$1)', [attempt['id']])[0]['stock']), 3)
    request('/admin/commerce/checkout-attempts/' + attempt['id'] + '/cancel-draft', 'POST', headers=HEADERS, status=409)
    print(f'{probe.checks} restore assertions passed; unknown state and test holds survived API restart.')


def main():
    marker = uuid4().hex[:10]
    product = sql("select id from products where sku='TEST-001' and status='active'")[0]['id']
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    # Only a disposable fixture URL; no asset request, file edit or real product.
    sql("update product_images set url='https://cdn.example.com/isolated-fixture.webp' where product_id=$1", [product])
    actor = save('agent', {'profile_id': ADMIN, 'name': 'Attempt fixture operator', 'role': 'orders', 'is_active': True})
    variant = save('variant', {'product_id': product, 'sku': 'ATTEMPT-HTTP-' + marker,
        'name': 'Synthetic scarce variant', 'price_cents': 3000, 'stock': 3, 'status': 'active',
        'is_verified': True, 'requires_vehicle': False, 'evidence_ref': 'local-synthetic-only'})
    offer = save('offer', {'variant_id': variant['id'], 'supplier_id': supplier,
        'supplier_sku': 'PRIVATE-ATTEMPT-' + marker, 'supplier_variant': 'Synthetic exact variant',
        'url': 'https://supplier.example.test/' + marker, 'verification_state': 'verified',
        'evidence_ref': 'local-synthetic-only', 'is_primary': True, 'availability': 'available',
        'available_quantity': 3, 'valid_until': '2099-01-01T00:00:00Z', 'unit_cost_cents': 1000,
        'recoverable_tax_cents': 0, 'currency': 'EUR', 'preparation_days_min': 1,
        'preparation_days_max': 2, 'responsible_agent_id': actor['id']})
    save('shipping_rate', {'offer_id': offer['id'], 'country': 'FR', 'mode': 'tracked', 'max_quantity': 3,
        'shipping_cost_cents': 0, 'shipping_recoverable_tax_cents': 0, 'customer_shipping_cents': 0,
        'goods_tax_bps': 0, 'shipping_tax_bps': 0, 'agent_fee_cents': 0, 'import_duty_cents': 0,
        'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0, 'verification_state': 'verified',
        'evidence_ref': 'local-synthetic-only', 'valid_until': '2099-01-01T00:00:00Z',
        'delivery_days_min': 3, 'delivery_days_max': 5})
    orders = []
    for number in range(3):
        guest = {'X-Session-Id': 'attempt_http_' + marker + '_' + str(number)}
        request('/cart', 'POST', {'product_id': product, 'variant_id': variant['id'], 'quantity': 2}, guest)
        quote = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
            'destination': {'name': 'Synthetic recipient', 'line1': '1 Synthetic street', 'city': 'Paris',
                            'country': 'FR', 'postal_code': '75001'}}, guest)
        orders.append(request('/admin/commerce/quotes/' + quote['quote_id'] + '/prepare-test-order', 'POST', headers=HEADERS))
    def prepare(order, status=200):
        return request('/admin/commerce/orders/' + order['order_id'] + '/checkout-attempt', 'POST', headers=HEADERS, status=status)
    first = prepare(orders[0])
    eq(first['state'], 'ready')
    eq(first['payment_available'], False)
    frozen = sql('select * from commerce_checkout_attempts where id=$1', [first['attempt_id']])[0]
    eq(frozen['params']['line_items'][0]['price_data']['unit_amount'], 3000)
    eq(frozen['params']['expires_at'], int(frozen['expires_at']))
    eq(frozen['params']['metadata']['order_id'], orders[0]['order_id'])
    eq(prepare(orders[0]), first)
    eq(sql('select * from commerce_checkout_attempts where id=$1', [first['attempt_id']])[0], frozen)
    prepare(orders[1], status=409)
    eq(int(sql('select count(*) n from commerce_checkout_attempts where order_id=$1', [orders[1]['order_id']])[0]['n']), 0)
    eq(int(sql('select stock from product_variants where id=$1', [variant['id']])[0]['stock']), 3)
    cancelled = request('/admin/commerce/checkout-attempts/' + first['attempt_id'] + '/cancel-draft', 'POST', headers=HEADERS)
    eq(cancelled['state'], 'cancelled')
    second = prepare(orders[1])
    eq(second['state'], 'ready')
    eq(int(sql("select sum(quantity) n from commerce_variant_reservations where variant_id=$1 and state='held'", [variant['id']])[0]['n']), 2)
    # Simulated worker claim/outcome only. No external create-session method.
    sql('select commerce_claim_checkout_attempt($1,$2)', [ADMIN, second['attempt_id']])
    sql("select commerce_checkout_unknown($1,$2,'provider_timeout')", [ADMIN, second['attempt_id']])
    unknown = request('/admin/commerce/checkout-attempts/' + second['attempt_id'], headers=HEADERS)
    eq(unknown['state'], 'unknown')
    eq(unknown['requires_reconciliation'], True)
    request('/admin/commerce/checkout-attempts/' + second['attempt_id'] + '/cancel-draft', 'POST', headers=HEADERS, status=409)
    prepare(orders[2], status=409)
    eq(int(sql('select stock from product_variants where id=$1', [variant['id']])[0]['stock']), 3)
    eq(int(sql('select available_quantity from supplier_offers where id=$1', [offer['id']])[0]['available_quantity']), 3)
    eq(int(sql('select count(*) n from supplier_orders where order_id in($1,$2,$3)', [row['order_id'] for row in orders])[0]['n']), 0)
    eq({row['payment_status'] for row in sql('select payment_status from orders where id in($1,$2,$3)', [row['order_id'] for row in orders])}, {'unpaid'})
    assert 'PRIVATE-ATTEMPT' not in str(first) and 'params' not in first and 'idempotency_key' not in first
    print(f'{probe.checks} HTTP/SQL attempt assertions passed; isolated test reservations only, no Stripe/payment/stock mutation.')


if __name__ == '__main__':
    restore() if '--restore' in sys.argv else main()
