"""Explicit local FAKE transport, installed only in the isolated probe process.

No Stripe API can be reached: HTTPX MockTransport implements a closed set of SDK
requests. Never import/install this from the production application.
"""
from copy import deepcopy
from dataclasses import replace
import json
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, HTTPException


PROFILES = [
    dict(reference='synthetic-context-production', mode='production', account_id='acct_SyntheticContextA',
         signing_secret='whsec_synthetic_context_production_a'),
    dict(reference='synthetic-context-other', mode='production', account_id='acct_SyntheticContextB',
         signing_secret='whsec_synthetic_context_production_b'),
    dict(reference='synthetic-context-sandbox', mode='sandbox', account_id='acct_SyntheticContextTest',
         signing_secret='whsec_synthetic_context_sandbox'),
]


def install(server):
    import app.commerce_customer_checkout_api as boundary
    original_httpx_client = boundary.stripe.HTTPXClient
    sessions, keys = {}, {}
    counters = {'account_reads': 0, 'create_calls': 0, 'retrieve_calls': 0}
    credentials = {}
    for profile in PROFILES:
        prefix = 'sk_test_' if profile['mode'] == 'sandbox' else 'sk_live_'
        credentials[prefix + 'synthetic_context_' + profile['account_id']] = profile

    def handle(request):
        key = request.headers.get('Authorization', '').removeprefix('Bearer ')
        profile = credentials.get(key)
        if request.url.host != 'api.stripe.com' or profile is None:
            return httpx.Response(401, json={'error': {'type': 'authentication_error', 'message': 'FAKE only'}})
        account = profile['account_id']
        if request.method == 'GET' and request.url.path == '/v1/account':
            counters['account_reads'] += 1
            return httpx.Response(200, json={'id': account, 'object': 'account', 'charges_enabled': True})
        if request.method == 'POST' and request.url.path == '/v1/checkout/sessions':
            counters['create_calls'] += 1
            params = parse_qs(request.content.decode())
            idem = request.headers['Idempotency-Key']
            identity = (account, idem)
            if identity in keys:
                if keys[identity][0] != params:
                    return httpx.Response(409, json={'error': {'message': 'FAKE idempotency mismatch'}})
                return httpx.Response(200, json=sessions[(account, keys[identity][1])])
            metadata = {name: params['metadata[' + name + ']'][0] for name in ('attempt_id', 'order_id', 'quote_id')}
            amount, index = 0, 0
            while 'line_items[' + str(index) + '][quantity]' in params:
                field = 'line_items[' + str(index) + ']'
                amount += int(params[field + '[quantity]'][0]) * int(params[field + '[price_data][unit_amount]'][0])
                index += 1
            shipping = int(params['shipping_options[0][shipping_rate_data][fixed_amount][amount]'][0])
            sid = ('cs_test_' if profile['mode'] == 'sandbox' else 'cs_live_') + metadata['attempt_id'].replace('-', '')
            response = {'id': sid, 'object': 'checkout.session', 'mode': 'payment',
                'livemode': profile['mode'] == 'production', 'status': 'open', 'payment_status': 'unpaid',
                'currency': 'eur', 'payment_intent': None, 'metadata': metadata,
                'client_reference_id': metadata['order_id'], 'expires_at': int(params['expires_at'][0]),
                'amount_subtotal': amount, 'amount_total': amount + shipping,
                'total_details': {'amount_discount': 0, 'amount_tax': 0, 'amount_shipping': shipping},
                'automatic_tax': {'enabled': False},
                'url': 'https://checkout.stripe.com/c/pay/' + sid + '#SYNTHETIC-NO-REAL-PAYMENT'}
            sessions[(account, sid)] = deepcopy(response)
            keys[identity] = (deepcopy(params), sid)
            return httpx.Response(200, json=response)
        if request.method == 'GET' and request.url.path.startswith('/v1/checkout/sessions/'):
            counters['retrieve_calls'] += 1
            response = sessions.get((account, request.url.path.rsplit('/', 1)[-1]))
            if response is not None:
                return httpx.Response(200, json=response)
        return httpx.Response(404, json={'error': {'type': 'invalid_request_error', 'message': 'FAKE unknown operation'}})

    class InterceptedHttpx:
        def AsyncClient(self, **kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

        def __getattr__(self, name):
            return getattr(httpx, name)

    @server.app.post('/qa-context-config', include_in_schema=False)
    async def configure(payload: dict, _actor=Depends(server.require_admin)):
        if set(payload) != {'profile_ref'}:
            raise HTTPException(400, 'Synthetic profile only')
        profile = next((p for p in PROFILES if p['reference'] == payload['profile_ref']), None)
        if profile is None:
            raise HTTPException(400, 'Unknown synthetic profile')
        key = next(key for key, value in credentials.items() if value is profile)
        server.settings = replace(server.settings, environment='production',
            frontend_url='https://shop.example.com', stripe_mode='test' if profile['mode'] == 'sandbox' else 'live',
            stripe_secret_key=key, stripe_checkout_profile=profile['reference'],
            stripe_webhook_profiles_json=json.dumps(PROFILES), stripe_legacy_webhook_mode='test')
        # Boundary owns and closes this real SDK HTTP wrapper. Transport is
        # always intercepted; no real credentials or external requests exist.
        boundary.stripe.HTTPXClient = lambda **_kwargs: original_httpx_client(
            timeout=20, _lib=InterceptedHttpx())
        return {'transport': 'FAKE', 'profile_ref': profile['reference'], **counters}

    @server.app.post('/qa-context-counters', include_in_schema=False)
    async def counts(_actor=Depends(server.require_admin)):
        return {'transport': 'FAKE', **counters}
