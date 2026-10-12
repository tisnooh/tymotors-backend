"""Manual QA probe: only the disposable loopback database, never real Stripe."""
import hashlib
import hmac
import json
import time
import httpx

def query(sql, params=None):
    response = httpx.post('http://127.0.0.1:8766/query', json={'sql': sql, 'params': params or []})
    response.raise_for_status()
    return response.json()['rows']

def run():
    order = query("select * from orders where stripe_session_id like 'cs_test_fixture_%' order by created_at desc limit 1")[0]
    stock_before = query('select stock from products where id in (select product_id from order_items where order_id=$1)', [order['id']])[0]['stock']
    obj = {'id': order['stripe_session_id'], 'payment_status': 'paid', 'metadata': {'order_id': order['id']},
           'client_reference_id': order['id'], 'amount_total': order['total_cents'], 'currency': order['currency'].lower(),
           'payment_intent': 'pi_test_fixture', 'customer_details': {'email': 'qa@example.com', 'name': 'Fixture QA', 'phone': '+33100000000'}}
    event = {'id': 'evt_fixture_' + order['id'], 'type': 'checkout.session.completed', 'livemode': False, 'data': {'object': obj}}
    body = json.dumps(event).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(b'whsec_synthetic_fixture_not_a_credential', stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
    headers = {'Stripe-Signature': f't={stamp},v1={signature}', 'Content-Type': 'application/json'}
    with httpx.Client(base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/stripe/webhook', content=body).status_code == 400
        first = client.post('/api/stripe/webhook', content=body, headers=headers)
        assert first.status_code == 200, first.text
        replay = client.post('/api/stripe/webhook', content=body, headers=headers)
        assert replay.json().get('duplicate') is True, replay.text
        status = client.get('/api/checkout-session/'+order['stripe_session_id'], headers={'X-Session-Id': order['guest_session_id']})
        assert status.json()['paid'] is True, status.text
        tracking = client.post('/api/order-tracking', json={'email': 'qa@example.com', 'order_number': order['order_number']})
        assert tracking.status_code == 200, tracking.text
        assert 'customer_email' not in tracking.json()
    after = query('select stock from products where id in (select product_id from order_items where order_id=$1)', [order['id']])[0]['stock']
    assert after == stock_before - (0 if order['payment_status'] == 'paid' else 1)
    print('Isolated HTTP QA passed: unsigned rejected, signed paid, replay deduplicated, stock once, public tracking private.')
    print('Fixture order:', order['order_number'])

if __name__ == '__main__':
    run()
