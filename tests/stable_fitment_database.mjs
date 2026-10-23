// Disposable PostgreSQL/PGlite; no network, credentials, files written or production DB.
import {readFile,access} from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for (const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url)]) {
  try {await access(url);runtime=url.href;break;} catch {}
}
if(!runtime) throw new Error('Existing PGlite runtime required; no auto-install');
const {PGlite}=await import(runtime);const db=new PGlite();let checks=0;
const one=async(sql,args=[]) => (await db.query(sql,args)).rows[0];
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(sql,args,pattern)=>{await assert.rejects(db.query(sql,args),pattern);checks++;};
try {
  await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;create schema auth;
    create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated,service_role;grant execute on function auth.uid() to anon,authenticated,service_role;`);
  for(const name of ['202608240001_initial_ecommerce.sql','20260911071309_admin_backoffice.sql','20260911120652_admin_backoffice_hardening.sql',
    '20261011221114_supplier_fulfillment_workflow.sql','20261012120138_supplier_directory.sql','20261013063630_sandbox_catalog_orders.sql',
    '20261023132803_commerce_foundation.sql','20261023233030_commerce_stable_fitment_save.sql']) {
    const sql=(await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8')).replace('create extension if not exists pgcrypto;','-- builtin gen_random_uuid');await db.exec(sql);
  }
  const admin='10000000-0000-4000-8000-000000000001',customer='10000000-0000-4000-8000-000000000002';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')",[admin,customer]);
  await db.query("update profiles set role='admin' where id=$1",[admin]);
  const category=(await one("insert into categories(slug,name) values('fitment-test','Fitment') returning id")).id;
  const brand=(await one("insert into brands(slug,name) values('fitment-test','Fitment') returning id")).id;
  const base={slug:'fitment-product',sku:'FITMENT',name:'Product before',subtitle:'',description:'A sufficiently complete test description',category_id:category,subcategory:'',price_cents:10000,currency:'EUR',stock:0,status:'draft',is_verified:false,featured:false,badges:[],review_count:0,specs:{},package_contents:[],tools_required:[],legacy_compatible_brands:[],tags:[]};
  const rule={brand_id:brand,model_name:'Test model',chassis:'W205',year_from:2015,year_to:2018,body_types:['sedan'],facelift:'pre-lci',required_trims:[],excluded_trims:[],verification_state:'verified'};
  const images=[{url:'https://example.test/product.webp',display_order:0,image_type:'main'}];
  const sql='select admin_save_product($1,$2,$3,$4,$5,$6,$7) id';
  const save=async(id,expected,rules,b=base)=>(await one(sql,[admin,id,expected,b,images,rules,{supplier_verified:false}])).id;
  const product=await save(null,null,[rule]);
  const original=await one('select * from product_compatibilities where product_id=$1',[product]);
  const originalImage=await one('select * from product_images where product_id=$1',[product]);
  const variant=(await one("select admin_save_commerce_record($1,'variant',null,$2,null) data",[admin,{product_id:product,sku:'FIXTURE-V',name:'Fixture variant',price_cents:10000,status:'active',is_verified:true,evidence_ref:'Fixture only',compatibility_ids:[original.id]}])).data;
  let stamp=(await one('select updated_at from products where id=$1',[product])).updated_at;
  await save(product,stamp,[rule],{...base,name:'Description-only edit',description:'Description updated without changing any fitting rule.'});
  const afterLegacy=await one('select * from product_compatibilities where id=$1',[original.id]);
  eq(afterLegacy,original);eq((await one('select compatibility_id from variant_compatibilities where variant_id=$1',[variant.id])).compatibility_id,original.id);
  eq((await one('select * from product_images where product_id=$1',[product])),originalImage);
  let audit=await one("select metadata from admin_audit where resource=$1 and action='product.update' order by created_at desc limit 1",[product]);
  eq(audit.metadata.compatibilities.inserted_ids,[]);eq(audit.metadata.compatibilities.removed_ids,[]);
  stamp=(await one('select updated_at from products where id=$1',[product])).updated_at;
  await save(product,stamp,[{...rule,id:original.id}],{...base,name:'Explicit identity edit'});
  eq((await one('select * from product_compatibilities where id=$1',[original.id])),original);
  const otherProduct=await save(null,null,[rule],{...base,slug:'other-fitment',sku:'OTHER-FITMENT'});
  const foreign=(await one('select id from product_compatibilities where product_id=$1',[otherProduct])).id;
  stamp=(await one('select updated_at from products where id=$1',[product])).updated_at;
  const before=await one('select * from products where id=$1',[product]);const auditCount=(await one('select count(*)::integer n from admin_audit')).n;
  await fail(sql,[admin,product,stamp,{...base,name:'Must roll back'},images,[{...rule,id:foreign}],{}],/does not belong/);
  await fail(sql,[admin,product,stamp,base,images,[{...rule,id:original.id},{...rule,id:original.id}],{}],/Duplicate compatibility ID/);
  await fail(sql,[admin,product,stamp,{...base,name:'Removed linked rule'},[],[],{}],/foreign key/);
  await fail(sql,[admin,product,stamp,{...base,name:'Downgraded linked rule'},[],[{...rule,id:original.id,verification_state:'unverified'}],{}],/would become invalid/);
  eq((await one('select * from products where id=$1',[product])),before);
  eq((await one('select count(*)::integer n from admin_audit')).n,auditCount);
  eq((await one('select * from product_images where product_id=$1',[product])),originalImage);
  eq((await one('select * from product_compatibilities where id=$1',[original.id])),original);
  await fail(sql,[admin,product,null,base,images,[rule],{}],/Product changed/);
  await fail(sql,[admin,product,'2000-01-01T00:00:00Z',base,images,[rule],{}],/Product changed/);
  await fail(sql,[customer,product,stamp,base,images,[rule],{}],/Admin role required/);
  // Explicit, verified changes update that identity in place; no reassociation.
  await save(product,stamp,[{...rule,id:original.id,notes:'Verified fitting restriction updated explicitly'}]);
  eq((await one('select id,notes from product_compatibilities where product_id=$1',[product])),{id:original.id,notes:'Verified fitting restriction updated explicitly'});
  eq((await one('select compatibility_id from variant_compatibilities where variant_id=$1',[variant.id])).compatibility_id,original.id);
  // A genuinely retired, unreferenced rule can be removed, but not a linked rule.
  const free=await save(null,null,[rule],{...base,slug:'free-fitment',sku:'FREE-FITMENT'});
  const freeStamp=(await one('select updated_at from products where id=$1',[free])).updated_at;
  await save(free,freeStamp,[],{...base,slug:'free-fitment',sku:'FREE-FITMENT'});
  eq((await one('select count(*)::integer n from product_compatibilities where product_id=$1',[free])).n,0);
  // Legacy duplicates are refused instead of arbitrarily stealing an association.
  await fail(sql,[admin,null,null,{...base,slug:'new-duplicates-fitment',sku:'NEW-DUPLICATES'},images,[rule,rule],{supplier_verified:false}],/Duplicate new compatibility content/);
  const duplicateProduct=await save(null,null,[rule],{...base,slug:'duplicates-fitment',sku:'DUPLICATES'});
  await db.query(`insert into product_compatibilities(product_id,brand_id,model_name,chassis,year_from,year_to,body_types,facelift,required_trims,excluded_trims,verification_state)
    select product_id,brand_id,model_name,chassis,year_from,year_to,body_types,facelift,required_trims,excluded_trims,verification_state from product_compatibilities where product_id=$1`,[duplicateProduct]);
  const duplicateStamp=(await one('select updated_at from products where id=$1',[duplicateProduct])).updated_at;
  await fail(sql,[admin,duplicateProduct,duplicateStamp,{...base,slug:'duplicates-fitment',sku:'DUPLICATES'},images,[rule],{}],/Ambiguous legacy/);
  const duplicates=(await db.query('select id from product_compatibilities where product_id=$1 order by id',[duplicateProduct])).rows;
  await save(duplicateProduct,duplicateStamp,duplicates.map(x=>({...rule,id:x.id})),{...base,slug:'duplicates-fitment',sku:'DUPLICATES'});
  eq((await one('select count(*)::integer n from product_compatibilities where product_id=$1',[duplicateProduct])).n,2);
  for(const role of ['anon','authenticated']) eq((await one("select has_function_privilege($1,'public.admin_save_product(uuid,uuid,timestamptz,jsonb,jsonb,jsonb,jsonb)','EXECUTE') allowed",[role])).allowed,false);
  eq((await one("select has_function_privilege('service_role','public.admin_save_product(uuid,uuid,timestamptz,jsonb,jsonb,jsonb,jsonb)','EXECUTE') allowed")).allowed,true);
  console.log(JSON.stringify({checks,result:'passed',engine:'PostgreSQL/PGlite',hostedDatabase:false}));
} catch(error) {console.error(JSON.stringify({checks,result:'failed',message:error.message,code:error.code,where:error.where,detail:error.detail}));process.exitCode=1;}
finally {await db.close();}
