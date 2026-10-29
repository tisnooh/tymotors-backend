// Upgrade a populated historical schema, never a hosted database.
import { readFile, access, readdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
let runtime;
for (const path of ['../tools/sql-tests/node_modules/@electric-sql/pglite/dist/index.js',
                   '../../../backend/.admin-test-runtime/node_modules/@electric-sql/pglite/dist/index.js']) {
  const url = new URL(path, import.meta.url);
  try { await access(url); runtime = url.href; break; } catch {}
}
if (!runtime) throw new Error('Pinned local PGlite runtime required');
const { PGlite } = await import(runtime);
const db = new PGlite();
try {
  await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    create table auth.users(id uuid primary key,email text,raw_user_meta_data jsonb default '{}');
    create table auth.sessions(id uuid primary key,user_id uuid,not_after timestamptz);
    create function auth.uid() returns uuid language sql stable as $$
      select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to anon,authenticated,service_role;
    grant execute on function auth.uid() to anon,authenticated,service_role;`);
  const fixture = await readFile(new URL('./admin_database.mjs', import.meta.url), 'utf8');
  const files = [...fixture.matchAll(/supabase\/migrations\/([0-9]+_[A-Za-z0-9_]+\.sql)/g)]
    .map(match => match[1]);
  assert.equal(new Set(files).size, files.length, 'Duplicate migration in fixture');
  const boundary = files.indexOf('20261013063630_sandbox_catalog_orders.sql');
  assert.ok(boundary > 0, 'Historical boundary required');
  async function apply(file) {
    const source = await readFile(new URL('../supabase/migrations/' + file, import.meta.url), 'utf8');
    await db.exec(source.replace('create extension if not exists pgcrypto;', '-- built-in gen_random_uuid'));
  }
  for (const file of files.slice(0, boundary + 1)) await apply(file);
  await db.exec(`insert into categories(slug,name) values('upgrade-fixture','Upgrade fixture');
    insert into products(slug,sku,name,description,category_id,price_cents,stock,status)
      select 'upgrade-'||n,'UPGRADE-'||n,'Synthetic historical product','Historical description',
        (select id from categories where slug='upgrade-fixture'),12345,0,'draft'
      from generate_series(1,40) n;
    insert into product_images(product_id,url,image_type)
      select id,'https://example.test/unchanged/'||sku||'.jpg','main' from products;
    insert into orders(order_number,subtotal_cents,total_cents,is_test,payment_status,status,
      stripe_session_id,stripe_payment_intent_id,paid_at)
      values('TY-SYNTHETIC-HISTORICAL',12345,12345,true,'paid','paid',
        'cs_test_HistoricalUpgrade','pi_HistoricalUpgrade',now());
    insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents,image_url)
      select o.id,p.id,p.name,p.slug,p.sku,1,p.price_cents,i.url
      from orders o,products p join product_images i on i.product_id=p.id where p.sku='UPGRADE-1';
    insert into stripe_events(event_id,event_type,status,completed_at)
      values('evt_HistoricalUpgrade','checkout.session.completed','completed',now());`);
  const tables = ['products','product_images','orders','order_items','stripe_events'];
  const snapshots = {};
  for (const table of tables) snapshots[table] = (await db.query(`select * from ${table} order by 1`)).rows;
  const pending = files.slice(boundary + 1);
  const repositoryPending = (await readdir(new URL('../supabase/migrations/', import.meta.url)))
    .filter(file => file.endsWith('.sql') && file > files[boundary]).sort();
  assert.deepEqual(pending, repositoryPending, 'Fixture does not cover the complete pending migration chain');
  for (const file of pending) await apply(file);
  let preserved = 0;
  for (const table of tables) {
    const rows = (await db.query(`select * from ${table} order by 1`)).rows;
    assert.equal(rows.length, snapshots[table].length, table + ' row count changed');
    for (let index=0; index<rows.length; index++) {
      for (const [key,value] of Object.entries(snapshots[table][index])) {
        assert.deepEqual(rows[index][key],value, table + '.' + key + ' changed'); preserved++;
      }
    }
  }
  const historic = (await db.query("select stripe_account_id,commerce_quote_id from orders where order_number='TY-SYNTHETIC-HISTORICAL'")).rows[0];
  assert.equal(historic.stripe_account_id,null);
  assert.equal(historic.commerce_quote_id,null);
  assert.equal((await db.query('select commerce_live_enabled from shop_settings')).rows[0].commerce_live_enabled,false);
  for (const table of ['product_variants','supplier_offers','commerce_payment_sessions','commerce_fulfillment_tasks']) {
    assert.equal((await db.query(`select count(*)::int n from ${table}`)).rows[0].n,0,'Invented backfill: '+table);
  }
  console.log(JSON.stringify({result:'PASS',pending_migrations:pending.length,
    preserved_fields:preserved,synthetic_products:40,historical_orders:1,
    live_enabled:false,remote_writes:0,limitations:'PGlite; not a hosted-schema clone or native concurrency test'}));
} finally { await db.close(); }
