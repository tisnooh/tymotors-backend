"""Receive real TEST refund signatures over an owned disposable loopback DB.

No Stripe API client or creation endpoint exists in this fixture. The original
production webhook function is reused, not a substitute financial implementation.
All hosted DB/email settings are disabled by the launching runner before import.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import json
import logging
import os
import re
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx
import stripe

from app.commerce_refund_events import normalize_test_refund_event


FIXTURE = 'real_stripe_refund_existing_test_payment_disposable_db'


class RefundDatabase:
    """Deliberately narrower than the general QA adapter. No hosted URL option."""
    async def query(self, statement, params=None):
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post('http://127.0.0.1:8766/query',
                json={'sql':statement,'params':params or []})
        if response.status_code != 200:
            raise RuntimeError('disposable_refund_database_query_failed')
        return response.json()['rows']

    async def select(self, table, *, params):
        if (table != 'orders' or set(params) - {'select','id','stripe_payment_intent_id','limit'}
                or not {'id','stripe_payment_intent_id'} & set(params)):
            raise ValueError('unexpected_refund_fixture_query')
        values, conditions = [], []
        for field in ('id','stripe_payment_intent_id'):
            if field in params:
                term=params[field]
                if not isinstance(term,str) or not term.startswith('eq.'):
                    raise ValueError('unexpected_refund_fixture_filter')
                values.append(term[3:]); conditions.append(field+'=$'+str(len(values)))
        return await self.query('select id,commerce_quote_id,is_test,stripe_payment_intent_id '
            'from public.orders where '+' and '.join(conditions)+' limit 2',values)

    async def rpc(self, name, payload):
        if name!='commerce_record_test_refund' or set(payload)!={'p_event'}:
            raise ValueError('unexpected_refund_fixture_rpc')
        return (await self.query('select public.commerce_record_test_refund($1::jsonb) result',
            [json.dumps(payload['p_event'])]))[0]['result']


def create_app(*, signing_secret, order_id, payment_intent_id, database=None):
    if (not isinstance(signing_secret,str) or not re.fullmatch(r'whsec_[A-Za-z0-9_]{16,512}',signing_secret)
            or not isinstance(payment_intent_id,str)
            or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,240}',payment_intent_id)):
        raise ValueError('explicit_refund_fixture_identity_required')
    try:
        if str(UUID(order_id))!=order_id or not UUID(order_id).int:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError('explicit_refund_fixture_identity_required') from None
    import server
    db=database or RefundDatabase()

    async def no_email(*args,**kwargs):
        raise RuntimeError('email_forbidden_in_refund_fixture')

    @asynccontextmanager
    async def lifespan(_app):
        fixtures=await db.query("select id from public.products where sku='TEST-001' and status='active'")
        rows=await db.select('orders',params={'id':'eq.'+order_id})
        if (len(fixtures)!=1 or len(rows)!=1 or rows[0].get('is_test') is not True
                or not rows[0].get('commerce_quote_id') or rows[0].get('stripe_payment_intent_id')!=payment_intent_id):
            raise RuntimeError('restored_disposable_test_order_required')
        previous=(server.db,server.settings,server.stripe_client,server._send_order_email)
        server.db=db
        server.settings=replace(server.settings,environment='test',stripe_mode='test',
            stripe_secret_key='',stripe_webhook_secret=signing_secret,email_enabled=False)
        server.stripe_client=None
        server._send_order_email=no_email
        try:
            yield
        finally:
            server.db,server.settings,server.stripe_client,server._send_order_email=previous

    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def scope(request:Request,call_next):
        if not request.client or request.client.host not in {'127.0.0.1','::1'}:
            return JSONResponse({'detail':'Loopback refund fixture only'},status_code=403)
        if request.url.path=='/qa-stripe-refund-status' and request.method=='GET':
            return JSONResponse({'fixture':FIXTURE,'is_test':True,'database':'disposable_loopback',
                'provider_transport':'real_webhook_signature_no_api_gateway',
                'new_payment_allowed':False,'email_allowed':False,'supplier_send_allowed':False})
        if request.url.path!='/api/stripe/webhook' or request.method!='POST':
            return JSONResponse({'detail':'Refund receipt endpoint only'},status_code=403)
        body=await request.body()
        try:
            if len(body)>1024*1024:
                raise ValueError
            # Authenticate BEFORE any DB lookup. The production handler checks
            # this untouched raw body again; no event is manufactured or signed here.
            event=stripe.Webhook.construct_event(body,request.headers.get('Stripe-Signature',''),signing_secret).to_dict()
            normalized=normalize_test_refund_event(event)
            if normalized['payment_intent_id']!=payment_intent_id:
                raise ValueError
        except (ValueError,stripe.SignatureVerificationError):
            return JSONResponse({'detail':'Bound signed sandbox refund required'},status_code=400)
        try:
            rows=await db.select('orders',params={'id':'eq.'+order_id,
                'stripe_payment_intent_id':'eq.'+payment_intent_id})
        except Exception:
            return JSONResponse({'detail':'Refund fixture context unavailable'},status_code=503)
        if len(rows)!=1 or rows[0].get('is_test') is not True or not rows[0].get('commerce_quote_id'):
            return JSONResponse({'detail':'Bound quoted test order required'},status_code=409)
        return await call_next(request)

    app.add_api_route('/api/stripe/webhook',server.stripe_webhook,methods=['POST'],include_in_schema=False)
    return app


def main():
    if os.environ.get('PHOENIX_STRIPE_REFUND_FIXTURE')!='explicit-test-only':
        raise RuntimeError('explicit_opt_in_required')
    if os.environ.get('STRIPE_SECRET_KEY') or os.environ.get('STRIPE_API_KEY'):
        raise RuntimeError('api_credentials_forbidden_in_receipt_process')
    app=create_app(signing_secret=os.environ.get('STRIPE_WEBHOOK_SECRET'),
        order_id=os.environ.get('PHOENIX_REFUND_ORDER_ID'),
        payment_intent_id=os.environ.get('PHOENIX_REFUND_PAYMENT_INTENT'))
    import uvicorn
    for name in ('httpx','httpcore','stripe','stripe._http_client'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning',access_log=False)


if __name__=='__main__':
    main()
