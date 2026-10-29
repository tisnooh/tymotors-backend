"""Offline signed Checkout lifecycle + actual disposable PostgreSQL assertions.

Never connects to Stripe, Supabase, email or a hosted service. The HTTP boundary
uses the real application/Stripe SDK with an explicitly in-memory DB adapter.
PostgreSQL transaction behavior is checked separately by admin_database.mjs.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
import server
from app.supabase_rest import SupabaseError


class MemoryDatabase:
    def __init__(self):
        self.tables = {'orders': [], 'order_items': [], 'stripe_events': [], 'order_tracking_events': []}
        self.payment_effects = 0

    async def select(self, table, *, params=None):
        rows = deepcopy(self.tables.get(table, []))
        for field, value in (params or {}).items():
            if field in {'select', 'limit', 'offset', 'order'}: continue
            if value == 'is.null': rows = [row for row in rows if row.get(field) is None]
            elif value.startswith('eq.'):
                def text(item):
                    return 'true' if item is True else 'false' if item is False else str(item)
                rows = [row for row in rows if text(row.get(field)) == value[3:]]
            elif value.startswith('in.('): rows = [row for row in rows if str(row.get(field)) in value[4:-1].split(',')]
            else: raise AssertionError('Unsupported offline fixture filter')
        return rows

    async def insert(self, table, payload, **kwargs):
        records = deepcopy(payload if isinstance(payload, list) else [payload])
        if table == 'orders':
            for row in records: row.update(id='10000000-0000-4000-8000-000000000009', payment_status='unpaid', status='pending')
        if table == 'stripe_events' and any(row['event_id'] == records[0]['event_id'] for row in self.tables[table]):
            raise SupabaseError(409, 'Duplicate fixture event')
        self.tables.setdefault(table, []).extend(records)
        return deepcopy(records)

    async def update(self, table, payload, *, params):
        for row in self.tables[table]:
            if all(str(row.get(key)) == value[3:] for key, value in params.items()): row.update(deepcopy(payload))
        return []

    async def rpc(self, function, payload):
        assert function == 'complete_paid_order'
        row = next(row for row in self.tables['orders'] if row['id'] == payload['p_order_id'])
        if row['payment_status'] != 'paid':
            self.payment_effects += 1
            row.update(payment_status='paid', status='paid', fulfillment_status='pending',
                       customer_email=payload['p_customer_email'], shipping_address=payload['p_shipping_address'])
        return True


def run_http_smoke():
    database = MemoryDatabase()
    secret = 'whsec_' + secrets.token_urlsafe(32)  # Ephemeral, never a provider credential.
    config = replace(server.settings, stripe_mode='test', environment='test',
        stripe_secret_key='rk_test_' + secrets.token_urlsafe(24), stripe_webhook_secret=secret,
        email_enabled=False, shipping_rate_cents=1500, free_shipping_threshold_cents=35000,
        shipping_countries=('FR',), frontend_url='http://localhost:3000', cors_origins=['http://localhost:3000'])
    checkout = AsyncMock(return_value=SimpleNamespace(id='cs_test_offline_fixture', url='http://localhost:3000/order-success'))
    client_sdk = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=checkout))))
    cart = {'id': 'offline_cart'}
    cart_view = {'currency': 'EUR', 'items': [{'id': 'offline_product', 'slug': 'offline', 'sku': 'OFFLINE',
        'name': 'Offline fixture', 'quantity': 2, 'status': 'active', 'stock': 5, 'price_cents': 1999,
        'currency': 'EUR', 'images': [], 'selected_vehicle': None}]}
    with patch.object(server, 'db', database), patch.object(server, 'settings', config), \
         patch.object(server, 'stripe_client', client_sdk), patch.object(server, '_cart_for', AsyncMock(return_value=cart)), \
         patch.object(server, '_cart_response', AsyncMock(return_value=cart_view)), \
         patch.object(server, '_send_order_email', AsyncMock()), patch.object(server, 'checkout_attempts', {}), \
         patch.object(server, 'tracking_attempts', {}):
        # No TestClient lifespan context: no external client initialization.
        client = TestClient(server.app)
        guest = {'X-Session-Id': 'offline_guest_capability_192_bits_fixture'}
        created = client.post('/api/create-checkout-session', headers=guest, json={'price': 1})
        assert created.status_code == 200, 'Offline Checkout creation failed'
        assert len(database.tables['orders']) == 1
        order = database.tables['orders'][0]
        assert order['total_cents'] == 5498 and order['payment_status'] == 'unpaid'
        lines = checkout.call_args.kwargs['params']['line_items']
        assert lines[0]['price_data']['unit_amount'] == 1999 and lines[1]['price_data']['unit_amount'] == 1500
        event = {'id': 'evt_offline_fixture', 'object': 'event', 'type': 'checkout.session.completed', 'livemode': False,
            'data': {'object': {'id': 'cs_test_offline_fixture', 'object': 'checkout.session', 'payment_status': 'paid',
                'metadata': {'order_id': order['id']}, 'client_reference_id': order['id'], 'amount_total': 5498,
                'currency': 'eur', 'payment_intent': 'pi_offline_fixture',
                'customer_details': {'email': 'fixture@example.com', 'name': 'Offline test', 'phone': '+33100000000'}}}}
        body = json.dumps(event).encode(); stamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), stamp.encode()+b'.'+body, hashlib.sha256).hexdigest()
        headers = {'Stripe-Signature': f't={stamp},v1={digest}', 'Content-Type': 'application/json'}
        assert client.post('/api/stripe/webhook', content=body).status_code == 400
        assert database.payment_effects == 0 and len(database.tables['stripe_events']) == 0
        assert client.post('/api/stripe/webhook', content=body, headers=headers).status_code == 200
        replay = client.post('/api/stripe/webhook', content=body, headers=headers)
        assert replay.json().get('duplicate') is True
        assert database.payment_effects == 1 and len(database.tables['orders']) == len(database.tables['stripe_events']) == 1
        state = client.get('/api/checkout-session/cs_test_offline_fixture', headers=guest)
        assert state.json()['paid'] is True and state.json()['total'] == 54.98
        tracking = client.post('/api/order-tracking', json={'order_number': order['order_number'], 'email': 'fixture@example.com'})
        assert tracking.status_code == 200 and 'customer_email' not in tracking.json()
        assert client.get('/api/checkout-session/cs_test_offline_fixture', headers={'X-Session-Id':'different_fixture_capability'}).status_code == 404
    return {'offline_http': 'passed', 'order_count': 1, 'event_count': 1, 'payment_effects': 1,
            'signature': 'real Stripe SDK', 'external_calls': 0}


def main():
    result = run_http_smoke()
    sql = subprocess.run(['node', 'tests/admin_database.mjs'], cwd=ROOT, capture_output=True, text=True, timeout=90)
    if sql.returncode:
        print('Disposable PostgreSQL checks unavailable/failed; install the documented test runtime. No end-to-end success claimed.')
        return 1
    result['postgres'] = json.loads(sql.stdout.strip().splitlines()[-1])
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
