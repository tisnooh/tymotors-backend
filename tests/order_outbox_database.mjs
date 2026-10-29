// Actual disposable SQL transactions/roles; no provider or email transport.
import assert from 'node:assert/strict';

export async function testOrderOutbox(db,admin,customer,product) {
  let checks=0;
  const one=async (sql,p=[]) => (await db.query(sql,p)).rows[0];
  const eq=(a,b) => {assert.deepEqual(a,b);checks++;};
  const rejects=async (sql,p,re) => {await assert.rejects(db.query(sql,p),re);checks++;};
  const transition='select admin_update_order_fulfillment($1,$2,$3,null,null,null,$4) r';
  const claim='select admin_claim_order_notification($1,$2,$3,$4) r';
  const finish='select complete_order_notification($1,$2,$3,$4) r';
  const uuid=async () => (await one('select gen_random_uuid() id')).id;
  async function seed(changes={}) {
    const o=await one("insert into orders(order_number,subtotal_cents,total_cents,customer_email) values('OUTBOX-'||gen_random_uuid(),1000,1000,'frozen@example.test') returning *");
    await db.query("insert into order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents) values($1,$2,'Frozen fixture','test-product','FROZEN',1,1000)",[o.id,product]);
    const values={payment_status:'paid',status:'paid',...changes};
    const cols=Object.keys(values);
    await db.query(`update orders set ${cols.map((k,i)=>`${k}=$${i+2}`).join(',')} where id=$1`,[o.id,...Object.values(values)]);
    return one('select * from orders where id=$1',[o.id]);
  }
  const queued=async o => (await one(transition,[admin,o.id,'processing',o.updated_at])).r;
  const log=async id => one('select * from email_logs where id=$1',[id]);
  // A failure *during enqueue* rolls back the order, tracking and audit, not only the log.
  const rollback=await seed();
  await db.exec(`create function public.qa_reject_outbox() returns trigger language plpgsql as $$
    begin if new.event_snapshot is not null then raise exception 'Injected outbox failure'; end if; return new; end $$;
    create trigger qa_outbox before insert on email_logs for each row execute function public.qa_reject_outbox();`);
  await rejects(transition,[admin,rollback.id,'processing',rollback.updated_at],/Injected outbox failure/);
  eq(await one('select * from orders where id=$1',[rollback.id]),rollback);
  eq((await one('select count(*) n from admin_audit where resource=$1',[rollback.id])).n,0);
  eq((await one("select count(*) n from email_logs where order_id=$1 and email_type='order_processing'",[rollback.id])).n,0);
  eq((await one("select count(*) n from email_logs where order_id=$1 and email_type='payment_confirmed'",[rollback.id])).n,1);
  await db.exec('drop trigger qa_outbox on email_logs; drop function public.qa_reject_outbox()');

  const o=await seed(), result=await queued(o), id=result.notification_log_id;
  assert.ok(id);checks++;
  const frozen=await log(id);
  eq(frozen.delivery_state,'pending');eq(frozen.status,'queued');
  eq(frozen.idempotency_key,`order:${o.id}:order_processing:once`);
  eq(frozen.event_snapshot.order.total_cents,1000);
  eq(frozen.event_snapshot.items[0].sku,'FROZEN');
  eq('shipping_address' in frozen.event_snapshot.order,false);
  // Simulate stop after order COMMIT, before any transport: the event survives.
  eq((await one(transition,[admin,o.id,'processing',o.updated_at])).r.updated,false);
  eq((await one("select count(*) n from email_logs where order_id=$1 and email_type='order_processing'",[o.id])).n,1);
  await db.query("update orders set customer_email='changed@example.test',total_cents=2000 where id=$1",[o.id]);
  await db.query("update order_items set product_name='Changed',sku='CHANGED' where order_id=$1",[o.id]);
  eq((await log(id)).recipient,'frozen@example.test');
  eq((await log(id)).event_snapshot,frozen.event_snapshot);
  for (const [column,value] of [['recipient','changed@example.test'],['idempotency_key','new-key'],['event_snapshot',{}]])
    await rejects(`update email_logs set ${column}=$2 where id=$1`,[id,value],/immutable/);
  const token=await uuid();
  await rejects(claim,[customer,id,token,true],/Admin role/);
  eq((await one(claim,[admin,id,token,false])).r,{claimed:false,state:'blocked'});
  eq((await log(id)).delivery_token,null);
  eq((await one(claim,[admin,id,token,true])).r,{claimed:true,state:'claimed'});
  // Identical-token replay and a competing worker both lose; never authorize transport twice.
  eq((await one(claim,[admin,id,token,true])).r,{claimed:false,state:'claimed'});
  eq((await one(claim,[admin,id,await uuid(),true])).r,{claimed:false,state:'claimed'});
  eq((await one(finish,[id,await uuid(),'sent','wrong'])).r.completed,false);
  eq((await one(finish,[id,token,'sent','fixture-provider'])).r,{completed:true,state:'sent'});
  eq((await log(id)).provider_message_id,'fixture-provider');
  eq((await one(finish,[id,token,'unknown',null])).r.completed,false);
  eq((await one(claim,[admin,id,await uuid(),true])).r,{claimed:false,state:'sent'});
  await rejects("update email_logs set delivery_state='pending',status='queued' where id=$1",[id],/immutable/);
  await rejects('delete from email_logs where id=$1',[id],/cannot be deleted/);
  await rejects('truncate email_logs',[],/cannot be truncated/);
  eq((await log(id)).delivery_state,'sent');

  const uncertain=await queued(await seed()), uncertainToken=await uuid();
  await one(claim,[admin,uncertain.notification_log_id,uncertainToken,true]);
  await one(finish,[uncertain.notification_log_id,uncertainToken,'unknown',null]);
  eq((await one(claim,[admin,uncertain.notification_log_id,await uuid(),true])).r,{claimed:false,state:'unknown'});
  await rejects(finish,[uncertain.notification_log_id,uncertainToken,'pending',null],/Invalid notification/);

  for (const status of ['queued','failed','sent']) {
    const legacy=await seed();
    const row=await one("insert into email_logs(order_id,recipient,email_type,status,idempotency_key) values($1,'legacy@example.test','order_processing',$2,$3) returning id",
      [legacy.id,status,`order:${legacy.id}:order_processing:once`]);
    eq((await queued(legacy)).notification_log_id,row.id);
    eq((await log(row.id)).event_snapshot,null);
    eq((await one(claim,[admin,row.id,await uuid(),true])).r,{claimed:false,state:status==='sent'?'sent':'legacy_review'});
  }
  // No test mail, including cancellation (allowed for a test order).
  const test=await seed({is_test:true});
  eq((await one(transition,[admin,test.id,'cancelled',test.updated_at])).r.notification_log_id,null);
  eq((await one('select count(*) n from email_logs where order_id=$1',[test.id])).n,0);
  for (const mutation of ["is_test=true","fulfillment_status='cancelled'", "payment_status='unpaid'",
    "payment_status='refunded',status='refunded'", "status='cancelled'", "refunded_amount_cents=100"]) {
    const changed=await seed(), q=await queued(changed);
    await db.query(`update orders set ${mutation} where id=$1`,[changed.id]);
    eq((await one(claim,[admin,q.notification_log_id,await uuid(),true])).r,{claimed:false,state:'unknown'});
  }
  // Cancellation remains true after a separate refund, without promising a new refund.
  const cancelled=await seed();
  const cq=(await one(transition,[admin,cancelled.id,'cancelled',cancelled.updated_at])).r;
  await db.query("update orders set payment_status='refunded',status='refunded',refunded_amount_cents=1000 where id=$1",[cancelled.id]);
  eq((await one(claim,[admin,cq.notification_log_id,await uuid(),true])).r,{claimed:true,state:'claimed'});
  // Old logged event remains private and non-sendable after FK detachment.
  const detached=await seed(), dq=await queued(detached);
  await db.query('update email_logs set order_id=null where id=$1',[dq.notification_log_id]);
  eq((await one(claim,[admin,dq.notification_log_id,await uuid(),true])).r,{claimed:false,state:'unknown'});
  for (const signature of ['public.admin_claim_order_notification(uuid,uuid,uuid,boolean)',
    'public.complete_order_notification(uuid,uuid,text,text)','private.enqueue_order_notification(uuid,text)']) {
    for (const role of ['anon','authenticated','service_role'])
      eq((await one("select has_function_privilege($1,$2,'EXECUTE') allowed",[role,signature])).allowed,role==='service_role');
  }
  await db.exec('begin; set local role authenticated');
  await db.query("select set_config('request.jwt.claim.sub',$1,true)",[customer]);
  eq((await db.query('select event_snapshot from email_logs where id=$1',[id])).rows.length,0);
  await rejects("update email_logs set status='sent' where id=$1",[id],/permission denied/);
  await db.exec('rollback');
  return checks;
}
