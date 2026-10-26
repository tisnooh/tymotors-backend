"""Opt-in REAL Stripe sandbox transport over a disposable loopback database.

Run only under an operator-controlled test process. Requires STRIPE_SECRET_KEY
(sk_test_, rk_test_ or official CLI rkcs_test_) and STRIPE_WEBHOOK_SECRET in
process memory. This module never provisions an account, prints credentials,
sends email, charges live money or transmits anything to a supplier/HyperSKU.

The operator manages the disposable database on 127.0.0.1:8766 and the Stripe
CLI forwarding signed sandbox events to /api/stripe/webhook. Creating a real
sandbox Checkout Session is NOT evidence of a completed sandbox payment.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import logging
import os
import re
from urllib.parse import urlsplit
from uuid import UUID

# Do not load this checkout's .env or inherit real database/email credentials.
# These values affect this explicitly launched QA process only. Keep the two
# operator-provided Stripe env values unprinted and unmodified.
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
for _name, _value in {
    'ENVIRONMENT': 'test', 'STRIPE_MODE': 'test',
    'SUPABASE_URL': 'https://sandbox-fixture.invalid.supabase.co',
    'SUPABASE_PUBLISHABLE_KEY': 'fixture-public-not-a-credential',
    'SUPABASE_SECRET_KEY': 'fixture-service-not-a-credential',
    'SUPABASE_SERVICE_ROLE_KEY': 'fixture-service-not-a-credential',
    'SITE_URL': 'http://127.0.0.1:8765', 'FRONTEND_URL': 'http://127.0.0.1:8765',
    'CORS_ORIGINS': 'http://127.0.0.1:8765', 'CORS_ORIGIN_REGEX': '',
    'EMAIL_ENABLED': 'false', 'EMAIL_PROVIDER': 'brevo', 'BREVO_API_KEY': '',
    'SMTP_PASSWORD': '', 'SMTP_USERNAME': '', 'CLOUDINARY_URL': '',
    'CLOUDINARY_API_KEY': '', 'CLOUDINARY_API_SECRET': '',
}.items():
    os.environ[_name] = _value
del _name, _value

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
import uvicorn

from tests.serve_admin_fixture import Database, server
from tests.stripe_sandbox_browser_scope import BOOTSTRAP_HTML, BOOTSTRAP_JS, sandbox_scope
from app.commerce_payment_service import CommercePaymentError, CommerceTestPayments, TestStripeGateway
from app.commerce_checkout_events import validate_checkout_session

FIXTURE_NAME = 'real_stripe_sandbox_disposable_database'


def _dict(value):
    return (value.to_dict() if hasattr(value, 'to_dict') else
            value.to_dict_recursive() if hasattr(value, 'to_dict_recursive') else value)


def checked_checkout_url(value):
    """Redirect only to the exact Stripe-hosted test Checkout origin."""
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise CommercePaymentError('sandbox_checkout_url_missing')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname != 'checkout.stripe.com'
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or not parsed.path.startswith('/c/pay/cs_test_') or '\\' in value):
            raise ValueError
    except ValueError:
        raise CommercePaymentError('sandbox_checkout_url_invalid') from None
    return value


async def _assert_disposable_database():
    # The bridge itself is always literal loopback, never an environment URL.
    rows = await Database().query("select id from products where sku='TEST-001' and status='active'")
    if len(rows) != 1:
        raise RuntimeError('disposable_fixture_required')


@asynccontextmanager
async def sandbox_lifespan(_):
    key = os.environ.get('STRIPE_SECRET_KEY', '')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    if not re.fullmatch(r'(sk|rk|rkcs)_test_[A-Za-z0-9_]+', key):
        raise RuntimeError('operator_test_credentials_required')
    if not re.fullmatch(r'whsec_[A-Za-z0-9]{16,512}', webhook_secret):
        raise RuntimeError('operator_webhook_signing_secret_required')
    await _assert_disposable_database()
    gateway = TestStripeGateway(key)
    server.settings = replace(server.settings, environment='test',
        frontend_url='http://127.0.0.1:8765', stripe_mode='test',
        stripe_secret_key=key, stripe_webhook_secret=webhook_secret,
        email_enabled=False, brevo_api_key='', smtp_password='', smtp_username='')
    # Quoted webhooks use this only through CommerceTestPayments; all legacy
    # payment/email routes are blocked by the process-only allowlist below.
    server.stripe_client = gateway
    server.app.state.sandbox_gateway = gateway
    yield


server.app.router.lifespan_context = sandbox_lifespan
# Importing the database fixture registers a simulated provider endpoint.
# Remove it: this process must never be mistaken for fake transport success.
server.app.router.routes[:] = [route for route in server.app.router.routes
    if getattr(route, 'path', None) != '/qa-payment-attempt/{attempt_id}']


async def _no_email(*_args, **_kwargs):
    raise RuntimeError('email_delivery_forbidden_in_sandbox_fixture')


server.email_service.send = _no_email
server.email_service.retry = _no_email
server._send_order_email = _no_email


@server.app.middleware('http')
async def sandbox_only_boundary(request: Request, call_next):
    path = request.url.path
    scope=sandbox_scope(request.client.host if request.client else None,path,request.method,
        os.environ.get('PHOENIX_STRIPE_BROWSER_CART')=='explicit-test-only')
    if scope=='forbidden':
        return JSONResponse({'detail': 'Loopback QA process only'}, status_code=403)
    if scope=='identity':
        return JSONResponse({'fixture': FIXTURE_NAME, 'is_test': True,
            'database': 'disposable_loopback', 'provider_transport': 'real_stripe_sdk',
            'payment_completed': False, 'emails_enabled': False})
    if scope=='disabled':
        return JSONResponse({'detail':'Browser cart fixture not enabled'},status_code=404)
    if scope=='bootstrap_html':return HTMLResponse(BOOTSTRAP_HTML)
    if scope=='bootstrap_js':return Response(BOOTSTRAP_JS,media_type='application/javascript')
    if path == '/api/stripe/webhook':
        # Never let a real sandbox event enter legacy order/email processing.
        # Stripe SDK still verifies the untouched raw body in the actual route.
        try:
            body = await request.body()
            if len(body) > 1024 * 1024:
                raise ValueError
            event = json.loads(body)
            metadata = event.get('data', {}).get('object', {}).get('metadata') or {}
            if event.get('livemode') is not False or not metadata.get('attempt_id') or not metadata.get('quote_id'):
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            return JSONResponse({'detail': 'Only quoted sandbox events accepted'}, status_code=400)
    return await call_next(request)


@server.app.post('/qa-stripe-payment/{attempt_id}', include_in_schema=False)
async def real_sandbox_checkout(attempt_id: UUID, actor=Depends(server.require_admin)):
    """Explicit admin-only real SDK operation for one synthetic pending order.

    The service persists/claims the existing key and frozen parameters. A retry
    re-reads its already-bound session rather than creating a second one.
    Unknown/unbound claims require inspection; this fixture never auto-retries.
    """
    gateway = server.app.state.sandbox_gateway
    payments = CommerceTestPayments(server.db, gateway)
    try:
        attempt, order = await payments._context(str(attempt_id))
        lines = await server.db.select('commerce_order_lines', params={'order_id': 'eq.' + order['id']})
        if not lines or any(not str((line.get('line_snapshot') or {}).get('sku', '')).startswith('SANDBOX-SYNTHETIC-') for line in lines):
            raise CommercePaymentError('synthetic_order_required')
        if order.get('payment_status') != 'unpaid':
            raise CommercePaymentError('sandbox_order_not_unpaid')
        if attempt['state'] == 'ready' and not attempt.get('session_id'):
            await payments.create_session(actor['id'], str(attempt_id))
            attempt, order = await payments._context(str(attempt_id))
        if not attempt.get('session_id') or not attempt['session_id'].startswith('cs_test_'):
            raise CommercePaymentError('sandbox_attempt_requires_inspection')
        session = _dict(await gateway.client.v1.checkout.sessions.retrieve_async(attempt['session_id']))
        validate_checkout_session(session, attempt, order)
        if session.get('status') != 'open' or session.get('payment_status') != 'unpaid':
            raise CommercePaymentError('sandbox_session_not_open_unpaid')
        return {'attempt_id': str(attempt_id), 'order_id': order['id'],
            'session_id': session['id'], 'is_test': True,
            'provider_transport': 'real_stripe_sdk', 'payment_completed': False,
            'checkout_url': checked_checkout_url(session.get('url'))}
    except Exception as error:
        # Do not print SDK exceptions: request/response details can contain PII
        # or provider diagnostic data. Unknown state is retained by the service.
        diagnostic = {'code': 'sandbox_checkout_requires_inspection', 'error_type': type(error).__name__}
        # SDK codes/parameter NAMES are safe diagnostics; never expose messages,
        # request headers, supplied values or the provider response payload.
        for field in ('code', 'param'):
            value = getattr(error, field, None)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,120}', value):
                diagnostic['provider_' + field] = value
        if isinstance(error, CommercePaymentError):
            value = str(error)
            if re.fullmatch(r'[a-z_]{1,120}', value): diagnostic['business_code'] = value
        raise HTTPException(409, diagnostic) from None


if __name__ == '__main__':
    for logger_name in ('httpx', 'httpcore', 'stripe', 'stripe._http_client'):
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)
    uvicorn.run(server.app, host='127.0.0.1', port=8765, log_level='warning', access_log=False)
