// Isolated PostgreSQL/PGlite only. Synthetic owners/products/prices/events;
// never hosted credentials, network, Stripe, public catalogue or supplier orders.
import {readFile,access} from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for(const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url),new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js',import.meta.url)]) {
  try {await access(url);runtime=url.href;break;} catch {}
}
if(!runtime) throw new Error('Existing pinned PGlite required; no installation');
const {PGlite}=await import(runtime),db=new PGlite();let checks=0;
const one=async(sql,args=[]) => (await db.query(sql,args)).rows[0];
const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
const fail=async(sql,args,pattern)=>{await assert.rejects(db.query(sql,args),pattern);checks++;};
const migration='20261025121320_commerce_customer_test_checkout.sql';
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
    '20261023233030_commerce_stable_fitment_save.sql','20261024012206_commerce_quote_snapshots.sql','20261024073311_commerce_checkout_attempts.sql',
    '20261024140301_commerce_test_settlement.sql','20261024143917_commerce_hypersku_preparations.sql','20261024144103_commerce_positive_image_rights.sql',
    '20261025043553_commerce_simulated_tracking_retention.sql'])
    await db.exec((await readFile(new URL('../supabase/migrations/'+name,import.meta.url),'utf8')).replace('create extension if not exists pgcrypto;','-- built-in gen_random_uuid'));
  const admin='10000000-0000-4000-8000-000000000001',user='10000000-0000-4000-8000-000000000002',other='10000000-0000-4000-8000-000000000003';
  const session='20000000-0000-4000-8000-000000000002',otherSession='20000000-0000-4000-8000-000000000003';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test'),($3,'other@example.test')",[admin,user,other]);
  await db.query("update profiles set role='admin' where id=$1",[admin]);
  await db.query('insert into auth.sessions(id,user_id) values($1,$2),($3,$4)',[session,user,otherSession,other]);
  const category=(await one("insert into categories(slug,name) values('customer-test','Synthetic') returning id")).id;
  const brand=(await one("insert into brands(slug,name) values('customer-test','Synthetic') returning id")).id;
  const base={slug:'customer-product',sku:'CUSTOMER-SYNTHETIC',name:'Synthetic product',subtitle:'',description:'Disposable synthetic checkout fixture, not a real verified product or supplier',category_id:category,subcategory:'',price_cents:10000,currency:'EUR',stock:100,status:'active',is_verified:true,featured:false,badges:[],review_count:0,specs:{},package_contents:['Part'],installation_difficulty:'easy',delivery_estimate:'Fixture only',tools_required:[],legacy_compatible_brands:[],tags:[]};
  const rule={brand_id:brand,chassis:'W205',year_from:2015,year_to:2018,body_types:['sedan'],facelift:'pre-lci',required_trims:[],excluded_trims:[],verification_state:'verified'};
  const product=(await one('select admin_save_product($1,null,null,$2,$3,$4,$5) id',[admin,base,[{url:'https://cdn.example.com/customer-fixture.webp',display_order:0,image_type:'main'}],[rule],{supplier_verified:true,cost_price_cents:1000}])).id;
  await db.query(`insert into commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,derivatives_use,product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
    values($1,'https://cdn.example.com/customer-fixture.webp','verified','SYNTHETIC NOT A REAL GRANT',true,true,true,'not_present',array['FR'],now()+interval '1 year',$2,now())`,[product,admin]);
  const save=async(kind,data)=>(await one('select admin_save_commerce_record($1,$2,null,$3,null) data',[admin,kind,data])).data;
  const agent=await save('agent',{profile_id:admin,name:'Synthetic operator',role:'orders',is_active:true});
  const variant=await save('variant',{product_id:product,sku:'CUSTOMER-V1-SYNTHETIC',name:'Black',price_cents:10000,stock:100,status:'active',is_verified:true,evidence_ref:'SYNTHETIC',requires_vehicle:false});
  const variant2=await save('variant',{product_id:product,sku:'CUSTOMER-V2-SYNTHETIC',name:'White',price_cents:10000,stock:100,status:'active',is_verified:true,evidence_ref:'SYNTHETIC',requires_vehicle:false});
  const supplier=(await one("insert into suppliers(name,url) values('Synthetic customer supplier','https://supplier.example.test') returning id")).id;
  const until=(await one("select now()+interval '3 hours' value")).value.toISOString();
  const offers=[],rates=[];
  for(const v of [variant,variant2]) {
    const offer=await save('offer',{variant_id:v.id,supplier_id:supplier,supplier_sku:'SOURCE-'+v.sku,supplier_variant:v.name,url:'https://supplier.example.test/item',verification_state:'verified',evidence_ref:'SYNTHETIC',is_primary:true,availability:'available',available_quantity:100,valid_until:until,unit_cost_cents:1000,recoverable_tax_cents:0,preparation_days_min:1,preparation_days_max:2,responsible_agent_id:agent.id});
    offers.push(offer);
    rates.push(await save('shipping_rate',{offer_id:offer.id,country:'FR',mode:'tracked',max_quantity:100,shipping_cost_cents:100,shipping_recoverable_tax_cents:0,customer_shipping_cents:500,goods_tax_bps:2000,shipping_tax_bps:2000,agent_fee_cents:0,import_duty_cents:0,nonrecoverable_tax_cents:0,other_cost_cents:0,verification_state:'verified',evidence_ref:'SYNTHETIC',valid_until:until,delivery_days_min:2,delivery_days_max:3,multi_variant_policy:'independent_parcels'}));
  }
  const destination={name:'Synthetic recipient',line1:'1 Synthetic street',city:'Paris',country:'FR',postal_code:'75001'};
  const key=()=>one('select gen_random_uuid() id').then(x=>x.id);
  const ownerUser=[user,null,session],ownerOther=[other,null,otherSession];
  async function cart(owner) {
    return (await one('insert into carts(user_id,guest_session_id) values($1,$2) returning id',owner.slice(0,2))).id;
  }
  async function add(cartId,owner,v=variant) {
    return (await one('select commerce_cart_add($1,$2,$3,$4,$5,1,null,false) id',[cartId,...owner.slice(0,2),product,v.id])).id;
  }
  function payload(s) {
    const groups=[];let subtotal=0,shipping=0,taxes=0;
    for(const item of s.cart_items) {
      const v=s.variants.find(x=>x.id===item.variant_id),o=s.offers.find(x=>x.variant_id===v.id),r=s.rates.find(x=>x.offer_id===o.id),p=s.products[0];
      const goods=v.price_cents*item.quantity,total=goods+r.customer_shipping_cents;
      const net=Math.round(goods*10000/(10000+r.goods_tax_bps))+Math.round(r.customer_shipping_cents*10000/(10000+r.shipping_tax_bps));
      const acquisition=(o.unit_cost_cents-o.recoverable_tax_cents)*item.quantity,landed=acquisition+r.shipping_cost_cents-r.shipping_recoverable_tax_cents;
      subtotal+=goods;shipping+=r.customer_shipping_cents;taxes+=total-net;
      groups.push({variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,line_ids:[item.id],
        evaluation:{status:'ready',reasons:[],variant_id:v.id,offer_id:o.id,shipping_rate_id:r.id,responsible_agent_id:agent.id,supplier_id:supplier,supplier_sku:o.supplier_sku,supplier_variant:o.supplier_variant,quantity:item.quantity,currency:'EUR',supplier_gross_cents:o.unit_cost_cents*item.quantity,acquisition_net_cents:acquisition,shipping_net_cents:r.shipping_cost_cents-r.shipping_recoverable_tax_cents,additional_costs_cents:0,landed_cost_cents:landed,customer_shipping_cents:r.customer_shipping_cents,unit_price_cents:v.price_cents,customer_total_cents:total,revenue_net_cents:net,sales_tax_cents:total-net,contribution_margin_cents:net-landed,valid_until:until,delivery_days_min:3,delivery_days_max:5,margin_basis:'before_payment_fees_and_operating_expenses_not_net_profit'},
        lines:[{cart_item_id:item.id,product_id:p.id,variant_id:v.id,quantity:item.quantity,unit_amount_cents:v.price_cents,sku:v.sku,product_name:p.name,product_slug:p.slug,image_url:'https://cdn.example.com/customer-fixture.webp',selected_vehicle:item.selected_vehicle??null,compatibility_result:{status:'not_required'},variant_name:v.name,variant_attributes:v.attributes}]});
    }
    return {groups,subtotal_cents:subtotal,shipping_cents:shipping,tax_cents:taxes,total_cents:subtotal+shipping,currency:'EUR',valid_until:until};
  }
  async function quote(cartId,owner) {
    const src=(await one("select commerce_cart_context($1,$2,$3,'FR','75001','tracked') data",[cartId,...owner.slice(0,2)])).data;
    return (await one("select commerce_save_quote($1,$2,$3,$4,$5,'tracked',$6,$7) data",[cartId,...owner.slice(0,2),await key(),destination,src,payload(src)])).data;
  }
  function params(c) {
    const a=c.attempt,o=c.order,metadata={order_id:o.id,quote_id:o.commerce_quote_id,attempt_id:a.id},origin=a.frontend_origin;
    return {mode:'payment',client_reference_id:o.id,metadata,payment_intent_data:{metadata},
      line_items:c.items.map(i=>({quantity:i.quantity,price_data:{currency:'eur',unit_amount:i.unit_amount_cents,tax_behavior:'inclusive',product_data:{name:i.product_name,metadata:{product_id:i.product_id,variant_id:i.variant_id,order_item_id:i.id},images:[i.image_url]}}})),
      shipping_options:[{shipping_rate_data:{type:'fixed_amount',fixed_amount:{amount:o.shipping_amount_cents,currency:'eur'},display_name:'Livraison',tax_behavior:'inclusive'}}],shipping_address_collection:{allowed_countries:['FR']},billing_address_collection:'required',automatic_tax:{enabled:false},adaptive_pricing:{enabled:false},allow_promotion_codes:false,integration_identifier:a.integration_identifier,expires_at:a.expires_at,
      success_url:origin+'/order-success?session_id={CHECKOUT_SESSION_ID}',cancel_url:origin+'/cart?checkout=cancelled'};
  }
  const origin='https://tymotors.example.com';
  // Import a legacy ambiguous cart before applying the new gate. Both drafts
  // existed previously; the additive migration must prevent either claim now.
  const legacyOwner=[null,await key(),null],legacyCart=await cart(legacyOwner);await add(legacyCart,legacyOwner);
  const legacy=[];
  for(let i=0;i<2;i++) {
    const q=await quote(legacyCart,legacyOwner);
    const o=(await one('select commerce_order_from_quote($1,$2,null,$3,true) data',[admin,q.id,legacyOwner[1]])).data;
    const ctx=(await one('select commerce_prepare_checkout_attempt($1,$2,$3) data',[admin,o.order_id,origin])).data;
    await one('select commerce_store_checkout_params($1,$2,$3)',[admin,ctx.attempt.id,params(ctx)]);legacy.push(ctx);
  }
  await db.exec(await readFile(new URL('../supabase/migrations/'+migration,import.meta.url),'utf8'));
  const orderSQL='select commerce_customer_order_from_quote($1,$2,$3,$4) data';
  const prepareSQL='select commerce_customer_prepare_checkout_attempt($1,$2,$3,$4,$5) data';
  const storeSQL='select commerce_customer_store_checkout_params($1,$2,$3,$4,$5) data';
  const claimSQL='select commerce_customer_claim_checkout_attempt($1,$2,$3,$4) data';
  const unknownSQL='select commerce_customer_checkout_unknown($1,$2,$3,$4,$5) data';
  const cancelSQL='select commerce_customer_cancel_checkout_draft($1,$2,$3,$4) data';
  const functions=[['commerce_customer_order_from_quote','uuid,uuid,text,uuid'],['commerce_customer_prepare_checkout_attempt','uuid,text,uuid,text,uuid'],['commerce_customer_store_checkout_params','uuid,jsonb,uuid,text,uuid'],['commerce_customer_claim_checkout_attempt','uuid,uuid,text,uuid'],['commerce_customer_checkout_unknown','uuid,text,uuid,text,uuid'],['commerce_customer_cancel_checkout_draft','uuid,uuid,text,uuid']];
  for(const [name,types] of functions) {
    const reg='public.'+name+'('+types+')';
    for(const role of ['anon','authenticated']) eq((await one('select has_function_privilege($1,$2,$3) ok',[role,reg,'EXECUTE'])).ok,false);
    eq((await one('select has_function_privilege($1,$2,$3) ok',['service_role',reg,'EXECUTE'])).ok,true);
    eq((await one('select prosecdef from pg_proc where oid=$1::regprocedure',[reg])).prosecdef,false);
  }
  const privateFunctions=(await db.query("select p.oid::regprocedure::text name from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='private' and (p.proname like '%checkout%core' or p.proname in('commerce_attempt_order_core','commerce_order_from_quote_core','assert_commerce_checkout_authority','assert_commerce_customer_identity','assert_commerce_cart_purchase','guard_commerce_order_owner'))")).rows;
  for(const fn of privateFunctions) for(const role of ['anon','authenticated']) eq((await one('select has_function_privilege($1,$2,$3) ok',[role,fn.name,'EXECUTE'])).ok,false);
  await db.exec('set role service_role');
  for(const c of legacy) await fail(claimSQL,[c.attempt.id,...legacyOwner],/Another checkout purchase/);
  const userCart=await cart(ownerUser),item=await add(userCart,ownerUser),q=await quote(userCart,ownerUser);
  for(const invalid of [ownerOther,[user,null,otherSession],[user,null,null],[user,'guest-capability-1234',session],[null,null,null],[null,'short',null],[null,'valid-guest-capability',session]])
    await fail(orderSQL,[q.id,...invalid],/owner|authenticated|guest/i);
  const o=(await one(orderSQL,[q.id,...ownerUser])).data;
  eq(o.is_test,true);eq(o.reused,false);
  eq((await one(orderSQL,[q.id,...ownerUser])).data.order_id,o.order_id);
  eq((await one('select count(*)::int n from orders where commerce_quote_id=$1',[q.id])).n,1);
  await fail('select commerce_order_from_quote($1,$2,$3,null,true)',[user,q.id,user],/Admin role required/);
  await fail('select commerce_order_from_quote($1,$2,$3,null,false)',[admin,q.id,user],/live checkout is disabled/);
  for(const role of ['anon','authenticated']) {
    await db.exec('reset role;set role '+role);
    await fail(orderSQL,[q.id,...ownerUser],/permission denied/);
  }
  await db.exec('reset role;set role service_role');
  const ctx=(await one(prepareSQL,[o.order_id,origin,...ownerUser])).data;
  eq(ctx.attempt.state,'drafting');eq(ctx.order.is_test,true);eq(ctx.order.payment_status,'unpaid');eq(ctx.items.length,1);
  eq((await one(prepareSQL,[o.order_id,origin,...ownerUser])).data.attempt.id,ctx.attempt.id);
  await fail(prepareSQL,[o.order_id,origin,...ownerOther],/owner mismatch/);
  await fail(prepareSQL,[o.order_id,'https://different.example.com',...ownerUser],/origin mismatch/);
  await fail(storeSQL,[ctx.attempt.id,{forged:true},...ownerUser],/parameters do not match/);
  const ready=(await one(storeSQL,[ctx.attempt.id,params(ctx),...ownerUser])).data;
  eq(ready.state,'ready');eq((await one(storeSQL,[ctx.attempt.id,params(ctx),...ownerUser])).data.params_hash,ready.params_hash);
  await fail(storeSQL,[ctx.attempt.id,{...params(ctx),expires_at:1},...ownerUser],/immutable/);
  // Different request keys cannot make a second purchase of the same basket.
  const q2=await quote(userCart,ownerUser);
  await fail(orderSQL,[q2.id,...ownerUser],/Another checkout purchase/);
  const quoteRace=await Promise.allSettled([one(orderSQL,[q.id,...ownerUser]),one(orderSQL,[q2.id,...ownerUser])]);
  eq(quoteRace.filter(x=>x.status==='fulfilled').length,1);
  eq(quoteRace.filter(x=>x.status==='rejected').length,1);
  eq((await one('select count(*)::int n from orders where cart_id=$1',[userCart])).n,1);
  // Revocation/profile disappearance and source mutations are checked again at claim.
  await db.exec('reset role');await db.query("update auth.sessions set not_after=now()-interval '1 second' where id=$1",[session]);await db.exec('set role service_role');
  await fail(claimSQL,[ready.id,...ownerUser],/authenticated checkout owner/);
  await db.exec('reset role');await db.query('update auth.sessions set not_after=null where id=$1',[session]);
  await db.exec('begin');await db.query('delete from profiles where id=$1',[user]);
  await fail(claimSQL,[ready.id,...ownerUser],/authenticated checkout owner/);await db.exec('rollback');
  for(const mutation of ["update supplier_offers set unit_cost_cents=unit_cost_cents+1", "update commerce_image_permissions set state='revoked'", "update commerce_agents set is_active=false"]) {
    await db.exec('begin');await db.exec(mutation);await fail(claimSQL,[ready.id,...ownerUser],/source changed/i);await db.exec('rollback');
  }
  eq((await one('select first_requested_at from commerce_checkout_attempts where id=$1',[ready.id])).first_requested_at,null);
  await db.exec('set role service_role');
  // Concurrent JS requests on the disposable serialized PostgreSQL engine:
  // exactly one claim succeeds. This is NOT an independent-connection lock test.
  const claimRace=await Promise.allSettled([one(claimSQL,[ready.id,...ownerUser]),one(claimSQL,[ready.id,...ownerUser])]);
  eq(claimRace.filter(x=>x.status==='fulfilled').length,1);
  eq(claimRace.filter(x=>x.status==='rejected').length,1);
  const claimed=claimRace.find(x=>x.status==='fulfilled').value.data;
  eq(claimed.state,'creating');eq(claimed.idempotency_key,ready.idempotency_key);eq(claimed.params_hash,ready.params_hash);
  await fail(claimSQL,[ready.id,...ownerUser],/claimed twice/);
  await fail(cancelSQL,[ready.id,...ownerUser],/requires reconciliation/);
  await fail(unknownSQL,[ready.id,'private unbounded provider error',...ownerUser],/Bounded technical/);
  await fail(unknownSQL,[ready.id,'provider_timeout',...ownerOther],/owner mismatch/);
  const ambiguous=(await one(unknownSQL,[ready.id,'provider_timeout',...ownerUser])).data;
  eq(ambiguous.state,'unknown');eq(ambiguous.idempotency_key,ready.idempotency_key);
  await fail(orderSQL,[q2.id,...ownerUser],/Another checkout purchase/);
  await db.exec('begin');
  await one('select commerce_cart_update($1,$2,$3,$4,$5,2,false)',[userCart,user,null,item,product]);
  const editedWhileUnknown=await quote(userCart,ownerUser);
  await fail(orderSQL,[editedWhileUnknown.id,...ownerUser],/Another checkout purchase/);await db.exec('rollback');
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[ready.id])).state,'held');
  // Test financial truth is recorded by the EXISTING dedicated transaction.
  // Synthetic event/session identifiers are fixtures, never provider evidence.
  const sid='cs_test_customer_synthetic_'+(await key()).replaceAll('-','');
  const payment={object:'checkout.session',id:sid,mode:'payment',livemode:false,status:'complete',payment_status:'paid',currency:'eur',client_reference_id:o.order_id,
    metadata:{attempt_id:ready.id,order_id:o.order_id,quote_id:q.id},amount_total:ctx.order.total_cents,amount_subtotal:ctx.order.subtotal_cents,expires_at:ready.expires_at,
    total_details:{amount_shipping:ctx.order.shipping_amount_cents,amount_discount:0,amount_tax:0},automatic_tax:{enabled:false},payment_intent:'pi_customer_synthetic',customer_details:{email:'synthetic@example.test'}};
  await one('select commerce_settle_test_checkout($1,$2,$3,true)',['evt_customer_synthetic','checkout.session.completed',payment]);
  eq((await one('select payment_status from orders where id=$1',[o.order_id])).payment_status,'paid');
  await fail(orderSQL,[q2.id,...ownerUser],/already purchased/);
  await db.exec('begin');
  await one('select commerce_cart_update($1,$2,$3,$4,$5,2,false)',[userCart,user,null,item,product]);
  const editedPaidLine=await quote(userCart,ownerUser);
  await fail(orderSQL,[editedPaidLine.id,...ownerUser],/already purchased/);await db.exec('rollback');
  // Newly added lines survive; a mixed basket cannot silently recharge old lines.
  const newItem=await add(userCart,ownerUser,variant2),mixed=await quote(userCart,ownerUser);
  await fail(orderSQL,[mixed.id,...ownerUser],/already purchased/);
  eq((await one('select count(*)::int n from cart_items where cart_id=$1',[userCart])).n,2);
  await db.query('delete from cart_items where id=$1 and cart_id=$2',[item,userCart]);
  eq((await one('select id from cart_items where cart_id=$1',[userCart])).id,newItem);
  const disjoint=await quote(userCart,ownerUser);
  await db.query('update orders set refunded_amount_cents=1 where id=$1',[o.order_id]);
  await fail(orderSQL,[disjoint.id,...ownerUser],/financial review/);
  await db.query('update orders set refunded_amount_cents=0 where id=$1',[o.order_id]);
  const next=(await one(orderSQL,[disjoint.id,...ownerUser])).data;
  eq(next.order_id!==o.order_id,true);eq((await one('select id from cart_items where cart_id=$1',[userCart])).id,newItem);
  const nextCtx=(await one(prepareSQL,[next.order_id,origin,...ownerUser])).data;
  eq(nextCtx.attempt.state,'drafting');
  const cancelled=(await one(cancelSQL,[nextCtx.attempt.id,...ownerUser])).data;
  eq(cancelled.state,'cancelled');eq((await one(cancelSQL,[nextCtx.attempt.id,...ownerUser])).data,cancelled);
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[cancelled.id])).state,'released');
  const replacement=await quote(userCart,ownerUser);
  eq((await one(orderSQL,[replacement.id,...ownerUser])).data.is_test,true);
  // Guest ownership is an independent capability; login never converts it.
  const guestOwner=[null,await key(),null],guestCart=await cart(guestOwner);await add(guestCart,guestOwner);
  const gq=await quote(guestCart,guestOwner),go=(await one(orderSQL,[gq.id,...guestOwner])).data;
  const gc=(await one(prepareSQL,[go.order_id,origin,...guestOwner])).data;
  await fail(prepareSQL,[go.order_id,origin,...ownerUser],/owner mismatch/);
  await fail(cancelSQL,[gc.attempt.id,null,await key(),null],/owner mismatch/);
  await one(cancelSQL,[gc.attempt.id,...guestOwner]);
  await fail('update orders set user_id=$2 where id=$1',[go.order_id,user],/cannot be reassigned/);
  await fail('update orders set guest_session_id=$2 where id=$1',[go.order_id,await key()],/cannot be reassigned/);
  const guestAudit=(await db.query("select admin_user_id,metadata from admin_audit where resource in($1,$2) and action like 'commerce.%'",[go.order_id,gc.attempt.id])).rows;
  eq(guestAudit.length>0,true);eq(guestAudit.every(x=>x.admin_user_id===null),true);
  eq(guestAudit.every(x=>x.metadata.authority==='customer_guest'),true);
  eq(JSON.stringify(guestAudit).includes(guestOwner[1]),false);
  // A provider error may arrive after cart deletion: immutable quote/order
  // ownership, not a live basket lookup, authorizes the bounded unknown marker.
  const lateOwner=[null,await key(),null],lateCart=await cart(lateOwner);await add(lateCart,lateOwner);
  const lq=await quote(lateCart,lateOwner),lo=(await one(orderSQL,[lq.id,...lateOwner])).data;
  const lc=(await one(prepareSQL,[lo.order_id,origin,...lateOwner])).data;
  await one(storeSQL,[lc.attempt.id,params(lc),...lateOwner]);
  eq((await one(claimSQL,[lc.attempt.id,...lateOwner])).data.state,'creating');
  await db.query('delete from carts where id=$1',[lateCart]);
  eq((await one(unknownSQL,[lc.attempt.id,'provider_timeout',...lateOwner])).data.state,'unknown');
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[lc.attempt.id])).state,'held');
  await fail(cancelSQL,[lc.attempt.id,...lateOwner],/requires reconciliation/);
  // The never-claimed counterpart may cancel safely even after detachment.
  const detachedOwner=[null,await key(),null],detachedCart=await cart(detachedOwner);await add(detachedCart,detachedOwner);
  const dq=await quote(detachedCart,detachedOwner),dorder=(await one(orderSQL,[dq.id,...detachedOwner])).data;
  const dc=(await one(prepareSQL,[dorder.order_id,origin,...detachedOwner])).data;
  await db.query('delete from carts where id=$1',[detachedCart]);
  eq((await one(cancelSQL,[dc.attempt.id,...detachedOwner])).data.state,'cancelled');
  eq((await one('select state from commerce_variant_reservations where attempt_id=$1',[dc.attempt.id])).state,'released');
  const userAudit=(await one("select admin_user_id,metadata from admin_audit where resource=$1 and action='commerce.quote.prepare_test_order'",[o.order_id]));
  eq(userAudit.admin_user_id,null);eq(userAudit.metadata.authority,'customer_user');eq(userAudit.metadata.actor_user_id,user);
  // The refactoring also preserves an administrator's complete successful path.
  const adminOwner=[null,await key(),null],adminCart=await cart(adminOwner);await add(adminCart,adminOwner);
  const aq=await quote(adminCart,adminOwner);
  const ao=(await one('select commerce_order_from_quote($1,$2,null,$3,true) data',[admin,aq.id,adminOwner[1]])).data;
  const ac=(await one('select commerce_prepare_checkout_attempt($1,$2,$3) data',[admin,ao.order_id,origin])).data;
  await one('select commerce_store_checkout_params($1,$2,$3)',[admin,ac.attempt.id,params(ac)]);
  eq((await one('select commerce_claim_checkout_attempt($1,$2) data',[admin,ac.attempt.id])).data.state,'creating');
  eq((await one('select commerce_checkout_unknown($1,$2,$3) data',[admin,ac.attempt.id,'provider_timeout'])).data.state,'unknown');
  const aa=await one("select admin_user_id,metadata from admin_audit where resource=$1 and action='commerce.checkout.claimed'",[ac.attempt.id]);
  eq(aa.admin_user_id,admin);eq(aa.metadata.authority,'admin');
  await fail('select commerce_prepare_checkout_attempt($1,$2,$3)',[user,ao.order_id,origin],/Admin role required/);
  // All real inventory and supplier-order tables remain untouched.
  eq((await one('select stock from product_variants where id=$1',[variant.id])).stock,100);
  eq((await one('select available_quantity from supplier_offers where id=$1',[offers[0].id])).available_quantity,100);
  eq((await one('select count(*)::int n from supplier_orders')).n,0);
  console.log(JSON.stringify({checks,engine:'PostgreSQL/PGlite',result:'passed',transport:'NONE',real_payments:0,real_supplier_orders:0,commercial_products_validated:0,scope:'owner_test_checkout_and_cross_quote_purchase_guards'}));
} finally {await db.close();}
