"""Test-only bridge to a disposable PostgreSQL engine; binds only to loopback."""
from contextlib import asynccontextmanager
import re
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
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
    server.settings = replace(server.settings, frontend_url='http://127.0.0.1:8765', stripe_mode='test', stripe_webhook_secret='whsec_synthetic_fixture_not_a_credential')
    async def checkout(params, options):
        order_id = params['metadata']['order_id']
        sid = 'cs_test_fixture_' + order_id
        return SimpleNamespace(id=sid, url=f'http://127.0.0.1:8765/order-success?session_id={sid}')
    server.stripe_client = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create_async=checkout))))
    yield
server.app.router.lifespan_context=test_lifespan

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
fixture_site=Path(__file__).resolve().parents[2]/'frontend'/'.browser-test-build'
server.app.mount('/qa-assets', StaticFiles(directory=fixture_site,check_dir=False),name='qa-assets')
@server.app.middleware('http')
async def fixture_html_policy(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith('/api/'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' https: data:; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'"
    return response
@server.app.get('/{path:path}', include_in_schema=False)
async def fixture_spa(path: str):
    return FileResponse(fixture_site/'index.html')
if __name__=="__main__":
    logging.getLogger('httpx').setLevel(logging.WARNING)
    uvicorn.run(server.app,host="127.0.0.1",port=8765,log_level='warning',access_log=False)
