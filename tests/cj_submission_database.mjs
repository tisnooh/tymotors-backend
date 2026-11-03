// Disposable PostgreSQL engine. This never connects to hosted Supabase or CJ.
import { PGlite } from '../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const db = new PGlite();
await db.exec(`
  create role anon; create role authenticated; create role service_role bypassrls;
  create schema auth;
  create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
  create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
  create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid
  $$;
  grant usage on schema auth to anon,authenticated,service_role;
  grant execute on function auth.uid() to anon,authenticated,service_role;
`);
const migrations = [
  '202608240001_initial_ecommerce.sql',
  '20260911071309_admin_backoffice.sql',
  '20260911120652_admin_backoffice_hardening.sql',
  '20260912165642_complete_email_system.sql',
  '20260912211934_email_advisor_hardening.sql',
  '20261011221114_supplier_fulfillment_workflow.sql',
  '20261011222034_supplier_fulfillment_indexes.sql',
  '20261012042643_supplier_link_refresh.sql',
  '20261012115851_checkout_customer_phone.sql',
  '20261012120138_supplier_directory.sql',
  '20261012163951_withdrawal_receipts.sql',
  '20261012184823_enforce_active_auth_session.sql',
  '20261013063630_sandbox_catalog_orders.sql',
  '20261101041200_admin_dashboard_exclude_test_orders.sql',
  '20261101044000_admin_customers_exclude_test_orders.sql',
  '20261101050000_guard_supplier_claims.sql',
  '20261101052000_checkout_stock_reservations.sql',
  '20261101053000_admin_inventory_reserved_stock.sql',
  '20261103072605_admin_zero_checkout_diagnostic.sql',
  '20261103180202_cj_order_submission_reservation.sql',
];
for (const name of migrations) {
  let sql = await readFile(new URL(`../supabase/migrations/${name}`, import.meta.url), 'utf8');
  if (name === migrations[0]) sql = sql.replace('create extension if not exists pgcrypto;', '-- pgcrypto not needed by PGlite');
  await db.exec(sql);
}

let checks = 0;
const one = async (sql, params = []) => (await db.query(sql, params)).rows[0];
async function rejects(sql, params, pattern) {
  await assert.rejects(db.query(sql, params), pattern);
  checks++;
}
const admin = '10000000-0000-4000-8000-000000000001';
const customer = '10000000-0000-4000-8000-000000000002';
await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')", [admin, customer]);
await db.query("update public.profiles set role='admin' where id=$1", [admin]);
const cat = (await one("insert into categories(slug,name) values('test','Test') returning id")).id;
const brand = (await one("insert into brands(slug,name) values('bmw','BMW') returning id")).id;
const base = {
  slug: 'test-cj-product', sku: 'TEST-CJ-001', name: 'Test CJ product', subtitle: '',
  description: 'A complete test product description', category_id: cat, subcategory: '',
  price_cents: 1000, compare_at_price_cents: null, currency: 'EUR', stock: 10,
  status: 'active', is_verified: true, featured: false, badges: [], rating: null,
  review_count: 0, specs: {}, package_contents: ['Product'], installation_difficulty: 'easy',
  installation_minutes: null, tools_required: [], warranty_months: null,
  delivery_estimate: '5 days', legacy_compatible_brands: ['bmw'], low_stock_threshold: 3, tags: [],
};
const supplier = {
  supplier_name: 'Fixture supplier', supplier_reference: 'SUP-CJ-001',
  supplier_url: 'https://supplier.example.test',
  exact_source_url: 'https://www.alibaba.com/product-detail/test_123.html',
  supplier_verified: true, cost_price_cents: 300, shipping_cost_cents: 100,
};
const rules = [{
  brand_id: brand, model_name: 'Series 3', chassis: 'F30', year_from: 2012,
  year_to: 2019, body_types: [], facelift: 'unknown', required_trims: [],
  excluded_trims: [], verification_state: 'verified',
}];
const product = (await one('select admin_save_product($1,$2,$3,$4,$5,$6,$7) as id',
  [admin, null, null, base,
    [{url: 'https://example.test/product.png', display_order: 0, image_type: 'main'}],
    rules, supplier])).id;

const address = {line1: '1 rue Test', line2: '', city: 'Paris', state: 'Paris',
  postal_code: '75001', country: 'FR'};
async function makeOrder({test = false, paid = true, approve = true} = {}) {
  const order = await one(`insert into orders(order_number,subtotal_cents,total_cents,
    customer_email,customer_name,customer_phone,shipping_address,currency,is_test)
    values(gen_random_uuid()::text,1000,1000,'client@example.test','Client Test',
    '+33123456789',$1,'EUR',$2) returning *`, [address, test]);
  const item = await one(`insert into order_items(order_id,product_id,product_name,
    product_slug,sku,quantity,unit_amount_cents,compatibility_result)
    values($1,$2,'Test CJ product','test-cj-product','TEST-CJ-001',1,1000,
    '{"status":"compatible"}') returning *`, [order.id, product]);
  if (paid) {
    if (test) await db.query("update orders set stripe_session_id='cs_test_fixture' where id=$1", [order.id]);
    await db.query("select complete_paid_order($1,'pi_fixture','client@example.test','Client Test',$2,'{}')",
      [order.id, address]);
  }
  let dossier = await one('select * from supplier_orders where order_id=$1', [order.id]);
  if (approve && dossier) {
    await db.query(`select admin_update_supplier_order($1,$2,'approved',null,null,
      'CJdropshipping','not_connected',null,$3)`, [admin, order.id, dossier.updated_at]);
    dossier = await one('select * from supplier_orders where order_id=$1', [order.id]);
  }
  return {order: await one('select * from orders where id=$1', [order.id]), item, dossier};
}
function payload(fixture) {
  return {
    orderNumber: fixture.order.order_number, payType: 3, orderFlow: 1, isSandbox: 0,
    platform: 'Api', shopLogisticsType: 2, storeName: 'TYMotors',
    shippingZip: address.postal_code, shippingCountryCode: 'FR', shippingCountry: 'France',
    shippingProvince: address.state, shippingCity: address.city,
    shippingCustomerName: 'Client Test', shippingAddress: address.line1,
    shippingAddress2: '', shippingPhone: '+33123456789',
    logisticName: 'CJPacket', fromCountryCode: 'CN',
    products: [{vid: 'cj-variant-1', sku: 'CJ-SKU-1', storeProductId: product,
      storeSku: 'TEST-CJ-001', quantity: 1, storeLineItemId: fixture.item.id}],
  };
}
const claimSql = 'select admin_claim_cj_submission($1,$2,$3,$4,$5,$6) as data';
const fingerprint = 'a'.repeat(64);
const paid = await makeOrder();
const claimParams = [admin, paid.order.id, paid.dossier.updated_at, fingerprint, payload(paid), 'shop-1'];

for (const role of ['anon', 'authenticated']) {
  assert.equal((await one(`select has_table_privilege('${role}',
    'public.cj_order_submissions','INSERT') allowed`)).allowed, false); checks++;
  assert.equal((await one(`select has_function_privilege('${role}',
    'public.admin_claim_cj_submission(uuid,uuid,timestamptz,text,jsonb,text)','EXECUTE') allowed`)).allowed, false); checks++;
}
assert.equal((await one("select relrowsecurity as enabled from pg_class where oid='public.cj_order_submissions'::regclass")).enabled, true); checks++;
await rejects(claimSql, [customer, ...claimParams.slice(1)], /Admin role required/);
await rejects(claimSql, [admin, paid.order.id, new Date(0), fingerprint, payload(paid), 'shop-1'], /changed/);
await rejects(claimSql, [admin, paid.order.id, paid.dossier.updated_at, 'bad', payload(paid), 'shop-1'], /fingerprint/);
await rejects(claimSql, [admin, paid.order.id, paid.dossier.updated_at, fingerprint, payload(paid), ''], /shop ID/);
for (const bad of [
  {...payload(paid), payType: 2},
  {...payload(paid), payType: null},
  {...payload(paid), isSandbox: 1},
  {...payload(paid), shopAmount: 0},
  {...payload(paid), shippingAddress: 'wrong'},
  {...payload(paid), products: [{...payload(paid).products[0], quantity: 2}]},
  {...payload(paid), products: [{...payload(paid).products[0], storeSku: 'WRONG'}]},
  {...payload(paid), products: [{...payload(paid).products[0], vid: ''}]},
]) await rejects(claimSql, [admin, paid.order.id, paid.dossier.updated_at, fingerprint, bad, 'shop-1'], /CJ/);

const claimed = (await one(claimSql, claimParams)).data;
assert.equal(claimed.claimed, true); checks++;
assert.equal(claimed.submission.state, 'reserved'); checks++;
const repeated = (await one(claimSql,
  [admin, paid.order.id, null, 'bad', {payType: 2}, 'wrong-shop'])).data;
assert.equal(repeated.claimed, false);
assert.equal(repeated.submission.id, claimed.submission.id);
assert.equal((await one('select count(*) as n from cj_order_submissions where order_id=$1',
  [paid.order.id])).n, 1); checks++;
assert.equal((await one('select cj_shop_id from cj_order_submissions where order_id=$1',
  [paid.order.id])).cj_shop_id, 'shop-1'); checks++;

await rejects('select admin_finish_cj_submission($1,$2,$3,$4,$5)',
  [admin, claimed.submission.id, 'submitted', null, null], /requires its ID/);
await rejects('select admin_finish_cj_submission($1,$2,$3,$4,$5)',
  [admin, claimed.submission.id, 'ordered', 'CJ-1', null], /cannot be finished/);
const submitted = (await one('select admin_finish_cj_submission($1,$2,$3,$4,$5) as data',
  [admin, claimed.submission.id, 'submitted', 'CJ-1', 'request-1'])).data;
assert.equal(submitted.state, 'submitted'); checks++;
const after = await one('select * from supplier_orders where id=$1', [paid.dossier.id]);
assert.equal(after.agent_order_id, 'CJ-1');
assert.equal(after.status, 'approved');
assert.equal(after.agent_connection_status, 'not_connected'); checks++;
await rejects('select admin_finish_cj_submission($1,$2,$3,$4,$5)',
  [admin, claimed.submission.id, 'submitted', 'CJ-1', null], /cannot be finished twice/);

await rejects('select admin_observe_cj_submission($1,$2,$3)',
  [admin, claimed.submission.id, {shippingAddress: 'private'}], /unsupported fields/);
await rejects('select admin_observe_cj_submission($1,$2,$3)',
  [admin, claimed.submission.id, {shop_id: 'wrong-shop', order_id: 'CJ-1',
    order_status: 'AWAITING_PAYMENT', products: [{vid: 'cj-variant-1', quantity: 1,
      store_line_item_id: paid.item.id}]}], /identity and status/);
const observation = {shop_id: 'shop-1', order_id: 'CJ-1', order_number: 'api_generated_1',
  order_status: 'AWAITING_PAYMENT', sub_status: null, tracking_number: null,
  tracking_provider: null, logistic_name: 'CJPacket',
  products: [{vid: 'cj-variant-1', quantity: 1, store_line_item_id: paid.item.id}]};
const observed = (await one('select admin_observe_cj_submission($1,$2,$3) as data',
  [admin, claimed.submission.id, observation])).data;
assert.deepEqual(observed.observation, observation); checks++;
assert.equal((await one(`select is_customer_visible as visible from order_tracking_events
  where order_id=$1 and event_key='cj_submission_observed'`, [paid.order.id])).visible, false); checks++;

const testOrder = await makeOrder({test: true, approve: false});
await rejects(claimSql, [admin, testOrder.order.id, new Date(), fingerprint, payload(testOrder), 'shop-1'],
  /Supplier dossier not found|non-test/);
const unpaid = await makeOrder({paid: false, approve: false});
await rejects(claimSql, [admin, unpaid.order.id, new Date(), fingerprint, payload(unpaid), 'shop-1'],
  /Supplier dossier not found|non-test/);

const uncertainOrder = await makeOrder();
const uncertainClaim = (await one(claimSql, [admin, uncertainOrder.order.id,
  uncertainOrder.dossier.updated_at, 'b'.repeat(64), payload(uncertainOrder), 'shop-1'])).data;
const uncertain = (await one('select admin_finish_cj_submission($1,$2,$3,$4,$5) as data',
  [admin, uncertainClaim.submission.id, 'uncertain', null, 'request-timeout'])).data;
assert.equal(uncertain.state, 'uncertain'); checks++;
assert.equal((await one('select agent_order_id from supplier_orders where id=$1',
  [uncertainOrder.dossier.id])).agent_order_id, null); checks++;
assert.equal((await one(claimSql, [admin, uncertainOrder.order.id,
  uncertainOrder.dossier.updated_at, fingerprint, payload(uncertainOrder), 'shop-1'])).data.claimed, false); checks++;

const twoLines = await makeOrder({paid: false, approve: false});
const secondLine = await one(`insert into order_items(order_id,product_id,product_name,
  product_slug,sku,quantity,unit_amount_cents,compatibility_result)
  values($1,$2,'Test CJ product','test-cj-product','TEST-CJ-001',1,1000,
  '{"status":"compatible"}') returning *`, [twoLines.order.id, product]);
await db.query('update orders set subtotal_cents=2000,total_cents=2000 where id=$1', [twoLines.order.id]);
await db.query("select complete_paid_order($1,'pi_two','client@example.test','Client Test',$2,'{}')",
  [twoLines.order.id, address]);
let twoDossier = await one('select * from supplier_orders where order_id=$1', [twoLines.order.id]);
await db.query(`select admin_update_supplier_order($1,$2,'approved',null,null,
  'CJdropshipping','not_connected',null,$3)`, [admin, twoLines.order.id, twoDossier.updated_at]);
twoDossier = await one('select * from supplier_orders where order_id=$1', [twoLines.order.id]);
const twoPayload = payload(twoLines);
twoPayload.products.push({...twoPayload.products[0], storeLineItemId: secondLine.id});
const twoClaim = (await one(claimSql, [admin, twoLines.order.id,
  twoDossier.updated_at, 'c'.repeat(64), twoPayload, 'shop-1'])).data;
await one('select admin_finish_cj_submission($1,$2,$3,$4,$5)',
  [admin, twoClaim.submission.id, 'submitted', 'CJ-2', null]);
const firstObservedLine = {vid: 'cj-variant-1', quantity: 1,
  store_line_item_id: twoLines.item.id};
await rejects('select admin_observe_cj_submission($1,$2,$3)',
  [admin, twoClaim.submission.id, {shop_id: 'shop-1', order_id: 'CJ-2',
    order_status: 'AWAITING_PAYMENT', products: [firstObservedLine, firstObservedLine]}],
  /product lines differ/);

assert.equal((await one("select count(*) as n from admin_audit where action='cj_submission.claim'")).n, 3); checks++;
console.log(`${checks} CJ submission database checks passed`);
