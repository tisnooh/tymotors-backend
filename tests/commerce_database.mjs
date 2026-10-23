// Real disposable PostgreSQL/PGlite. No hosted database, secrets, installation or network.
import { readFile, access } from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for (const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),
                  new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),
                  new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url)]) {
  try { await access(url); runtime=url.href; break; } catch {}
}
if (!runtime) throw new Error('Existing PGlite runtime missing; no dependency is installed automatically');
const { PGlite }=await import(runtime);
const db=new PGlite();
let checks=0;
const one=async(sql,params=[]) => (await db.query(sql,params)).rows[0];
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fails=async(sql,params=[],pattern=/./)=>{await assert.rejects(db.query(sql,params),pattern);checks++;};
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
    create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to anon,authenticated,service_role; grant execute on function auth.uid() to anon,authenticated,service_role;`);
  const migrations=[
    '202608240001_initial_ecommerce.sql','20260911071309_admin_backoffice.sql','20260911120652_admin_backoffice_hardening.sql',
    '20260912165642_complete_email_system.sql','20260912211934_email_advisor_hardening.sql',
    '20261011221114_supplier_fulfillment_workflow.sql','20261011222034_supplier_fulfillment_indexes.sql',
    '20261012042643_supplier_link_refresh.sql','20261012115851_checkout_customer_phone.sql','20261012120138_supplier_directory.sql',
    '20261012163951_withdrawal_receipts.sql','20261012184823_enforce_active_auth_session.sql','20261013063630_sandbox_catalog_orders.sql',
    '20261023132803_commerce_foundation.sql'];
  for (const file of migrations) {
    let sql=await readFile(new URL('../supabase/migrations/'+file,import.meta.url),'utf8');
    sql=sql.replace('create extension if not exists pgcrypto;','-- gen_random_uuid built into PostgreSQL/PGlite');
    await db.exec(sql);
  }
  const tables=['commerce_agents','product_variants','supplier_offers','shipping_rates','variant_compatibilities'];
  for(const table of tables) eq((await one('select count(*)::integer n from '+table)).n,0);
  const admin='10000000-0000-4000-8000-000000000001', customer='10000000-0000-4000-8000-000000000002';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')",[admin,customer]);
  await db.query("update profiles set role='admin' where id=$1",[admin]);
  const category=(await one("insert into categories(slug,name) values('commerce-test','Commerce') returning id")).id;
  const brand=(await one("insert into brands(slug,name) values('commerce-test','Commerce') returning id")).id;
  async function product(sku){return (await one("insert into products(slug,sku,name,description,category_id,price_cents,stock) values(lower($1),$1,'Draft product','Disposable commerce fixture only',$2,10000,0) returning id",[sku,category])).id;}
  const p1=await product('COM-1'),p2=await product('COM-2');
  async function rule(product,state='unverified'){return (await one("insert into product_compatibilities(product_id,brand_id,chassis,verification_state) values($1,$2,'W205',$3) returning id",[product,brand,state])).id;}
  const r1=await rule(p1,'verified'),r2=await rule(p2,'verified'),rUnverified=await rule(p1);
  const supplier=(await one("insert into suppliers(name,url) values('Test supplier','https://supplier.example.test') returning id")).id;
  const saveSQL='select admin_save_commerce_record($1,$2,$3,$4,$5) data';
  const save=async(kind,data,id=null,expected=null)=>(await one(saveSQL,[admin,kind,id,data,expected])).data;
  const vInput={product_id:p1,sku:'VAR-1',name:'Variant one',price_cents:10000};
  const agent=await save('agent',{name:'Research agent',role:'sourcing',profile_id:admin});
  eq(agent.is_active,false);
  const v=await save('variant',vInput);
  eq(v.price_cents,10000);eq(v.sale_tax_bps,null);eq(v.stock,0);eq(v.is_verified,false);eq(v.status,'draft');eq(v.compatibility_ids,[]);
  await fails(saveSQL,[customer,'variant',null,vInput,null],/Admin role required/);
  await fails(saveSQL,[admin,'bogus',null,{},null],/Unknown commerce record kind/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-ID',id:customer},null],/Unknown or immutable commerce field/);
  await fails(saveSQL,[admin,'variant',null,vInput,null],/unique/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-TAX',sale_tax_bps:10001},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-STOCK',stock:-1},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-STOCK-HIGH',stock:100001},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-PRICE-HIGH',price_cents:2000000001},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-PROOF',evidence_ref:'x'.repeat(1001)},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-ATTR',attributes:{nested:{foo:'bar'}}},null],/Invalid variant attributes/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-EVIDENCE',status:'active',is_verified:true},null],/check constraint/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-RULE',compatibility_ids:[r2]},null],/same product/);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'BAD-UNVERIFIED',status:'active',is_verified:true,evidence_ref:'fixture only',compatibility_ids:[rUnverified]},null],/verified compatibility/);
  const active=await save('variant',{...vInput,sku:'ACTIVE',status:'active',is_verified:true,is_default:true,evidence_ref:'fixture only',compatibility_ids:[r1]});
  eq(active.compatibility_ids,[r1]);
  await fails(saveSQL,[admin,'variant',null,{...vInput,sku:'ACTIVE-2',status:'active',is_verified:true,is_default:true,evidence_ref:'fixture only',compatibility_ids:[r1]},null],/unique/);
  await fails(saveSQL,[admin,'variant',v.id,{product_id:p2},v.updated_at],/immutable/);
  await fails(saveSQL,[admin,'variant',v.id,{name:'Stale'},null],/changed; reload/);
  const edited=await save('variant',{name:'Edited'},v.id,v.updated_at);
  eq(edited.name,'Edited');assert.notEqual(edited.updated_at,v.updated_at);checks++;
  await fails(saveSQL,[admin,'variant',v.id,{name:'Stale overwrite'},v.updated_at],/changed; reload/);
  const auditBefore=(await one('select count(*)::integer n from admin_audit')).n;
  await fails(saveSQL,[admin,'variant',v.id,{name:'Rollback me',compatibility_ids:[r2]},edited.updated_at],/same product/);
  eq((await one('select name from product_variants where id=$1',[v.id])).name,'Edited');
  eq((await one('select count(*)::integer n from admin_audit')).n,auditBefore);
  await fails('update product_compatibilities set verification_state=$2 where id=$1',[r1,'unverified'],/would become invalid/);
  await fails('update product_compatibilities set product_id=$2 where id=$1',[r1,p2],/would become invalid/);
  await fails('delete from variant_compatibilities where variant_id=$1',[active.id],/verified compatibility/);
  const offerInput={variant_id:v.id,supplier_id:supplier,supplier_sku:'SUP-1',supplier_variant:'Gloss black',url:'https://supplier.example.test/item',responsible_agent_id:agent.id};
  const offer=await save('offer',offerInput);
  eq(offer.unit_cost_cents,null);eq(offer.recoverable_tax_cents,null);eq(offer.availability,'unknown');eq(offer.moq,1);
  for(const data of [{unit_cost_cents:-1},{unit_cost_cents:2000000001},{moq:0},{moq:1000001},{currency:'BTC'},{recoverable_tax_cents:1},{unit_cost_cents:100,recoverable_tax_cents:101},{fx_rate:0},{fx_rate:1000001},{available_quantity:-1},{available_quantity:1000001},{preparation_days_min:731},{preparation_days_min:5,preparation_days_max:3},{verification_state:'verified'},{evidence_ref:'x'.repeat(1001)},{supplier_sku:''},{supplier_variant:''},{url:'javascript:alert(1)'},{url:'https://name:password@supplier.example.test/item'}])
    await fails(saveSQL,[admin,'offer',null,{...offerInput,...data},null],/check constraint/);
  const primary=await save('offer',{...offerInput,is_primary:true,unit_cost_cents:0,recoverable_tax_cents:0,verification_state:'verified',evidence_ref:'fixture evidence'});
  eq(primary.unit_cost_cents,0);eq(primary.recoverable_tax_cents,0);
  await fails(saveSQL,[admin,'offer',null,{...offerInput,supplier_sku:null},null],/not-null/);
  await fails(saveSQL,[admin,'offer',null,{...offerInput,supplier_variant:null},null],/not-null/);
  await fails(saveSQL,[admin,'offer',null,{...offerInput,is_primary:true},null],/unique/);
  await fails(saveSQL,[admin,'offer',offer.id,{variant_id:active.id},offer.updated_at],/immutable/);
  const rateInput={offer_id:offer.id,country:'FR',mode:'Tracked',max_quantity:20};
  const rate=await save('shipping_rate',rateInput);
  eq(rate.shipping_cost_cents,null);eq(rate.postal_prefix,'');eq(rate.min_quantity,1);eq(rate.goods_tax_bps,null);eq(rate.shipping_tax_bps,null);
  for(const data of [{country:'fr'},{postal_prefix:'*'},{postal_prefix:'123456789012345678901'},{min_quantity:0},{max_quantity:1000001},{min_quantity:3,max_quantity:2},{currency:'USD'},{shipping_cost_cents:-1},{shipping_cost_cents:2000000001},{shipping_recoverable_tax_cents:1},{shipping_cost_cents:100,shipping_recoverable_tax_cents:101},{customer_shipping_cents:-1},{agent_fee_cents:-1},{import_duty_cents:-1},{nonrecoverable_tax_cents:-1},{other_cost_cents:-1},{delivery_days_min:731},{delivery_days_min:5,delivery_days_max:1},{verification_state:'verified'},{goods_tax_bps:-1},{shipping_tax_bps:10001}])
    await fails(saveSQL,[admin,'shipping_rate',null,{...rateInput,...data},null],/check constraint/);
  const free=await save('shipping_rate',{...rateInput,shipping_cost_cents:0,shipping_recoverable_tax_cents:0,customer_shipping_cents:0,agent_fee_cents:0,import_duty_cents:0,nonrecoverable_tax_cents:0,other_cost_cents:0,verification_state:'verified',evidence_ref:'fixture only'});
  eq(free.shipping_cost_cents,0);
  await fails(saveSQL,[admin,'shipping_rate',null,{...rateInput,max_quantity:null},null],/not-null/);
  const taxed=await save('shipping_rate',{...rateInput,goods_tax_bps:2000,shipping_tax_bps:0});
  eq(taxed.goods_tax_bps,2000);eq(taxed.shipping_tax_bps,0);
  await fails(saveSQL,[admin,'shipping_rate',rate.id,{offer_id:primary.id},rate.updated_at],/immutable/);
  for(const table of tables) {
    eq((await one('select relrowsecurity from pg_class where oid=$1::regclass',['public.'+table])).relrowsecurity,true);
    for(const role of ['anon','authenticated']) {
      for(const privilege of ['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER'])
        eq((await one('select has_table_privilege($1,$2,$3) allowed',[role,'public.'+table,privilege])).allowed,false);
      await db.exec('begin; set local role '+role);
      await fails('select * from '+table,[],/permission denied/);await db.exec('rollback');
    }
  }
  for(const role of ['anon','authenticated']) {
    eq((await one("select has_function_privilege($1,'public.admin_save_commerce_record(uuid,text,uuid,jsonb,timestamptz)','execute') allowed",[role])).allowed,false);
  }
  eq((await one("select has_function_privilege('service_role','public.admin_save_commerce_record(uuid,text,uuid,jsonb,timestamptz)','execute') allowed")).allowed,true);
  await db.exec('begin; set local role service_role');
  await fails(saveSQL,[customer,'agent',null,{profile_id:customer,name:'Not admin',role:'orders'},null],/Admin role required/);
  await db.exec('rollback; begin; set local role service_role');
  const viaService=(await one(saveSQL,[admin,'agent',null,{profile_id:admin,name:'Service role test',role:'orders'},null])).data;
  eq(viaService.role,'orders');await db.exec('commit');
  // The legacy product editor deletes rules. It must fail safely rather than
  // silently cascade away a commerce association or its verified provenance.
  await fails('delete from product_compatibilities where product_id=$1',[p1],/foreign key/);
  eq((await one('select count(*)::integer n from variant_compatibilities where variant_id=$1',[active.id])).n,1);
  eq((await one("select count(*)::integer n from admin_audit where action='commerce.variant.save' and resource=$1",[v.id])).n,2);
  // No writes to existing catalogue pricing/inventory or customer commerce records.
  eq((await one('select stock,price_cents,status from products where id=$1',[p1])),{stock:0,price_cents:10000,status:'draft'});
  for(const table of ['orders','order_items','supplier_orders','supplier_order_items','inventory_movements']) eq((await one('select count(*)::integer n from '+table)).n,0);
  console.log(JSON.stringify({checks,engine:'PostgreSQL/PGlite',result:'passed',hostedDatabase:false}));
} catch(error) {
  console.error(JSON.stringify({result:'failed',checks,message:error.message,code:error.code,where:error.where,detail:error.detail}));
  process.exitCode=1;
} finally { await db.close(); }
