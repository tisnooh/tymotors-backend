// Executed against PostgreSQL/PGlite in memory. No production data or network.
import { readFile, access } from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for (const url of [new URL('../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url),
                   new URL('../.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url),
                   new URL('../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js', import.meta.url)]) {
  try { await access(url); runtime = url.href; break; } catch {}
}
if (!runtime) throw new Error('Existing PGlite runtime missing');
const { PGlite } = await import(runtime);
const db = new PGlite();
let checks = 0;
const one = async (sql, params = []) => (await db.query(sql, params)).rows[0];
const eq = (a, b) => { assert.deepEqual(a, b); checks++; };
const fails = async (sql, params = [], pattern = /./) => { await assert.rejects(db.query(sql, params), pattern); checks++; };
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth; create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
    create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to anon,authenticated,service_role; grant execute on function auth.uid() to anon,authenticated,service_role;`);
  const migrations = ['202608240001_initial_ecommerce.sql', '20260911071309_admin_backoffice.sql',
    '20260911120652_admin_backoffice_hardening.sql', '20260912165642_complete_email_system.sql',
    '20260912211934_email_advisor_hardening.sql', '20261011221114_supplier_fulfillment_workflow.sql',
    '20261011222034_supplier_fulfillment_indexes.sql', '20261012042643_supplier_link_refresh.sql',
    '20261012115851_checkout_customer_phone.sql', '20261012120138_supplier_directory.sql',
    '20261012163951_withdrawal_receipts.sql', '20261012184823_enforce_active_auth_session.sql',
    '20261013063630_sandbox_catalog_orders.sql', '20261023132803_commerce_foundation.sql',
    '20261023232733_commerce_cart_identity.sql'];
  for (const file of migrations) {
    let sql = await readFile(new URL('../supabase/migrations/' + file, import.meta.url), 'utf8');
    await db.exec(sql.replace('create extension if not exists pgcrypto;', '-- gen_random_uuid built in'));
  }
  const admin = '10000000-0000-4000-8000-000000000001', customer = '10000000-0000-4000-8000-000000000002';
  await db.query("insert into auth.users(id,email) values($1,'admin@example.test'),($2,'client@example.test')", [admin, customer]);
  await db.query("update profiles set role='admin' where id=$1", [admin]);
  const category = (await one("insert into categories(slug,name) values('cart-test','Cart') returning id")).id;
  const brand = (await one("insert into brands(slug,name) values('cart-test','Synthetic') returning id")).id;
  async function product(sku, status = 'active', stock = 10) {
    const id = (await one(`insert into products(slug,sku,name,description,category_id,price_cents,stock,status,is_verified,
      package_contents,installation_difficulty,delivery_estimate)
      values(lower($1),$1,'Synthetic article','Disposable fixture only',$2,10000,$3,'draft',$4,
      array['Synthetic item'],'easy','Synthetic test only') returning id`,
      [sku, category, stock, status === 'active'])).id;
    if (status === 'active') {
      await db.query("insert into product_images(product_id,url,is_verified) values($1,'https://example.test/fixture.png',true)", [id]);
      await db.query("insert into product_compatibilities(product_id,brand_id,verification_state) values($1,$2,'verified')", [id, brand]);
      await db.query("insert into product_supplier_data(product_id,supplier_verified,cost_price_cents) values($1,true,100)", [id]);
      await db.query("update products set status='active' where id=$1", [id]);
    }
    return id;
  }
  const p = await product('CART-P'), legacy = await product('LEGACY', 'active', 3), draft = await product('DRAFT', 'draft', 0);
  const save = async data => (await one('select admin_save_commerce_record($1,\'variant\',null,$2,null) data', [admin, data])).data;
  const variant = await save({product_id: p, sku: 'BLACK', name: 'Black', price_cents: 10000, stock: 3,
    status: 'active', is_verified: true, evidence_ref: 'fixture only', requires_vehicle: false});
  const alternate = await save({product_id: p, sku: 'CARBON', name: 'Carbon', price_cents: 15000, stock: 10,
    status: 'active', is_verified: true, evidence_ref: 'fixture only', requires_vehicle: false});
  const cart = (await one('insert into carts(user_id) values($1) returning id', [customer])).id;
  const guestSession = 'synthetic_cart_guest_123456', guest = (await one('insert into carts(guest_session_id) values($1) returning id', [guestSession])).id;
  const a = {brand_slug: 'bmw', model: 'Série 3', chassis: 'F30', year: 2016, facelift: 'lci', has_camera: false};
  const b = {...a, year: 2017};
  const addSQL = 'select commerce_cart_add($1,$2,$3,$4,$5,$6,$7,$8) id';
  const add = async (product, v, q, vehicle = a, cid = cart, user = customer, guest = null, test = false) =>
    (await one(addSQL, [cid, user, guest, product, v, q, vehicle, test])).id;
  const updateSQL = 'select commerce_cart_update($1,$2,$3,$4,$5,$6,$7) changed';
  const first = await add(p, variant.id, 1);
  eq(await add(p, variant.id, 1, {...a, model: ' Série 3 ', compatibility_status: 'compatible'}), first);
  eq((await one('select quantity from cart_items where id=$1', [first])).quantity, 2);
  const second = await add(p, variant.id, 1, b);
  assert.notEqual(first, second); checks++;
  await fails(addSQL, [cart, customer, null, p, variant.id, 1, null, false], /stock across cart lines/);
  await fails(updateSQL, [cart, customer, null, second, p, 2, false], /stock across cart lines/);
  eq((await one('select sum(quantity)::integer n from cart_items where cart_id=$1 and variant_id=$2', [cart, variant.id])).n, 3);
  const otherVariant = await add(p, alternate.id, 1);
  assert.notEqual(first, otherVariant); checks++;
  await fails(updateSQL, [cart, customer, null, null, p, 0, false], /ambiguous/);
  await fails(updateSQL, [cart, customer, null, first, legacy, 0, false], /product mismatch/);
  await fails(addSQL, [cart, admin, null, p, alternate.id, 1, a, false], /not owned/);
  await fails(addSQL, [cart, null, guestSession, p, alternate.id, 1, a, false], /not owned/);
  await fails(addSQL, [cart, customer, null, legacy, alternate.id, 1, a, false], /does not belong/);
  await fails(addSQL, [cart, customer, null, p, null, 1, a, false], /variant selection required/);
  await fails(addSQL, [cart, customer, null, draft, null, 1, a, null], /Product unavailable/);
  await fails(addSQL, [cart, customer, null, draft, null, 1, a, false], /Product unavailable/);
  const testLine = await add(draft, null, 20, a, cart, customer, null, true);
  eq((await one('select quantity from cart_items where id=$1', [testLine])).quantity, 20);
  await fails(addSQL, [cart, customer, null, draft, null, 1, a, true], /quantity exceeds/);
  await fails(addSQL, [cart, customer, null, legacy, null, null, a, false], /quantity exceeds/);
  const legacyA = await add(legacy, null, 2);
  await fails(addSQL, [cart, customer, null, legacy, null, 2, b, false], /stock across cart lines/);
  await one(updateSQL, [cart, customer, null, second, p, 0, false]);
  eq((await one('select count(*)::integer n from cart_items where id=$1', [second])).n, 0);
  eq((await one('select quantity from cart_items where id=$1', [first])).quantity, 2);
  // Quick add without a vehicle cannot erase a selected vehicle.
  const noVehicle = await add(p, variant.id, 1, null);
  assert.notEqual(first, noVehicle); checks++;
  eq((await one('select selected_vehicle from cart_items where id=$1', [first])).selected_vehicle, a);
  // Claim must roll back EVERYTHING on an aggregate stock/quantity failure.
  await add(p, variant.id, 1, b, guest, null, guestSession);
  await add(p, alternate.id, 2, b, guest, null, guestSession);
  const claimSQL = 'select commerce_cart_claim($1,$2,$3,$4) changed';
  await fails(claimSQL, [cart, customer, guestSession, false], /stock across cart lines/);
  eq((await one('select count(*)::integer n from carts where id=$1', [guest])).n, 1);
  eq((await one('select quantity from cart_items where id=$1', [otherVariant])).quantity, 1);
  await one(updateSQL, [cart, customer, null, noVehicle, p, 0, false]);
  eq((await one(claimSQL, [cart, customer, guestSession, false])).changed, true);
  eq((await one('select count(*)::integer n from carts where id=$1', [guest])).n, 0);
  eq((await one(claimSQL, [cart, customer, guestSession, false])).changed, false);
  eq((await one('select quantity from cart_items where id=$1', [first])).quantity, 2);
  eq((await one('select quantity from cart_items where id=$1', [legacyA])).quantity, 2);
  const rows = (await db.query('select selected_vehicle,quantity,variant_id from cart_items where cart_id=$1', [cart])).rows;
  eq(rows.some(row => row.variant_id === alternate.id && row.selected_vehicle?.year === 2017 && row.quantity === 2), true);
  eq(rows.some(row => row.variant_id === variant.id && row.selected_vehicle?.has_camera === false), true);
  for (const role of ['anon', 'authenticated']) {
    for (const signature of ['commerce_cart_add(uuid,uuid,text,uuid,uuid,integer,jsonb,boolean)',
      'commerce_cart_update(uuid,uuid,text,uuid,uuid,integer,boolean)', 'commerce_cart_claim(uuid,uuid,text,boolean)']) {
      eq((await one('select has_function_privilege($1,$2,\'execute\') allowed', [role, 'public.' + signature])).allowed, false);
    }
  }
  eq((await one('select stock from product_variants where id=$1', [variant.id])).stock, 3);
  eq((await one('select stock from products where id=$1', [legacy])).stock, 3);
  eq((await one('select count(*)::integer n from orders')).n, 0);
  console.log(JSON.stringify({checks, result: 'passed', engine: 'PostgreSQL/PGlite', network: false, concurrency: 'serialized scenarios, not multiple connections'}));
} catch (error) {
  console.error(JSON.stringify({result: 'failed', checks, message: error.message, where: error.where, detail: error.detail}));
  process.exitCode = 1;
} finally { await db.close(); }
