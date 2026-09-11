"""Test-only bridge to a disposable PostgreSQL engine; binds only to loopback."""
from contextlib import asynccontextmanager
import re
import json
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

    async def get_user(self,token):
        identities={"admin-test-token":"10000000-0000-4000-8000-000000000001","customer-test-token":"10000000-0000-4000-8000-000000000002"}
        return {"id":identities[token]} if token in identities else None

fixture=Database()
for name in ("select","page","rpc","get_user"):
    setattr(server.db,name,getattr(fixture,name))

@asynccontextmanager
async def test_lifespan(_):
    yield
server.app.router.lifespan_context=test_lifespan
if __name__=="__main__":
    uvicorn.run(server.app,host="127.0.0.1",port=8765)
