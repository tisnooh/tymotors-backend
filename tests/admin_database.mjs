// Disposable PostgreSQL engine: no hosted database or production fixtures.
import { PGlite } from '../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const db = new PGlite();
await db.exec(`
  create role anon; create role authenticated; create role service_role bypassrls;
  create schema auth;
  create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid
  $$;
  grant usage on schema auth to anon,authenticated,service_role;
  grant execute on function auth.uid() to anon,authenticated,service_role;
`);
const initial = await readFile(new URL('../supabase/migrations/202608240001_initial_ecommerce.sql',import.meta.url),'utf8');
await db.exec(initial.replace('create extension if not exists pgcrypto;','-- gen_random_uuid is built into this PostgreSQL engine.'));
await db.exec(await readFile(new URL('../supabase/migrations/20260911071309_admin_backoffice.sql',import.meta.url),'utf8'));
await db.exec(await readFile(new URL('../supabase/migrations/20260911120652_admin_backoffice_hardening.sql',import.meta.url),'utf8'));
let checks = 0;
const one = async (sql,params=[]) => (await db.query(sql,params)).rows[0];
async function rejects(sql,params,pattern) { await assert.rejects(db.query(sql,params),pattern); checks++; }
const admin = '10000000-0000-4000-8000-000000000001', customer = '10000000-0000-4000-8000-000000000002';
await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')",[admin,customer]);
await db.query("update public.profiles set role='admin' where id=$1",[admin]);
const cat=(await one("insert into categories(slug,name) values('test','Test') returning id")).id;
const brand=(await one("insert into brands(slug,name) values('bmw','BMW') returning id")).id;
const base = {slug:'test-product',sku:'TEST-001',name:'Test product',subtitle:'',description:'A complete test product description',category_id:cat,subcategory:'',price_cents:1000,compare_at_price_cents:null,currency:'EUR',stock:10,status:'active',is_verified:true,featured:false,badges:[],rating:null,review_count:0,specs:{},package_contents:['Product'],installation_difficulty:'easy',installation_minutes:null,tools_required:[],warranty_months:null,delivery_estimate:'5 days',legacy_compatible_brands:['bmw'],low_stock_threshold:3,tags:[]};
const supplier={supplier_name:'Fixture supplier',supplier_verified:true,cost_price_cents:300};
const rules=[{brand_id:brand,model_name:'Series 3',chassis:'F30',year_from:2012,year_to:2019,body_types:[],facelift:'unknown',required_trims:[],excluded_trims:[],verification_state:'verified'}];
const images=[{url:'https://example.test/product.png',display_order:0,image_type:'main'}];
const saveSQL='select admin_save_product($1,$2,$3,$4,$5,$6,$7) as id';
const saveParams=[admin,null,null,base,images,rules,supplier];
const product=(await one(saveSQL,saveParams)).id; checks++;
await rejects(saveSQL,[customer,null,null,{...base,slug:'forbidden',sku:'FORBIDDEN'},images,rules,supplier],/Admin role required/);
let p=await one('select * from products where id=$1',[product]);
await rejects(saveSQL,[admin,product,p.updated_at,{...base,name:'Should roll back'},images,[{...rules[0],brand_id:customer}],supplier],/foreign key/);
assert.equal((await one('select name from products where id=$1',[product])).name,'Test product');checks++;
await rejects('select admin_adjust_stock($1,$2,9,1,$3)',[admin,product,'correction'],/Stock changed/);
await rejects('select admin_adjust_stock($1,$2,10,-11,$3)',[admin,product,'correction'],/Insufficient stock/);
await one("select admin_adjust_stock($1,$2,10,2,'supplier_receipt')",[admin,product]);checks++;
assert.equal((await one('select stock from products where id=$1',[product])).stock,12);
async function order(quantity=2){
  const o=await one("insert into orders(order_number,subtotal_cents,total_cents,customer_email,currency) values(gen_random_uuid()::text,$1,$1,'client@example.test','EUR') returning *",[quantity*1000]);
  await db.query("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents) values($1,$2,'Test product','test-product','TEST-001',$3,1000)",[o.id,product,quantity]);
  return o;
}
const paid=await order();
const complete="select complete_paid_order($1,'pi_fixture','client@example.test','Client','{}','{}')";
await db.query(complete,[paid.id]);await db.query(complete,[paid.id]);
assert.equal((await one('select stock from products where id=$1',[product])).stock,10);checks++;
assert.equal((await one('select cost_price_cents from order_items where order_id=$1',[paid.id])).cost_price_cents,300);checks++;
let dash=(await one('select admin_dashboard($1) as data',[admin])).data;
assert.equal(dash.revenue.today.net,2000);assert.equal(dash.estimated_margin_cents,1400);checks++;
let paidRow = await one('select updated_at from orders where id=$1',[paid.id]);
await db.query("select admin_update_order($1,$2,'shipped','TRACK-TEST',$3)",[admin,paid.id,paidRow.updated_at]);
paidRow = await one('select updated_at from orders where id=$1',[paid.id]);
await rejects("select admin_update_order($1,$2,'processing','TRACK-TEST',$3)",[admin,paid.id,paidRow.updated_at],/Invalid transition/);
await db.query("select admin_update_order($1,$2,'delivered','TRACK-TEST',$3)",[admin,paid.id,paidRow.updated_at]);checks++;
await db.query("select record_order_refund('pi_fixture',500)");
assert.equal((await one('select payment_status from orders where id=$1',[paid.id])).payment_status,'paid');
dash=(await one('select admin_dashboard($1) as data',[admin])).data;assert.equal(dash.revenue.today.net,1500);checks++;
await db.query("select record_order_refund('pi_fixture',2000)");
await db.query(complete,[paid.id]);
assert.equal((await one('select stock from products where id=$1',[product])).stock,10);checks++;
const oversized=await order(20);
await rejects(complete,[oversized.id],/Insufficient stock/);
assert.equal((await one('select payment_status from orders where id=$1',[oversized.id])).payment_status,'unpaid');checks++;
const item=(await one('select id from order_items where order_id=$1',[paid.id])).id;
const ret=(await one("select admin_return_action($1,null,$2) as id",[admin,{order_item_id:item,quantity:1,reason:'Test return'}])).id;
await rejects("select admin_return_action($1,$2,$3)",[admin,ret,{restock:true}],/Receive and inspect/);
await db.query("select admin_return_action($1,$2,$3)",[admin,ret,{status:'accepted'}]);
await db.query("select admin_return_action($1,$2,$3)",[admin,ret,{status:'received'}]);
await db.query("select admin_return_action($1,$2,$3)",[admin,ret,{restock:true}]);
await rejects("select admin_return_action($1,$2,$3)",[admin,ret,{restock:true}],/Receive and inspect/);
assert.equal((await one('select stock from products where id=$1',[product])).stock,11);checks++;
await db.query("select admin_save_record($1,'settings',null,$2)",[admin,{shop_name:'Test shop',contact_email:'ops@example.test',low_stock_threshold:6}]);checks++;
const promo=(await one("select admin_save_record($1,'promotion',null,$2) as data",[admin,{code:'TEST10',active:true,discount_type:'percent',value:10,minimum_amount_cents:0,max_uses:1,product_ids:[product],category_ids:[]}])).data;
assert.ok(promo.id);
const discounted=await order();
assert.equal((await one("select apply_order_promotion($1,'TEST10') as data",[discounted.id])).data.discount_cents,200);checks++;
const extra=await order();
await rejects("select apply_order_promotion($1,'TEST10')",[extra.id],/usage limit/);
const perms=(await db.query(`select rolname,has_function_privilege(rolname,'public.admin_dashboard(uuid)','EXECUTE') as can_execute from pg_roles where rolname in ('anon','authenticated')`)).rows;
assert.equal(perms.every(r=>!r.can_execute),true);checks++;
await db.exec('begin; set local role authenticated;');
await db.query("select set_config('request.jwt.claim.sub',$1,true)",[customer]);
assert.equal((await db.query('select * from product_supplier_data')).rows.length,0);checks++;
await rejects("update profiles set role='admin' where id=$1",[customer],/permission denied/);
await db.exec('rollback');
await db.exec('begin; set local role anon;');
await rejects('select * from returns',[],/permission denied/);
await db.exec('rollback');
await db.query("select admin_save_record($1,'archive',$2,'{}')",[admin,product]);
assert.equal((await one('select status from products where id=$1',[product])).status,'archived');checks++;
console.log(JSON.stringify({checks,engine:'PostgreSQL/PGlite',result:'passed'}));
if (process.argv.includes('--serve')) {
  const { createServer } = await import('node:http');
  createServer(async (req,res) => {
    try {
      if (req.method !== 'POST' || req.url !== '/query') { res.writeHead(404).end(); return; }
      let body=''; for await(const chunk of req) body+=chunk;
      const {sql,params=[]}=JSON.parse(body);
      const result=await db.query(sql,params);
      res.setHeader('Content-Type','application/json');res.end(JSON.stringify(result));
    } catch(e) { res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({error:e.message})); }
  }).listen(8766,'127.0.0.1',()=>console.log('Disposable test database on 127.0.0.1:8766'));
} else await db.close();
