// Disposable PostgreSQL, no SDK/network/secrets/hosted DB. Explicit runtime install only.
import {readFile,access} from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for(const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url)]) {
  try {await access(url);runtime=url.href;break;} catch {}
}
if(!runtime) throw new Error('Existing PGlite runtime required; no automatic installation');
const {PGlite}=await import(runtime),db=new PGlite();let checks=0;
const one=async(sql,args=[]) => (await db.query(sql,args)).rows[0];
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(sql,args,pattern)=>{await assert.rejects(db.query(sql,args),pattern);checks++;};
const clone=x=>JSON.parse(JSON.stringify(x));
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
    '20261023233030_commerce_stable_fitment_save.sql','20261024012206_commerce_quote_snapshots.sql','20261024073311_commerce_checkout_attempts.sql','20261024144103_commerce_positive_image_rights.sql'])
    await db.exec((await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8')).replace('create extension if not exists pgcrypto;','-- built-in gen_random_uuid'));
  const admin='10000000-0000-4000-8000-000000000001',user='10000000-0000-4000-8000-000000000002';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')",[admin,user]);
  await db.query("update profiles set role='admin' where id=$1",[admin]);
  const category=(await one("insert into categories(slug,name) values('attempt-test','Attempt') returning id")).id;
  const brand=(await one("insert into brands(slug,name) values('attempt-test','Attempt') returning id")).id;
  const base={slug:'attempt-product',sku:'ATTEMPT',name:'Fixture product',subtitle:'',description:'Disposable attempt product, not a real verified item',category_id:category,subcategory:'',price_cents:10000,currency:'EUR',stock:10,status:'active',is_verified:true,featured:false,badges:[],review_count:0,specs:{},package_contents:['Part'],installation_difficulty:'easy',delivery_estimate:'Fixture only',tools_required:[],legacy_compatible_brands:[],tags:[]};
  const rule={brand_id:brand,chassis:'W205',year_from:2015,year_to:2018,body_types:['sedan'],facelift:'pre-lci',required_trims:[],excluded_trims:[],verification_state:'verified'};
  const product=(await one('select admin_save_product($1,null,null,$2,$3,$4,$5) id',[admin,base,[{url:'https://example.test/item.webp',display_order:0,image_type:'main'}],[rule],{supplier_verified:true,cost_price_cents:1000}])).id;
  await db.query(`insert into commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,derivatives_use,product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
    values($1,'https://example.test/item.webp','verified','SYNTHETIC GRANT',true,true,true,'not_present',array['FR'],now()+interval '1 year',$2,now())`,[product,admin]);
  const save=async(kind,data,id=null,expected=null)=>(await one('select admin_save_commerce_record($1,$2,$3,$4,$5) data',[admin,kind,id,data,expected])).data;
  const agent=await save('agent',{profile_id:admin,name:'Test order agent',role:'orders',is_active:true});
  const variant=await save('variant',{product_id:product,sku:'ATTEMPT-V',name:'Gloss black',price_cents:10000,stock:10,status:'active',is_verified:true,evidence_ref:'Fixture',requires_vehicle:false,attributes:{finish:'black'}});
  const supplier=(await one("insert into suppliers(name,url) values('Attempt supplier','https://supplier.example.test') returning id")).id;
  const until=(await one("select now()+interval '3 hours' value")).value.toISOString();
  const offer=await save('offer',{variant_id:variant.id,supplier_id:supplier,supplier_sku:'SOURCE-V',supplier_variant:'Black',url:'https://supplier.example.test/item',verification_state:'verified',evidence_ref:'Fixture',is_primary:true,availability:'available',available_quantity:10,valid_until:until,unit_cost_cents:1000,recoverable_tax_cents:0,preparation_days_min:1,preparation_days_max:2,responsible_agent_id:agent.id});
  const rate=await save('shipping_rate',{offer_id:offer.id,country:'FR',mode:'tracked',max_quantity:20,shipping_cost_cents:100,shipping_recoverable_tax_cents:0,customer_shipping_cents:500,goods_tax_bps:2000,shipping_tax_bps:2000,agent_fee_cents:0,import_duty_cents:0,nonrecoverable_tax_cents:0,other_cost_cents:0,verification_state:'verified',evidence_ref:'Fixture',valid_until:until,delivery_days_min:2,delivery_days_max:3,multi_variant_policy:'independent_parcels'});
  const destination={name:'Test customer',line1:'1 Fixture street',city:'Paris',country:'FR',postal_code:'75001'};
  const key=()=>one('select gen_random_uuid() id').then(x=>x.id);
  function payload(s) {
    const item=s.cart_items[0],v=s.variants[0],o=s.offers.find(x=>x.id===offer.id),r=s.rates.find(x=>x.id===rate.id),p=s.products[0];
    const qty=item.quantity,goods=v.price_cents*qty,total=goods+r.customer_shipping_cents;
    const net=Math.round(goods*10000/(10000+r.goods_tax_bps))+Math.round(r.customer_shipping_cents*10000/(10000+r.shipping_tax_bps));
    const acquisition=(o.unit_cost_cents-o.recoverable_tax_cents)*qty,landed=acquisition+r.shipping_cost_cents-r.shipping_recoverable_tax_cents;
    return {groups:[{variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,line_ids:[item.id],
      evaluation:{status:'ready',reasons:[],variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,supplier_sku:o.supplier_sku,supplier_variant:o.supplier_variant,quantity:qty,currency:'EUR',supplier_gross_cents:o.unit_cost_cents*qty,acquisition_net_cents:acquisition,shipping_net_cents:r.shipping_cost_cents-r.shipping_recoverable_tax_cents,additional_costs_cents:0,landed_cost_cents:landed,customer_shipping_cents:r.customer_shipping_cents,unit_price_cents:v.price_cents,customer_total_cents:total,revenue_net_cents:net,sales_tax_cents:total-net,contribution_margin_cents:net-landed,valid_until:until,delivery_days_min:3,delivery_days_max:5,margin_basis:'before_payment_fees_and_operating_expenses_not_net_profit'},
      lines:[{cart_item_id:item.id,product_id:p.id,variant_id:v.id,quantity:qty,unit_amount_cents:v.price_cents,sku:v.sku,product_name:p.name,product_slug:p.slug,image_url:null,selected_vehicle:item.selected_vehicle??null,compatibility_result:{status:'not_required'},variant_name:v.name,variant_attributes:v.attributes}]}],subtotal_cents:goods,shipping_cents:r.customer_shipping_cents,tax_cents:total-net,total_cents:total,currency:'EUR',valid_until:until};
  }
  async function order(qty=2,aged=false) {
    const guest=await key();
    const cart=(await one('insert into carts(guest_session_id) values($1) returning id',[guest])).id;
    await one('select commerce_cart_add($1,null,$2,$3,$4,$5,null,false) id',[cart,guest,product,variant.id,qty]);
    const src=(await one("select commerce_cart_context($1,null,$2,'FR','75001','tracked') data",[cart,guest])).data;
    let quote=(await one("select commerce_save_quote($1,null,$2,$3,$4,'tracked',$5,$6) data",[cart,guest,await key(),destination,src,payload(src)])).data;
    if(aged) {
      // A valid historical quote fixture: creation was 20m ago, 25m remain.
      quote=(await one(`insert into commerce_quotes(cart_id,owner_guest_session,country,mode,destination,source_context,payload,subtotal_cents,shipping_cents,tax_cents,total_cents,expires_at,request_key,created_at)
        values($1,$2,'FR','tracked',$3,$4,$5,$6,500,$7,$8,clock_timestamp()+interval '25 minutes',$9,clock_timestamp()-interval '20 minutes') returning to_jsonb(commerce_quotes) data`,
        [cart,guest,destination,src,payload(src),quote.subtotal_cents,quote.tax_cents,quote.total_cents,await key()])).data;
    }
    const row=(await one('select commerce_order_from_quote($1,$2,null,$3,true) data',[admin,quote.id,guest])).data;
    return {...row,quote,cart};
  }
  const prepareSQL='select commerce_prepare_checkout_attempt($1,$2,$3) data',storeSQL='select commerce_store_checkout_params($1,$2,$3) data';
  const claimSQL='select commerce_claim_checkout_attempt($1,$2) data',cancelSQL='select commerce_cancel_checkout_draft($1,$2) data';
  const origin='https://tymotors.example.com';
  const prepare=async(o)=>(await one(prepareSQL,[admin,o.order_id,origin])).data;
  function params(c) {
    const a=c.attempt,o=c.order,metadata={order_id:o.id,quote_id:o.commerce_quote_id,attempt_id:a.id};
    return {mode:'payment',client_reference_id:o.id,metadata,payment_intent_data:{metadata},
      line_items:c.items.map(i=>({quantity:i.quantity,price_data:{currency:'eur',unit_amount:i.unit_amount_cents,tax_behavior:'inclusive',product_data:{name:i.product_name,metadata:{product_id:i.product_id,variant_id:i.variant_id,order_item_id:i.id},...(i.image_url?{images:[i.image_url]}:{})}}})),
      shipping_options:[{shipping_rate_data:{type:'fixed_amount',fixed_amount:{amount:o.shipping_amount_cents,currency:'eur'},display_name:'Livraison',tax_behavior:'inclusive'}}],shipping_address_collection:{allowed_countries:['FR']},billing_address_collection:'required',automatic_tax:{enabled:false},adaptive_pricing:{enabled:false},allow_promotion_codes:false,integration_identifier:a.integration_identifier,expires_at:a.expires_at,
      success_url:origin+'/order-success?session_id={CHECKOUT_SESSION_ID}',cancel_url:origin+'/cart?checkout=cancelled'};
  }
  const first=await order(6),second=await order(6),initial=await prepare(first),a=initial.attempt;
  eq(a.state,'drafting');eq(a.is_test,true);eq(a.currency,'EUR');eq(a.total_cents,60500);eq(a.params,null);
  eq(initial.order.quote_expires_at,a.quote_expires_at);eq(initial.items.length,1);
  eq(/_[A-Za-z]{8}$/.test(a.integration_identifier),true);eq(a.idempotency_key,'tymotors-test-'+a.id);
  eq((await prepare(first)).attempt,a);
  await fail(prepareSQL,[admin,first.order_id,'https://other.example.com'],/origin mismatch/);
  await fail(prepareSQL,[user,first.order_id,origin],/Admin role required/);
  await fail(prepareSQL,[admin,first.order_id,'https://example.com/path'],/Invalid checkout frontend/);
  await db.exec('begin');await db.query("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents,currency) values($1,$2,'Forged extra item','attempt-product','FORGED',1,10000,'EUR')",[first.order_id,product]);
  await fail(prepareSQL,[admin,first.order_id,origin],/item snapshot mismatch/);await db.exec('rollback');
  // Same source stock cannot support two 6-unit attempts; failure is atomic.
  await fail(prepareSQL,[admin,second.order_id,origin],/variant reservation quantity unavailable/);
  eq((await one('select count(*)::int n from commerce_checkout_attempts')).n,1);
  eq((await one('select sum(quantity)::int n from commerce_variant_reservations where state=$1',['held'])).n,6);
  const good=params(initial);
  await fail('update commerce_checkout_attempts set state=$2,params=$3,params_hash=encode(sha256(convert_to($3::jsonb::text,$4)), $5) where id=$1',
    [a.id,'ready',{fake:true},'UTF8','hex'],/parameters do not match/);
  for(const mutate of [p=>p.line_items[0].quantity=5,p=>p.metadata.order_id=user,p=>p.payment_intent_data.metadata.attempt_id=user,
    p=>p.expires_at++,p=>p.success_url='https://evil.example.com',p=>p.shipping_options[0].shipping_rate_data.fixed_amount.amount=0,
    p=>p.shipping_address_collection.allowed_countries=['US'],p=>p.currency='usd',p=>p.payment_method_types=['card'],p=>p.automatic_tax.enabled=true]) {
    const bad=clone(good);mutate(bad);await fail(storeSQL,[admin,a.id,bad],/parameters do not match/);
  }
  const ready=(await one(storeSQL,[admin,a.id,good])).data;eq(ready.state,'ready');eq(ready.params,good);eq(ready.params_hash.length,64);
  eq((await one(storeSQL,[admin,a.id,good])).data,ready);
  eq((await one('select count(*)::int n from admin_audit where action=$1 and resource=$2',['commerce.checkout.params_stored',a.id])).n,1);
  await fail(storeSQL,[admin,a.id,{...good,mode:'subscription'}],/immutable/);
  for(const [field,value] of [['total_cents',1],['expires_at',1],['idempotency_key','changed-key-is-invalid'],['integration_identifier','other_abcdefgh'],['frontend_origin','https://evil.example.com'],['is_test',false],['params',{fake:true}],['params_hash','a'.repeat(64)]])
    await fail(`update commerce_checkout_attempts set ${field}=$2 where id=$1`,[a.id,value],/immutable|transition/);
  await fail('update commerce_variant_reservations set quantity=1 where attempt_id=$1',[a.id],/immutable/);
  await fail('update commerce_variant_reservations set state=$2 where attempt_id=$1',[a.id,'released'],/immutable/);
  // Current price/region/restriction changes are checked AGAIN at claim time.
  for(const [sql,args] of [
    ["update commerce_image_permissions set state='revoked' where product_id=$1",[product]],
    ['update product_variants set price_cents=price_cents+1 where id=$1',[variant.id]],
    ["update shipping_rates set valid_until=clock_timestamp()+interval '10 minutes' where id=$1",[rate.id]],
    ["insert into shipping_rates(offer_id,country,mode,max_quantity,postal_prefix) values($1,'FR','tracked',20,'75')",[offer.id]],
  ]) {
    await db.exec('begin');await db.query(sql,args);await fail(claimSQL,[admin,a.id],/source changed/);await db.exec('rollback');
    eq((await one('select state from commerce_checkout_attempts where id=$1',[a.id])).state,'ready');
  }
  const creating=(await one(claimSQL,[admin,a.id])).data;eq(creating.state,'creating');assert.ok(creating.first_requested_at);checks++;
  await fail(claimSQL,[admin,a.id],/cannot be claimed twice/);
  await fail(cancelSQL,[admin,a.id],/requires reconciliation/);
  await fail('select commerce_checkout_unknown($1,$2,$3)',[admin,a.id,'raw email@example.com'],/technical error/);
  const unknown=(await one('select commerce_checkout_unknown($1,$2,$3) data',[admin,a.id,'provider_timeout'])).data;eq(unknown.state,'unknown');
  eq(unknown.first_requested_at,creating.first_requested_at);eq(unknown.params_hash,ready.params_hash);
  await fail(cancelSQL,[admin,a.id],/requires reconciliation/);
  await fail(claimSQL,[admin,a.id],/cannot be claimed twice/);
  await fail(prepareSQL,[admin,second.order_id,origin],/variant reservation quantity unavailable/);
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[a.id])).state,'held');
  // A separate rollback fixture proves cancellation liberates only never-claimed test holds.
  await db.exec('begin');
  // Existing unknown remains held; smaller 4-unit order can consume remaining stock.
  const small=await order(4),draft=await prepare(small);
  eq((await one('select sum(quantity)::int n from commerce_variant_reservations where state=$1',['held'])).n,10);
  const cancelled=(await one(cancelSQL,[admin,draft.attempt.id])).data;eq(cancelled.state,'cancelled');eq((await one(cancelSQL,[admin,draft.attempt.id])).data,cancelled);
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[draft.attempt.id])).state,'released');
  eq((await one('select count(*)::int n from admin_audit where action=$1 and resource=$2',['commerce.checkout.draft_cancelled',draft.attempt.id])).n,1);
  await db.exec('rollback');
  // Offer stock is independently bounded when it is lower than variant stock.
  await db.exec('begin');await db.query('update supplier_offers set available_quantity=7 where id=$1',[offer.id]);
  const offerLimited=await order(2);await fail(prepareSQL,[admin,offerLimited.order_id,origin],/supplier reservation quantity unavailable/);await db.exec('rollback');
  // Variant stock is independently bounded, even when supplier stock is sufficient.
  await db.exec('begin');await db.query('update product_variants set stock=7 where id=$1',[variant.id]);
  const variantLimited=await order(2);await fail(prepareSQL,[admin,variantLimited.order_id,origin],/variant reservation quantity unavailable/);await db.exec('rollback');
  const aged=await order(2,true);await fail(prepareSQL,[admin,aged.order_id,origin],/expires too soon/);
  for(const local of ['http://127.0.0.1:8765','http://[::1]:8765','http://localhost:8765']) {
    await db.exec('begin');const localOrder=await order(1);
    eq((await one(prepareSQL,[admin,localOrder.order_id,local])).data.attempt.frontend_origin,local);await db.exec('rollback');
  }
  // Import a historical expired draft in this disposable DB. An expired local
  // timestamp NEVER subtracts a hold; only an explicit safe cancellation does.
  const history=await order(4),historyID=await key();
  await db.query(`insert into commerce_checkout_attempts(id,order_id,commerce_quote_id,total_cents,expires_at,quote_expires_at,frontend_origin,integration_identifier,idempotency_key)
    values($1,$2,$3,$4,floor(extract(epoch from clock_timestamp()))-60,$5,$6,'historic_abcdefgh',$7)`,
    [historyID,history.order_id,history.quote.id,history.quote.total_cents,history.quote.expires_at,origin,'historical-test-'+historyID]);
  await db.query('insert into commerce_variant_reservations(attempt_id,variant_id,offer_id,quantity) values($1,$2,$3,4)',[historyID,variant.id,offer.id]);
  const historyBlocked=await order(1);await fail(prepareSQL,[admin,historyBlocked.order_id,origin],/variant reservation quantity unavailable/);
  eq((await one('select sum(quantity)::int n from commerce_variant_reservations where state=$1',['held'])).n,10);
  eq((await one(cancelSQL,[admin,historyID])).data.state,'cancelled');
  // Cancel remains possible after cart purge, since no remote claim was authorized.
  const detachable=await order(2),dc=await prepare(detachable);await db.query('delete from carts where id=$1',[detachable.cart]);
  eq((await one(cancelSQL,[admin,dc.attempt.id])).data.state,'cancelled');
  // Repeating preparation restores old data without interpreting current catalogue prices.
  await db.exec('begin');await db.query('update product_variants set price_cents=12000 where id=$1',[variant.id]);
  eq((await prepare(first)).attempt,unknown);await db.exec('rollback');
  // Never mutate real stock, payments or supplier queue.
  eq((await one('select stock from products where id=$1',[product])).stock,10);
  eq((await one('select stock from product_variants where id=$1',[variant.id])).stock,10);
  eq((await one('select available_quantity from supplier_offers where id=$1',[offer.id])).available_quantity,10);
  eq((await one('select count(*)::int n from supplier_orders')).n,0);
  eq((await one("select count(*)::int n from orders where payment_status<>'unpaid' or not is_test")).n,0);
  for(const table of ['commerce_checkout_attempts','commerce_variant_reservations']) {
    eq((await one('select relrowsecurity from pg_class where oid=$1::regclass',['public.'+table])).relrowsecurity,true);
    await fail('delete from '+table,[],/immutable/);await fail('truncate '+table+' cascade',[],/immutable/);
    for(const role of ['anon','authenticated']) {
      await db.exec('begin;set local role '+role);await fail('select * from '+table,[],/permission denied/);await db.exec('rollback');
    }
  }
  for(const fn of ['commerce_prepare_checkout_attempt(uuid,uuid,text)','commerce_store_checkout_params(uuid,uuid,jsonb)',
    'commerce_claim_checkout_attempt(uuid,uuid)','commerce_checkout_unknown(uuid,uuid,text)','commerce_cancel_checkout_draft(uuid,uuid)']) {
    for(const role of ['anon','authenticated']) eq((await one('select has_function_privilege($1,$2,$3) allowed',[role,'public.'+fn,'EXECUTE'])).allowed,false);
  }
  await db.exec('begin;set local role service_role');
  eq((await prepare(first)).attempt.id,a.id);await db.exec('commit');
  await db.exec('begin');await prepare(first);
  for(const table of ['profiles','product_variants','supplier_offers','commerce_checkout_attempts','commerce_variant_reservations'])
    eq((await one('select exists(select 1 from pg_locks where relation=$1::regclass and mode=$2 and granted) locked',['public.'+table,'ExclusiveLock'])).locked,true);
  await db.exec('rollback');
  console.log(JSON.stringify({checks,result:'passed',engine:'PostgreSQL/PGlite',hostedDatabase:false,multiConnectionContentionVerified:false}));
} catch(error) {console.error(JSON.stringify({checks,result:'failed',message:error.message,code:error.code,where:error.where,detail:error.detail}));process.exitCode=1;}
finally {await db.close();}
