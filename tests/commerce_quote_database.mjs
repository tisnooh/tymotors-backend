// PostgreSQL/PGlite in memory only; no network, secrets, installs or production DB.
import {readFile,access} from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for(const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url)]) {
  try {await access(url);runtime=url.href;break;} catch {}
}
if(!runtime) throw new Error('Existing PGlite runtime required; no automatic installation');
const {PGlite}=await import(runtime);const db=new PGlite();let checks=0;
const one=async(sql,args=[]) => (await db.query(sql,args)).rows[0];
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(sql,args,pattern)=>{await assert.rejects(db.query(sql,args),pattern);checks++;};
const copy=value=>JSON.parse(JSON.stringify(value));
try {
  await db.exec(`create role anon;create role authenticated;create role service_role bypassrls;create schema auth;
    create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
    create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
    create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
    grant usage on schema auth to anon,authenticated,service_role;grant execute on function auth.uid() to anon,authenticated,service_role;`);
  for(const name of ['202608240001_initial_ecommerce.sql','20260911071309_admin_backoffice.sql','20260911120652_admin_backoffice_hardening.sql',
    '20260912165642_complete_email_system.sql','20260912211934_email_advisor_hardening.sql','20261011221114_supplier_fulfillment_workflow.sql',
    '20261011222034_supplier_fulfillment_indexes.sql','20261012042643_supplier_link_refresh.sql','20261012115851_checkout_customer_phone.sql',
    '20261012120138_supplier_directory.sql','20261012163951_withdrawal_receipts.sql','20261012184823_enforce_active_auth_session.sql',
    '20261013063630_sandbox_catalog_orders.sql','20261023132803_commerce_foundation.sql','20261023232733_commerce_cart_identity.sql',
    '20261023233030_commerce_stable_fitment_save.sql','20261024012206_commerce_quote_snapshots.sql']) {
    await db.exec((await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8')).replace('create extension if not exists pgcrypto;','-- built-in gen_random_uuid'));
  }
  const admin='10000000-0000-4000-8000-000000000001',user='10000000-0000-4000-8000-000000000002',other='10000000-0000-4000-8000-000000000003';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test'),($3,'other@example.test')",[admin,user,other]);
  await db.query("update profiles set role='admin' where id=$1",[admin]);
  const category=(await one("insert into categories(slug,name) values('quote-test','Quote') returning id")).id;
  const brand=(await one("insert into brands(slug,name) values('quote-test','Quote') returning id")).id;
  const base={slug:'quote-product',sku:'QUOTE',name:'Fixture product',subtitle:'',description:'Disposable quote product, not a real verified item',category_id:category,subcategory:'',price_cents:10000,currency:'EUR',stock:10,status:'active',is_verified:true,featured:false,badges:[],review_count:0,specs:{},package_contents:['Part'],installation_difficulty:'easy',delivery_estimate:'Fixture only',tools_required:[],legacy_compatible_brands:[],tags:[]};
  const rule={brand_id:brand,chassis:'W205',year_from:2015,year_to:2018,body_types:['sedan'],facelift:'pre-lci',required_trims:[],excluded_trims:[],verification_state:'verified'};
  const product=(await one('select admin_save_product($1,null,null,$2,$3,$4,$5) id',[admin,base,[{url:'https://example.test/item.webp',display_order:0,image_type:'main'}],[rule],{supplier_verified:true,cost_price_cents:1000}])).id;
  const save=async(kind,data,id=null,expected=null)=>(await one('select admin_save_commerce_record($1,$2,$3,$4,$5) data',[admin,kind,id,data,expected])).data;
  const agent=await save('agent',{profile_id:admin,name:'Test order agent',role:'orders',is_active:true});
  const variant=await save('variant',{product_id:product,sku:'QUOTE-V',name:'Gloss black',price_cents:10000,stock:10,status:'active',is_verified:true,evidence_ref:'Fixture',requires_vehicle:false,attributes:{finish:'black'}});
  const supplier=(await one("insert into suppliers(name,url) values('Quote supplier','https://supplier.example.test') returning id")).id;
  const until=(await one("select now()+interval '3 hours' value")).value.toISOString();
  const offer=await save('offer',{variant_id:variant.id,supplier_id:supplier,supplier_sku:'SOURCE-V',supplier_variant:'Black',url:'https://supplier.example.test/item',verification_state:'verified',evidence_ref:'Fixture',is_primary:true,availability:'available',available_quantity:10,valid_until:until,unit_cost_cents:1000,recoverable_tax_cents:0,preparation_days_min:1,preparation_days_max:2,responsible_agent_id:agent.id});
  const rate=await save('shipping_rate',{offer_id:offer.id,country:'FR',mode:'tracked',max_quantity:20,shipping_cost_cents:100,shipping_recoverable_tax_cents:0,customer_shipping_cents:500,goods_tax_bps:2000,shipping_tax_bps:2000,agent_fee_cents:0,import_duty_cents:0,nonrecoverable_tax_cents:0,other_cost_cents:0,verification_state:'verified',evidence_ref:'Fixture',valid_until:until,delivery_days_min:2,delivery_days_max:3,multi_variant_policy:'independent_parcels'});
  eq(rate.multi_variant_policy,'independent_parcels');
  const cart=(await one('insert into carts(user_id) values($1) returning id',[user])).id;
  const line=(await one('select commerce_cart_add($1,$2,null,$3,$4,2,null,false) id',[cart,user,product,variant.id])).id;
  const destination={country:'FR',postal_code:'75001'};
  const contextSQL='select commerce_cart_context($1,$2,$3,$4,$5,$6) data';
  const context=async(c=cart,u=user,g=null)=>(await one(contextSQL,[c,u,g,'FR','75001','tracked'])).data;
  let source=await context();
  eq(source.postal_code,'75001');eq(source.cart_items.map(x=>x.id),[line]);
  function payload(s=source) {
    const item=s.cart_items[0],v=s.variants[0],o=s.offers[0],r=s.rates.find(x=>x.id===rate.id),p=s.products[0];
    const qty=item.quantity,goods=v.price_cents*qty,total=goods+r.customer_shipping_cents;
    const net=Math.round(goods*10000/(10000+r.goods_tax_bps))+Math.round(r.customer_shipping_cents*10000/(10000+r.shipping_tax_bps));
    const acquisition=(o.unit_cost_cents-o.recoverable_tax_cents)*qty,landed=acquisition+r.shipping_cost_cents-r.shipping_recoverable_tax_cents;
    return {groups:[{variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,line_ids:[item.id],
      evaluation:{status:'ready',reasons:[],variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,supplier_sku:o.supplier_sku,supplier_variant:o.supplier_variant,quantity:qty,currency:'EUR',supplier_gross_cents:o.unit_cost_cents*qty,acquisition_net_cents:acquisition,shipping_net_cents:r.shipping_cost_cents-r.shipping_recoverable_tax_cents,additional_costs_cents:0,landed_cost_cents:landed,customer_shipping_cents:r.customer_shipping_cents,unit_price_cents:v.price_cents,customer_total_cents:total,revenue_net_cents:net,sales_tax_cents:total-net,contribution_margin_cents:net-landed,valid_until:until,delivery_days_min:3,delivery_days_max:5,margin_basis:'before_payment_fees_and_operating_expenses_not_net_profit'},
      lines:[{cart_item_id:item.id,product_id:p.id,variant_id:v.id,quantity:qty,unit_amount_cents:v.price_cents,sku:v.sku,product_name:p.name,product_slug:p.slug,image_url:null,selected_vehicle:item.selected_vehicle??null,compatibility_result:{status:'not_required'},variant_name:v.name,variant_attributes:v.attributes}]}],subtotal_cents:goods,shipping_cents:r.customer_shipping_cents,tax_cents:total-net,total_cents:total,currency:'EUR',valid_until:until};
  }
  const saveSQL='select commerce_save_quote($1,$2,$3,$4,$5,$6,$7,$8) data';
  const key=()=>one('select gen_random_uuid() id').then(x=>x.id);
  const quote=async(src=source,body=payload(src),requestKey=null)=>(await one(saveSQL,[cart,user,null,requestKey||await key(),destination,'tracked',src,body])).data;
  const requestKey=await key();
  const first=await quote(source,payload(),requestKey);
  eq(first.state,'ready');eq(first.total_cents,20500);eq(first.tax_cents,3416);
  assert.ok(new Date(first.expires_at)-new Date(first.created_at)<=45*60*1000);checks++;
  eq((await quote(source,payload(),requestKey)).id,first.id);
  await db.exec('begin');
  await quote();
  eq((await one("select exists(select 1 from pg_locks where relation='public.profiles'::regclass and mode='ExclusiveLock' and granted) locked")).locked,true);
  eq((await one("select exists(select 1 from pg_locks where relation='public.shipping_rates'::regclass and mode='ExclusiveLock' and granted) locked")).locked,true);
  await db.exec('commit');
  await fail(saveSQL,[cart,user,null,requestKey,destination,'tracked',source,{...payload(),total_cents:1}],/key content mismatch/);
  await fail(contextSQL,[cart,other,null,'FR','75001','tracked'],/not owned/);
  await fail(saveSQL,[cart,other,null,await key(),destination,'tracked',source,payload()],/not owned/);
  for(const mutate of [b=>b.currency='USD',b=>b.total_cents=1,b=>b.tax_cents=0,b=>b.groups[0].lines[0].unit_amount_cents=1,
    b=>b.groups[0].evaluation.customer_shipping_cents=0,b=>b.groups[0].evaluation.supplier_gross_cents=1,
    b=>b.groups[0].lines.push(copy(b.groups[0].lines[0])),b=>b.groups[0].line_ids=[],b=>b.groups[0].lines[0].quantity=1]) {
    const body=payload();mutate(body);await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',source,body],/quote|Quote|Duplicate|evaluation|currency|line/i);
  }
  // Source price and newly inserted restrictions both invalidate the captured source.
  await db.query('update product_variants set price_cents=price_cents+1 where id=$1',[variant.id]);
  await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',source,payload()],/source changed/);
  await db.query('update product_variants set price_cents=price_cents-1 where id=$1',[variant.id]);
  source=await context();
  const sourceBeforeRegion=copy(source);
  await save('shipping_rate',{...rate,id:undefined,created_at:undefined,updated_at:undefined,postal_prefix:'75',multi_variant_policy:'independent_parcels'});
  await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',sourceBeforeRegion,payload(sourceBeforeRegion)],/source changed/);
  await db.query('delete from shipping_rates where offer_id=$1 and postal_prefix=$2',[offer.id,'75']);
  source=await context();
  const beforeRule=copy(source);
  await db.query("insert into product_compatibilities(product_id,brand_id,chassis,verification_state) values($1,$2,'W206','unverified')",[product,brand]);
  await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',beforeRule,payload(beforeRule)],/source changed/);
  source=await context();
  for(const [statement,args,pattern] of [
    ['update supplier_offers set moq=3 where id=$1',[offer.id],/quantity unavailable/],
    ['update supplier_offers set available_quantity=1 where id=$1',[offer.id],/quantity unavailable/],
    ['update product_variants set stock=1 where id=$1',[variant.id],/quantity unavailable/],
    ["update shipping_rates set valid_until=now()+interval '20 minutes' where id=$1",[rate.id],/expire too soon/],
    ["update carts set currency='USD' where id=$1",[cart],/currency/],
    ["update products set currency='USD' where id=$1",[product],/identity or verification mismatch/],
  ]) {
    await db.query(statement,args);source=await context();
    await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',source,payload()],pattern);
    await db.query('update supplier_offers set moq=1,available_quantity=10 where id=$1',[offer.id]);
    await db.query('update product_variants set stock=10 where id=$1',[variant.id]);
    await db.query('update shipping_rates set valid_until=$2 where id=$1',[rate.id,until]);
    await db.query("update carts set currency='EUR' where id=$1",[cart]);
    await db.query("update products set currency='EUR' where id=$1",[product]);
  }
  source=await context();
  const extraLine=(await one('select commerce_cart_add($1,$2,null,$3,$4,1,$5,false) id',[cart,user,product,variant.id,{brand_slug:'bmw',year:2016}])).id;
  source=await context();
  await fail(saveSQL,[cart,user,null,await key(),destination,'tracked',source,payload()],/every cart line/);
  await db.query('delete from cart_items where id=$1',[extraLine]);source=await context();
  // Context counts are exact and reject excess rows instead of truncating.
  await db.exec('begin');
  await db.query("insert into cart_items(cart_id,product_id,variant_id,quantity,selected_vehicle) select $1,$2,$3,1,jsonb_build_object('year',g) from generate_series(1,101) g",[cart,product,variant.id]);
  await fail(contextSQL,[cart,user,null,'FR','75001','tracked'],/cart line limit/);await db.exec('rollback');
  await db.exec('begin');
  await db.query("insert into shipping_rates(offer_id,country,mode,max_quantity,postal_prefix) select $1,'FR','tracked',20,g::text from generate_series(1,1001) g",[offer.id]);
  await fail(contextSQL,[cart,user,null,'FR','75001','tracked'],/shipping rule limit/);await db.exec('rollback');
  await db.exec('begin');
  await db.query("insert into supplier_offers(variant_id,supplier_id,supplier_sku,supplier_variant,url) select $1,$2,'LIMIT-'||g,'Black','https://example.test/item' from generate_series(1,1001) g",[variant.id,supplier]);
  await fail(contextSQL,[cart,user,null,'FR','75001','tracked'],/offer limit/);await db.exec('rollback');
  await db.exec('begin');
  await db.query("insert into product_compatibilities(product_id,brand_id,chassis) select $1,$2,'LIMIT-'||g from generate_series(1,1001) g",[product,brand]);
  await fail(contextSQL,[cart,user,null,'FR','75001','tracked'],/compatibility rule limit/);await db.exec('rollback');
  source=await context();
  const second=await quote();eq((await one('select state from commerce_quotes where id=$1',[first.id])).state,'superseded');
  await fail('update commerce_quotes set payload=$2 where id=$1',[second.id,{fake:true}],/immutable/);
  await fail('update commerce_quotes set cart_id=null where id=$1',[second.id],/immutable/);
  await fail('update commerce_quotes set state=$2 where id=$1',[second.id,'consumed'],/pending test order/);
  const orderSQL='select commerce_order_from_quote($1,$2,$3,$4,$5) data';
  await fail(orderSQL,[admin,second.id,user,null,false],/live checkout is disabled/);
  await fail(orderSQL,[user,second.id,user,null,true],/Admin role required/);
  await fail(orderSQL,[admin,second.id,other,null,true],/not owned/);
  await fail(orderSQL,[admin,first.id,user,null,true],/expired, superseded or consumed/);
  const order=(await one(orderSQL,[admin,second.id,user,null,true])).data;
  eq(order.is_test,true);eq((await one(orderSQL,[admin,second.id,user,null,true])).data.order_id,order.order_id);
  eq((await one('select is_test,status,payment_status,subtotal_cents,shipping_amount_cents,total_cents,stock_applied_at from orders where id=$1',[order.order_id])),{is_test:true,status:'pending',payment_status:'unpaid',subtotal_cents:20000,shipping_amount_cents:500,total_cents:20500,stock_applied_at:null});
  eq((await one('select count(*)::integer n from orders where commerce_quote_id=$1',[second.id])).n,1);
  eq((await one('select count(*)::integer n from admin_audit where resource=$1 and action=$2',[order.order_id,'commerce.quote.prepare_test_order'])).n,1);
  eq((await one('select stock from product_variants where id=$1',[variant.id])).stock,10);
  eq((await one('select count(*)::integer n from supplier_orders where order_id=$1',[order.order_id])).n,0);
  const privateLine=await one('select * from commerce_order_lines where order_id=$1',[order.order_id]);
  const publicLine=await one('select * from order_items where order_id=$1',[order.order_id]);
  eq(publicLine.cost_price_cents,null);eq(publicLine.variant_name,'Gloss black');eq(publicLine.source_cart_item_id,line);
  await fail('update commerce_order_lines set offer_snapshot=$2 where id=$1',[privateLine.id,{fake:true}],/immutable/);
  await fail('update order_items set variant_name=$2 where id=$1',[publicLine.id,'Faked'],/immutable/);
  await fail('update orders set commerce_quote_id=null where id=$1',[order.order_id],/immutable/);
  await fail('update orders set total_cents=1 where id=$1',[order.order_id],/immutable/);
  await fail('update orders set is_test=false where id=$1',[order.order_id],/immutable/);
  await db.query("update orders set customer_name='Allowed customer metadata' where id=$1",[order.order_id]);
  eq((await one('select customer_name from orders where id=$1',[order.order_id])).customer_name,'Allowed customer metadata');
  await fail('update commerce_quotes set state=$2 where id=$1',[second.id,'ready'],/Invalid quote state transition/);
  await fail('truncate commerce_quotes cascade',[],/immutable/);
  await db.exec('begin;set local role service_role');
  await fail('update commerce_quotes set subtotal_cents=1 where id=$1',[second.id],/immutable/);await db.exec('rollback');
  await db.exec('begin;set local role service_role');
  await fail('update commerce_order_lines set group_key=$2 where id=$1',[privateLine.id,'changed'],/permission denied/);await db.exec('rollback');
  await db.exec('begin;set local role service_role');
  eq((await one(orderSQL,[admin,second.id,user,null,true])).data.order_id,order.order_id);await db.exec('commit');
  await db.query('delete from carts where id=$1',[cart]);
  const detached=await one('select * from commerce_quotes where id=$1',[second.id]);
  eq(detached.cart_id,null);eq(detached.source_context.cart.id,cart);eq(detached.owner_user_id,user);eq(detached.payload,second.payload);
  eq((await one('select offer_snapshot from commerce_order_lines where id=$1',[privateLine.id])).offer_snapshot,privateLine.offer_snapshot);
  await fail(orderSQL,[admin,second.id,user,null,true],/cart is missing/);
  for(const table of ['commerce_quotes','commerce_order_lines']) {
    eq((await one('select relrowsecurity from pg_class where oid=$1::regclass',['public.'+table])).relrowsecurity,true);
    for(const role of ['anon','authenticated']) {
      await db.exec('begin;set local role '+role);await fail('select * from '+table,[],/permission denied/);await db.exec('rollback');
    }
  }
  for(const fn of ['commerce_cart_context(uuid,uuid,text,text,text,text)','commerce_save_quote(uuid,uuid,text,uuid,jsonb,text,jsonb,jsonb)','commerce_order_from_quote(uuid,uuid,uuid,text,boolean)'])
    for(const role of ['anon','authenticated']) eq((await one('select has_function_privilege($1,$2,$3) allowed',[role,'public.'+fn,'EXECUTE'])).allowed,false);
  console.log(JSON.stringify({checks,result:'passed',engine:'PostgreSQL/PGlite',hostedDatabase:false}));
} catch(error) {console.error(JSON.stringify({checks,result:'failed',message:error.message,code:error.code,where:error.where,detail:error.detail}));process.exitCode=1;}
finally {await db.close();}
