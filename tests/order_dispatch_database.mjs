// Disposable engine only. No provider, credentials, real orders or mail.
import assert from 'node:assert/strict';

export async function testOrderDispatch(db, admin, customer, product) {
  let checks = 0;
  const one = async (s,p=[]) => (await db.query(s,p)).rows[0];
  const ok = (a,b) => { assert.deepEqual(a,b); checks++; };
  const rejects = async (s,p,re) => { await assert.rejects(db.query(s,p),re); checks++; };
  const rpc = 'select admin_update_order_fulfillment($1,$2,$3,$4,$5,$6,$7) result';
  const legacy = 'select admin_update_order($1,$2,$3,$4,$5) result';
  async function seed(changes={}) {
    const o=await one("insert into orders(order_number,subtotal_cents,total_cents,customer_email) values('DISPATCH-FIXTURE-'||gen_random_uuid(),1000,1000,'client@example.test') returning *");
    await db.query("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents) values($1,$2,'Fixture','test-product','TEST-001',1,1000)",[o.id,product]);
    const values={payment_status:'paid',status:'paid',...changes};
    const cols=Object.keys(values);
    await db.query(`update orders set ${cols.map((k,i)=>`${k}=$${i+2}`).join(',')} where id=$1`,[o.id,...Object.values(values)]);
    return await one('select * from orders where id=$1',[o.id]);
  }
  const args=(o,status='shipped',tracking='FIXTURE-TRACK',carrier='Fixture carrier',url='https://carrier.example.test/track') =>
    [admin,o.id,status,tracking,carrier,url,o.updated_at];
  async function unchanged(o,params,re) {
    const counts=await one('select (select count(*) from admin_audit where resource=$1) audit,(select count(*) from order_tracking_events where order_id=$2) events',[o.id,o.id]);
    await rejects(rpc,params,re);
    ok(await one('select * from orders where id=$1',[o.id]),o);
    ok(await one('select (select count(*) from admin_audit where resource=$1) audit,(select count(*) from order_tracking_events where order_id=$2) events',[o.id,o.id]),counts);
  }
  for (const [changes,re] of [
    [{is_test:true},/simulation-only/], [{payment_status:'unpaid'},/Payment required/],
    [{payment_status:'refunded',status:'refunded'},/Payment required/],
    [{status:'cancelled'},/Payment required/], [{refunded_amount_cents:100},/Payment required/],
    [{requires_compatibility_review:true},/Compatibility review/],
  ]) {
    const o=await seed(changes);
    await unchanged(o,args(o),re);
    await rejects(legacy,[admin,o.id,'shipped','FIXTURE-TRACK',o.updated_at],re);
  }
  const testOrder=await seed({is_test:true});
  for (const status of ['processing','delivered'])
    await unchanged(testOrder,args(testOrder,status),/simulation-only/);
  const cart=await one("insert into carts(guest_session_id) values('dispatch_fixture_owner') returning *");
  const source={cart,country:'FR',mode:'fixture',postal_code:'75001'};
  const quote=await one(`insert into commerce_quotes(cart_id,owner_guest_session,country,mode,destination,source_context,payload,
    subtotal_cents,shipping_cents,tax_cents,total_cents,expires_at,request_key)
    values($1,'dispatch_fixture_owner','FR','fixture',$2,$3,'{"currency":"EUR"}',1000,0,0,1000,now()+interval '30 minutes',
      gen_random_uuid()) returning id`,[cart.id,{country:'FR',postal_code:'75001'},source]);
  const quotedRow=await one(`insert into orders(order_number,subtotal_cents,total_cents,customer_email,
    payment_status,status,commerce_quote_id) values('DISPATCH-QUOTED-'||gen_random_uuid(),1000,1000,
    'client@example.test','paid','paid',$1) returning *`,[quote.id]);
  await unchanged(quotedRow,args(quotedRow),/verified multi-parcel/);
  const cancelled=await seed({fulfillment_status:'cancelled',status:'cancelled'});
  ok((await one(rpc,args(cancelled,'cancelled',null,null,null))).result.updated,false);
  await unchanged(cancelled,args(cancelled,'requires_review'),/This order is closed/);
  const o=await seed();
  await rejects(legacy,[admin,o.id,'shipped','FIXTURE-TRACK',o.updated_at],/Tracking number required with carrier/);
  await unchanged(o,[customer,...args(o).slice(1)],/Admin role/);
  await unchanged(o,args(o,'delivered'),/Ship the order first/);
  await unchanged(o,args(o,'shipped',null),/Tracking number/);
  await unchanged(o,args(o,'shipped','FIXTURE-TRACK',null),/Tracking number/);
  await unchanged(o,args(o,'shipped','SIM-123'),/Simulated tracking/);
  await unchanged(o,args(o,'shipped','FIXTURE-TRACK','Fixture carrier','https://user:secret@carrier.example.test/'),/Invalid shipment/);
  await unchanged(o,args(o,'shipped','FIXTURE\nTRACK'),/Invalid shipment/);
  await unchanged(o,[...args(o).slice(0,6),null],/changed. Reload/);
  await unchanged(o,[...args(o).slice(0,6),'2000-01-01T00:00:00Z'],/changed. Reload/);
  // Force an error after the row UPDATE: the row, dates, audit and event roll back.
  await db.exec(`create function public.qa_reject_dispatch_audit() returns trigger language plpgsql as $$
    begin if new.action='order.update' then raise exception 'Injected audit failure'; end if; return new; end $$;
    create trigger qa_dispatch_audit before insert on public.admin_audit for each row execute function public.qa_reject_dispatch_audit();`);
  await unchanged(o,args(o),/Injected audit failure/);
  await db.exec('drop trigger qa_dispatch_audit on public.admin_audit; drop function public.qa_reject_dispatch_audit()');

  const first=(await one(rpc,args(o))).result;
  ok(first.status_changed,true); ok(first.notification_kind,'order_shipped');
  const shipped=await one('select * from orders where id=$1',[o.id]);
  ok(shipped.fulfillment_status,'shipped'); ok(shipped.tracking_number,'FIXTURE-TRACK');
  ok(shipped.carrier,'Fixture carrier'); ok(shipped.tracking_url,'https://carrier.example.test/track');
  assert.ok(shipped.shipped_at); checks++;
  // Identical response-loss replay succeeds without a second mutation or email.
  const replay=(await one(rpc,args(o))).result;
  ok(replay.updated,false); ok(replay.notification_kind,null);
  ok(await one('select * from orders where id=$1',[o.id]),shipped);
  await unchanged(shipped,args(shipped,'shipped','OTHER'),/tracking is locked/);
  await unchanged(shipped,args(shipped,'shipped','FIXTURE-TRACK','Other carrier'),/tracking is locked/);
  await unchanged(shipped,args(shipped,'shipped','FIXTURE-TRACK','Fixture carrier','https://other.example.test/'),/tracking is locked/);
  await unchanged(shipped,args(shipped,'processing'),/Invalid transition/);
  // A stale competing update cannot overwrite the winning shipment.
  await unchanged(shipped,args(o,'delivered'),/changed. Reload/);
  const delivered=(await one(rpc,args(shipped,'delivered',null,null,null))).result;
  ok(delivered.notification_kind,'order_delivered');
  const final=await one('select * from orders where id=$1',[o.id]);
  ok(final.tracking_number,shipped.tracking_number); ok(final.carrier,shipped.carrier);
  ok(final.tracking_url,shipped.tracking_url); assert.ok(final.delivered_at); checks++;
  const event=await one("select * from order_tracking_events where order_id=$1 and event_key='order_delivered'",[o.id]);
  ok(event.source,'admin'); ok(event.metadata.manual_confirmation,true);
  assert.match(event.description,/manuellement/); checks++;
  ok((await one(legacy,[admin,o.id,'delivered',null,shipped.updated_at])).result.updated,false);
  ok((await one("select count(*) n from order_tracking_events where order_id=$1 and event_key='order_delivered'",[o.id])).n,1);
  await unchanged(final,args(final,'processing'),/This order is closed/);
  await unchanged(final,args(final,'delivered','REPLACED'),/tracking is locked/);
  for (const signature of ['public.admin_update_order(uuid,uuid,text,text,timestamptz)',
    'public.admin_update_order_fulfillment(uuid,uuid,text,text,text,text,timestamptz)']) {
    for (const role of ['anon','authenticated','service_role'])
      ok((await one('select has_function_privilege($1,$2,\'EXECUTE\') allowed',[role,signature])).allowed,role==='service_role');
  }
  return checks;
}
