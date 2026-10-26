"""Loopback API -> disposable SQL -> public tracking. No mail or provider calls."""
import json
from uuid import uuid4
from tests import commerce_http_probe as probe


def main():
    marker = uuid4().hex[:10]
    fixture = probe.sql("select id,status from products where sku='TEST-001'")
    assert len(fixture) == 1 and fixture[0]['status'] == 'active', 'Disposable fixture required'
    assert probe.request('/health') == {'status': 'ok'}

    def seed(is_test=False, paid=True):
        order = probe.sql("""insert into orders(order_number,subtotal_cents,total_cents,customer_email,is_test)
            values($1,1000,1000,'dispatch@example.com',$2) returning *""", ['TY-DISPATCH-' + uuid4().hex[:12].upper(), is_test])[0]
        probe.sql("""insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents)
            values($1,$2,'Fixture','test-product','TEST-001',1,1000)""", [order['id'], fixture[0]['id']])
        if paid:
            probe.sql("update orders set payment_status='paid',status='paid' where id=$1", [order['id']])
        return probe.sql('select * from orders where id=$1', [order['id']])[0]

    def payload(order, state='shipped', **changes):
        return {'expected_updated_at': order['updated_at'], 'fulfillment_status': state,
                'tracking_number': 'FIXTURE-' + marker, 'carrier': 'Fixture carrier',
                'tracking_url': 'https://carrier.example.test/track/' + marker, **changes}

    for order in [seed(is_test=True), seed(paid=False)]:
        path = '/admin/orders/' + order['id']
        probe.request(path, 'PUT', payload(order), probe.HEADERS, status=409)
        probe.eq(probe.sql('select * from orders where id=$1', [order['id']])[0], order)
        probe.eq(probe.sql("select count(*) n from order_tracking_events where order_id=$1 and event_key='order_shipped'", [order['id']])[0]['n'], 0)

    order = seed()
    path = '/admin/orders/' + order['id']
    probe.request(path, 'PUT', payload(order), status=401)
    result = probe.request(path, 'PUT', payload(order), probe.HEADERS)
    probe.eq(result['notification_kind'], 'order_shipped')
    replay = probe.request(path, 'PUT', payload(order), probe.HEADERS)
    probe.eq(replay['updated'], False)
    probe.eq(replay['notification_kind'], None)
    shipped = probe.sql('select * from orders where id=$1', [order['id']])[0]
    probe.eq(shipped['carrier'], 'Fixture carrier')
    probe.eq(shipped['tracking_url'], payload(order)['tracking_url'])
    probe.request(path, 'PUT', payload(order, 'delivered'), probe.HEADERS, status=409)
    probe.request(path, 'PUT', payload(shipped, tracking_number='REPLACED'), probe.HEADERS, status=409)
    probe.request(path, 'PUT', payload(shipped, 'delivered', tracking_number=None, carrier=None, tracking_url=None), probe.HEADERS)
    tracking = probe.request('/order-tracking', 'POST', {'order_number': order['order_number'], 'email': 'dispatch@example.com'})
    probe.eq(tracking['fulfillment_status'], 'delivered')
    probe.eq(tracking['carrier'], 'Fixture carrier')
    probe.eq(tracking['tracking_number'], 'FIXTURE-' + marker)
    probe.eq(tracking['tracking_url'], payload(order)['tracking_url'])
    events = [e for e in tracking['tracking_events'] if e['title'] in ('Commande expédiée', 'Commande livrée')]
    probe.eq(len(events), 2)
    assert all('metadata' not in e and 'order_id' not in e for e in events)
    assert any('manuellement' in e['description'] for e in events)
    probe.eq(probe.sql("select count(*) n from admin_audit where resource=$1 and action='order.update'", [order['id']])[0]['n'], 2)
    print(json.dumps({'result': 'passed', 'checks': probe.checks, 'transport': 'none',
                      'scope': 'loopback_synthetic_manual_dispatch_not_real_shipment'}))


if __name__ == '__main__':
    main()
