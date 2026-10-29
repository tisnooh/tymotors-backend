"""Test-only bridge to a disposable PostgreSQL engine; binds only to loopback."""
from contextlib import asynccontextmanager
import re
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import httpx
import uvicorn
import server
from app.supabase_rest import SupabaseError

class Database:
    async def query(self, sql, params=None):
        async with httpx.AsyncClient() as client:
            response = await client.post("http://127.0.0.1:8766/query", json={"sql":sql,"params":params or []})
        if response.status_code != 200: raise SupabaseError(409, response.json()["error"])
        return response.json()["rows"]

    def ident(self, value):
        if not re.fullmatch(r"[a-z_]+", value): raise ValueError("Test adapter invalid identifier")
        return '"' + value + '"'

    def where(self, params):
        clauses, values = [], []
        for key, value in params.items():
            if key in ("select","order","offset","limit"): continue
            if key == "or":
                parts=[]
                for condition in value[1:-1].split(","):
                    field,op,term=condition.split(".",2)
                    assert op=="ilike"
                    values.append(term.replace("*","%"))
                    parts.append(f"{self.ident(field)} ilike ${len(values)}")
                clauses.append("("+" or ".join(parts)+")");continue
            op,term=value.split(".",1)
            field=self.ident(key)
            if op=="in":
                terms=term[1:-1].split(",");slots=[]
                for t in terms: values.append(t);slots.append(f"${len(values)}")
                clauses.append(field+" in ("+",".join(slots)+")")
            elif op=="is": clauses.append(field+" is "+("null" if term=="null" else "true"))
            else:
                values.append(term.replace("*","%") if op=="ilike" else term)
                clauses.append(field+{"eq":"=","neq":"<>","ilike":" ilike "}[op]+f"${len(values)}")
        return (" where "+" and ".join(clauses) if clauses else ""),values

    async def select(self, table, *, params=None):
        params=params or {};where,values=self.where(params)
        cols=params.get("select","*")
        nested="(" in cols
        if nested: cols="*"
        elif cols!="*": cols=",".join(self.ident(c) for c in cols.split(","))
        query=f"select {cols} from public.{self.ident(table)}{where}"
        if params.get("order"):
            sorts=[]
            for part in params["order"].split(","):
                bits=part.split(".");sorts.append(self.ident(bits[0])+(" desc" if "desc" in bits else " asc")+(" nulls last" if "nullslast" in bits else ""))
            query+=" order by "+",".join(sorts)
        if "limit" in params: query+=" limit "+str(int(params["limit"]))
        if "offset" in params: query+=" offset "+str(int(params["offset"]))
        rows=await self.query(query,values)
        if nested and table=="returns":
            for row in rows:
                row["orders"]=(await self.select("orders",params={"id":"eq."+row["order_id"]}))[0]
                row["order_items"]=(await self.select("order_items",params={"id":"eq."+row["order_item_id"]}))[0]
        return rows

    async def page(self, table, *, params, page, limit):
        where,values=self.where(params)
        total=(await self.query(f"select count(*) n from public.{self.ident(table)}{where}",values))[0]["n"]
        total=int(total)
        return {"items":await self.select(table,params={**params,"offset":(page-1)*limit,"limit":limit}),
                "total":total,"page":page,"limit":limit,"pages":(total+limit-1)//limit}

    async def rpc(self, function, payload):
        values=[json.dumps(v) if isinstance(v,(dict,list)) else v for v in payload.values()]
        args=",".join(self.ident(k)+f"=>${i+1}" for i,k in enumerate(payload))
        return (await self.query(f"select public.{self.ident(function)}({args}) result",values))[0]["result"]

    async def insert(self, table, payload, *, upsert=False, on_conflict=None):
        records = payload if isinstance(payload, list) else [payload]
        rows = []
        for record in records:
            cols = ','.join(self.ident(k) for k in record)
            values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in record.values()]
            slots = ','.join(f'${i+1}' for i in range(len(values)))
            conflict = ''
            if upsert:
                keys = (on_conflict or 'id').split(',')
                target = ','.join(self.ident(key) for key in keys)
                updates = ','.join(f'{self.ident(key)}=excluded.{self.ident(key)}' for key in record if key not in keys)
                conflict = f' on conflict ({target}) do update set {updates}' if updates else f' on conflict ({target}) do nothing'
            rows.extend(await self.query(f'insert into public.{self.ident(table)}({cols}) values({slots}){conflict} returning *', values))
        return rows

    async def update(self, table, payload, *, params):
        where, filters = self.where(params)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in payload.values()]
        where = re.sub(r'\$(\d+)', lambda m: '$'+str(int(m[1])+len(values)), where)
        changes = ','.join(f'{self.ident(k)}=${i+1}' for i,k in enumerate(payload))
        return await self.query(f'update public.{self.ident(table)} set {changes}{where} returning *', values+filters)

    async def delete(self, table, *, params):
        where, values = self.where(params)
        return await self.query(f'delete from public.{self.ident(table)}{where} returning *', values)

    async def get_user(self,token):
        identities={"admin-test-token":"10000000-0000-4000-8000-000000000001","customer-test-token":"10000000-0000-4000-8000-000000000002"}
        return {"id":identities[token]} if token in identities else None

fixture=Database()
for name in ("select","page","rpc","get_user","insert","update","delete"):
    setattr(server.db,name,getattr(fixture,name))

@asynccontextmanager
async def test_lifespan(_):
    # Isolated fake Checkout transport, never Stripe or a hosted database.
    server.settings = replace(server.settings, frontend_url='http://127.0.0.1:8765', stripe_mode='test',
        stripe_secret_key='sk_test_synthetic_fixture_not_a_credential',
        stripe_webhook_secret='whsec_synthetic_fixture_not_a_credential', email_enabled=False)
    async def checkout(params, options):
        order_id = params['metadata']['order_id']
        sid = 'cs_test_fixture_' + order_id
        return SimpleNamespace(id=sid, url=f'http://127.0.0.1:8765/order-success?session_id={sid}')
    server.stripe_client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=checkout))))
    yield
server.app.router.lifespan_context=test_lifespan

from fastapi.responses import FileResponse
from fastapi import Depends
from app.commerce_payment_service import CommerceTestPayments, TestStripeGateway
from fastapi.staticfiles import StaticFiles
fixture_site=Path(__file__).resolve().parents[2]/'frontend'/'.browser-test-build'
server.app.mount('/qa-assets', StaticFiles(directory=fixture_site,check_dir=False),name='qa-assets')


class FixtureCustomerGateway(TestStripeGateway):
    """Actual test gateway instance, FAKE transport installed only by main().

    In particular, importing Database from this module in the real Stripe
    fixture MUST NOT patch any gateway factory or execute this class.
    """
    sessions = {}
    keys = {}
    create_calls = 0
    retrieve_calls = 0

    async def create(self, params, key):
        cls = type(self)
        cls.create_calls += 1
        if key in cls.keys:
            previous, session_id = cls.keys[key]
            if previous != params:
                raise ValueError('Synthetic idempotency parameter conflict')
            return deepcopy(cls.sessions[session_id])
        amount = sum(x['quantity']*x['price_data']['unit_amount'] for x in params['line_items'])
        shipping = params['shipping_options'][0]['shipping_rate_data']['fixed_amount']['amount']
        session_id = 'cs_test_customer_fixture_' + params['metadata']['attempt_id'].replace('-', '')
        session = {'object':'checkout.session','id':session_id,'mode':'payment','livemode':False,
            'currency':'eur','status':'open','payment_status':'unpaid','payment_intent':None,
            'client_reference_id':params['client_reference_id'],'metadata':deepcopy(params['metadata']),
            'expires_at':params['expires_at'],'amount_subtotal':amount,'amount_total':amount+shipping,
            'total_details':{'amount_discount':0,'amount_tax':0,'amount_shipping':shipping},
            'automatic_tax':{'enabled':False},
            'url':'https://checkout.stripe.com/c/pay/'+session_id+'#SYNTHETIC-NOT-A-REAL-CHECKOUT'}
        cls.sessions[session_id] = deepcopy(session)
        cls.keys[key] = (deepcopy(params), session_id)
        return deepcopy(session)

    async def retrieve(self, session_id):
        type(self).retrieve_calls += 1
        return deepcopy(type(self).sessions[session_id])


def enable_fake_customer_checkout():
    """Called only by this module's explicit main, never during an import."""
    import app.commerce_customer_checkout_api as boundary
    boundary.TestStripeGateway = FixtureCustomerGateway
    server.app.state.fake_customer_gateway_enabled = True

@server.app.post('/qa-payment-attempt/{attempt_id}')
async def simulated_provider_create(attempt_id: str, actor=Depends(server.require_admin)):
    """TEST PROCESS ONLY. Exercises real service with a fake SDK transport."""
    gateway = TestStripeGateway('sk_test_synthetic_fixture_not_a_credential')
    async def create(params, key):
        amount = sum(x['quantity']*x['price_data']['unit_amount'] for x in params['line_items'])
        shipping = params['shipping_options'][0]['shipping_rate_data']['fixed_amount']['amount']
        return {'object':'checkout.session','id':'cs_test_'+params['metadata']['attempt_id'].replace('-',''),
            'mode':'payment','livemode':False,'currency':'eur','status':'open','payment_status':'unpaid',
            'payment_intent':None,'client_reference_id':params['client_reference_id'],
            'metadata':params['metadata'],'expires_at':params['expires_at'],
            'amount_subtotal':amount,'amount_total':amount+shipping,
            'total_details':{'amount_discount':0,'amount_tax':0,'amount_shipping':shipping},
            'automatic_tax':{'enabled':False}}
    gateway.create = create
    return await CommerceTestPayments(server.db,gateway).create_session(actor['id'],attempt_id)
@server.app.middleware('http')
async def fixture_html_policy(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith('/api/'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' https: data:; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'"
    return response
@server.app.get('/qa-customer-payment-counters', include_in_schema=False)
async def customer_payment_counters(_actor=Depends(server.require_admin)):
    from fastapi import HTTPException
    if not getattr(server.app.state, 'fake_customer_gateway_enabled', False):
        raise HTTPException(404, 'Synthetic customer provider is not enabled')
    return {'transport':'FAKE','create_calls':FixtureCustomerGateway.create_calls,
        'retrieve_calls':FixtureCustomerGateway.retrieve_calls,'sessions':len(FixtureCustomerGateway.sessions)}
@server.app.get('/{path:path}', include_in_schema=False)
async def fixture_spa(path: str):
    if path in {'qa-delivery','qa-delivery-bootstrap.js'}:
        from fastapi import HTTPException
        from fastapi.responses import HTMLResponse, Response
        if not getattr(server.app.state,'fake_customer_gateway_enabled',False):
            raise HTTPException(404,'Synthetic customer fixture is not enabled')
        if path == 'qa-delivery':
            return HTMLResponse('<!doctype html><title>Synthetic delivery QA</title>'
                '<h1>Synthetic local cart only</h1><script src="/qa-delivery-bootstrap.js"></script>')
        return Response("localStorage.setItem('ty_session_id','delivery_browser_synthetic_guest');"
            "location.replace('/cart');",media_type='application/javascript')
    return FileResponse(fixture_site/'index.html')
if __name__=="__main__":
    enable_fake_customer_checkout()
    import os
    if os.environ.get('TYMOTORS_CONTEXT_FIXTURE') == '1':
        from tests.context_checkout_fixture import install
        install(server)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    uvicorn.run(server.app,host="127.0.0.1",port=8765,log_level='warning',access_log=False)
