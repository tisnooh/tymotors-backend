-- Durable manual-fulfillment notifications. No historical backfill, mail worker,
-- provider call or production activation. Reuse the existing private email log.
begin;
alter table public.email_logs
  add column event_snapshot jsonb,
  add column delivery_state text,
  add column delivery_token uuid,
  add column delivery_claimed_at timestamptz,
  add constraint email_logs_outbox_shape check (
    (event_snapshot is null and delivery_state is null and delivery_token is null and delivery_claimed_at is null)
    or (event_snapshot is not null and jsonb_typeof(event_snapshot)='object'
      and coalesce(event_snapshot->>'version'='1',false)
      and delivery_state is not null and delivery_state in ('pending','blocked','claimed','unknown','sent')
      and email_type in ('order_processing','order_shipped','order_delivered','order_cancelled')
      and status=case delivery_state when 'sent' then 'sent' when 'blocked' then 'failed'
        when 'unknown' then 'failed' else 'queued' end
      and ((delivery_token is null and delivery_claimed_at is null and delivery_state in ('pending','blocked','unknown'))
        or (delivery_token is not null and delivery_claimed_at is not null and delivery_state in ('claimed','unknown','sent')))));

create function private.guard_order_notification() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if old.event_snapshot is not null then
    if new.id is distinct from old.id or new.created_at is distinct from old.created_at
      or new.event_snapshot is distinct from old.event_snapshot or new.recipient is distinct from old.recipient
      or new.email_type is distinct from old.email_type or new.idempotency_key is distinct from old.idempotency_key
      or (new.order_id is distinct from old.order_id and new.order_id is not null)
      or (old.delivery_token is not null and (new.delivery_token is distinct from old.delivery_token
        or new.delivery_claimed_at is distinct from old.delivery_claimed_at))
      or (old.delivery_state in ('sent','unknown') and (new.provider_message_id is distinct from old.provider_message_id
        or new.sent_at is distinct from old.sent_at or new.error_message is distinct from old.error_message))
      or not (new.delivery_state=old.delivery_state
        or (old.delivery_state in ('pending','blocked') and new.delivery_state in ('blocked','claimed','unknown'))
        or (old.delivery_state='claimed' and new.delivery_state in ('sent','unknown')))
    then raise exception 'Order notification snapshot and delivery history are immutable'; end if;
  elsif new.event_snapshot is not null then
    raise exception 'Legacy email outcome requires manual review, not conversion';
  end if;
  return new;
end $$;
create trigger email_logs_outbox_immutable before update on public.email_logs
for each row execute function private.guard_order_notification();

-- Keep idempotency tombstones. No unreviewed retention/backfill policy here.
create function private.guard_order_notification_removal() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if tg_op='TRUNCATE' then
    if exists(select 1 from public.email_logs where event_snapshot is not null) then
      raise exception 'Order notification history cannot be truncated';
    end if;
    return null;
  end if;
  if old.event_snapshot is not null then raise exception 'Order notification history cannot be deleted'; end if;
  return old;
end $$;
create trigger email_logs_outbox_delete before delete on public.email_logs
for each row execute function private.guard_order_notification_removal();
create trigger email_logs_outbox_truncate before truncate on public.email_logs
for each statement execute function private.guard_order_notification_removal();

create function private.enqueue_order_notification(p_order uuid,p_kind text) returns uuid
language plpgsql security invoker set search_path='' as $$
declare o public.orders; snapshot jsonb; log_id uuid; key text;
begin
  if p_kind is null then return null; end if;
  if p_kind not in ('order_processing','order_shipped','order_delivered','order_cancelled')
    then raise exception 'Unsupported order notification'; end if;
  select * into o from public.orders where id=p_order;
  if not found or o.is_test then return null; end if;
  key:='order:'||o.id::text||':'||p_kind||':once';
  select jsonb_build_object('version',1,'order',jsonb_build_object(
    'id',o.id,'order_number',o.order_number,'payment_status',o.payment_status,
    'fulfillment_status',o.fulfillment_status,'carrier',o.carrier,'tracking_number',o.tracking_number,
    'tracking_url',o.tracking_url,'currency',o.currency,'subtotal_cents',o.subtotal_cents,
    'shipping_amount_cents',o.shipping_amount_cents,'tax_amount_cents',o.tax_amount_cents,'total_cents',o.total_cents),
    'items',coalesce((select jsonb_agg(jsonb_build_object('product_name',i.product_name,'quantity',i.quantity,
      'unit_amount_cents',i.unit_amount_cents,'sku',i.sku,'selected_vehicle',i.selected_vehicle,'image_url',i.image_url)
      order by i.created_at,i.id) from public.order_items i where i.order_id=o.id),'[]'::jsonb)) into snapshot;
  insert into public.email_logs(user_id,order_id,recipient,email_type,status,idempotency_key,metadata,event_snapshot,delivery_state)
  values(o.user_id,o.id,coalesce(o.customer_email,''),p_kind,'queued',key,
    jsonb_build_object('order_number',o.order_number,'source','atomic_manual_fulfillment'),snapshot,'pending')
  on conflict(idempotency_key) do nothing returning id into log_id;
  if log_id is null then select id into log_id from public.email_logs where idempotency_key=key; end if;
  return log_id;
end $$;

create function public.admin_claim_order_notification(p_actor uuid,p_id uuid,p_token uuid,p_ready boolean)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e public.email_logs; o public.orders; target uuid;
begin
  perform private.assert_admin(p_actor);
  if p_token is null or p_ready is null then raise exception 'Notification claim parameters required'; end if;
  -- Same lock order as fulfillment: order, then log. Never log -> order.
  select order_id into target from public.email_logs where id=p_id;
  select * into o from public.orders where id=target for update;
  select * into e from public.email_logs where id=p_id for update;
  perform private.assert_admin(p_actor);
  if e.id is null then raise exception 'Notification not found'; end if;
  if e.event_snapshot is null then
    return jsonb_build_object('claimed',false,'state',case when e.status='sent' then 'sent' else 'legacy_review' end);
  end if;
  if e.delivery_state not in ('pending','blocked') then
    return jsonb_build_object('claimed',false,'state',e.delivery_state);
  end if;
  if o.id is null or o.is_test or e.order_id is distinct from o.id
    or e.event_snapshot->'order'->>'id' is distinct from o.id::text
    or e.event_snapshot->'order'->>'fulfillment_status' is distinct from o.fulfillment_status::text
    or (e.email_type<>'order_cancelled' and (o.payment_status<>'paid'
      or o.status in ('cancelled','refunded') or o.refunded_amount_cents<>0)) then
    update public.email_logs set delivery_state='unknown',status='failed',
      error_message='Order changed or unavailable; manual review required' where id=e.id;
    return jsonb_build_object('claimed',false,'state','unknown');
  end if;
  if not p_ready then
    update public.email_logs set delivery_state='blocked',status='failed',
      error_message='Email configuration or snapshot validation unavailable; no transport attempted' where id=e.id;
    return jsonb_build_object('claimed',false,'state','blocked');
  end if;
  update public.email_logs set delivery_state='claimed',status='queued',delivery_token=p_token,
    delivery_claimed_at=clock_timestamp(),error_message=null where id=e.id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'email.outbox_claim',e.id::text,jsonb_build_object('order_id',e.order_id,'email_type',e.email_type));
  return jsonb_build_object('claimed',true,'state','claimed');
end $$;

create function public.complete_order_notification(p_id uuid,p_token uuid,p_outcome text,p_provider_id text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e public.email_logs;
begin
  if p_token is null or p_outcome is null or p_outcome not in ('sent','unknown')
    or length(p_provider_id)>500 then raise exception 'Invalid notification outcome'; end if;
  update public.email_logs set delivery_state=p_outcome,status=case when p_outcome='sent' then 'sent' else 'failed' end,
    provider_message_id=case when p_outcome='sent' then p_provider_id else null end,
    sent_at=case when p_outcome='sent' then clock_timestamp() else null end,
    error_message=case when p_outcome='unknown' then 'Delivery outcome unknown; inspect provider history before any action' end
  where id=p_id and event_snapshot is not null and delivery_state='claimed' and delivery_token=p_token
  returning * into e;
  return jsonb_build_object('completed',e.id is not null,'state',e.delivery_state);
end $$;

-- Fail closed if the preceding audited function no longer has this exact anchor.
do $$
declare body text; anchor text := $anchor$return jsonb_build_object('updated',true,'status_changed',changed,'notification_kind',email_kind,'updated_at',saved.updated_at);$anchor$;
begin
  select pg_get_functiondef('public.admin_update_order_fulfillment(uuid,uuid,text,text,text,text,timestamptz)'::regprocedure) into body;
  if position(anchor in body)=0 then raise exception 'Fulfillment outbox migration anchor missing'; end if;
  execute replace(body,anchor,$replace$return jsonb_build_object('updated',true,'status_changed',changed,'notification_kind',email_kind,
    'notification_log_id',private.enqueue_order_notification(saved.id,email_kind),'updated_at',saved.updated_at);$replace$);
end $$;

revoke all on function private.guard_order_notification(),private.guard_order_notification_removal(),private.enqueue_order_notification(uuid,text),
  public.admin_claim_order_notification(uuid,uuid,uuid,boolean),public.complete_order_notification(uuid,uuid,text,text)
  from public,anon,authenticated;
grant execute on function private.guard_order_notification(),private.guard_order_notification_removal(),private.enqueue_order_notification(uuid,text),
  public.admin_claim_order_notification(uuid,uuid,uuid,boolean),public.complete_order_notification(uuid,uuid,text,text) to service_role;
commit;
