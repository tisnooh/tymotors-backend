-- Financial intentions in the EXISTING outbox. No backfill, transport, account
-- authentication, production activation or supplier effect.
begin;

alter table public.email_logs drop constraint email_logs_outbox_shape;
alter table public.email_logs add constraint email_logs_outbox_shape check (
  (event_snapshot is null and delivery_state is null and delivery_token is null and delivery_claimed_at is null)
  or (event_snapshot is not null and jsonb_typeof(event_snapshot)='object'
    and coalesce(event_snapshot->>'version'='1',false)
    and delivery_state is not null and delivery_state in ('pending','blocked','claimed','unknown','sent')
    and email_type in ('order_processing','order_shipped','order_delivered','order_cancelled','payment_confirmed','refund_confirmed')
    and status=case delivery_state when 'sent' then 'sent' when 'blocked' then 'failed'
      when 'unknown' then 'failed' else 'queued' end
    and ((delivery_token is null and delivery_claimed_at is null and delivery_state in ('pending','blocked','unknown'))
      or (delivery_token is not null and delivery_claimed_at is not null and delivery_state in ('claimed','unknown','sent')))));

create or replace function private.enqueue_order_notification(p_order uuid,p_kind text) returns uuid
language plpgsql security invoker set search_path='' as $$
declare o public.orders; snapshot jsonb; log_id uuid; key text; financial boolean;
begin
  if p_kind is null then return null; end if;
  if p_kind not in ('order_processing','order_shipped','order_delivered','order_cancelled','payment_confirmed','refund_confirmed')
    then raise exception 'Unsupported order notification'; end if;
  select * into o from public.orders where id=p_order;
  if not found or o.is_test then return null; end if;
  financial:=p_kind in ('payment_confirmed','refund_confirmed');
  key:='order:'||o.id::text||':'||p_kind||':'||case when p_kind='refund_confirmed'
    then o.refunded_amount_cents::text else 'once' end;
  select jsonb_build_object('version',1,'order',jsonb_build_object(
    'id',o.id,'order_number',o.order_number,'payment_status',o.payment_status,
    'fulfillment_status',o.fulfillment_status,'carrier',o.carrier,'tracking_number',o.tracking_number,
    'tracking_url',o.tracking_url,'currency',o.currency,'subtotal_cents',o.subtotal_cents,
    'shipping_amount_cents',o.shipping_amount_cents,'tax_amount_cents',o.tax_amount_cents,'total_cents',o.total_cents),
    'items',coalesce((select jsonb_agg(jsonb_build_object('product_name',i.product_name,'quantity',i.quantity,
      'unit_amount_cents',i.unit_amount_cents,'sku',i.sku,'selected_vehicle',i.selected_vehicle,'image_url',i.image_url)
      order by i.created_at,i.id) from public.order_items i where i.order_id=o.id),'[]'::jsonb)) into snapshot;
  if financial then
    snapshot:=jsonb_set(snapshot,'{order}',snapshot->'order'||jsonb_build_object(
      'is_test',o.is_test,'status',o.status,'owner_user_id',o.user_id,'refunded_amount_cents',o.refunded_amount_cents,
      'stripe_payment_intent_id',o.stripe_payment_intent_id,'financial_review_required',o.financial_review_required));
    snapshot:=snapshot||jsonb_build_object('financial',jsonb_build_object(
      'kind',p_kind,'refunded_amount_cents',o.refunded_amount_cents,'total_cents',o.total_cents,
      'payment_intent_id',o.stripe_payment_intent_id,'occurred_at',clock_timestamp()));
  end if;
  insert into public.email_logs(user_id,order_id,recipient,email_type,status,idempotency_key,metadata,event_snapshot,delivery_state)
  values(o.user_id,o.id,coalesce(o.customer_email,''),p_kind,'queued',key,
    jsonb_build_object('order_number',o.order_number,'source',case when financial then 'atomic_financial_transition'
      else 'atomic_manual_fulfillment' end),snapshot,'pending')
  on conflict(idempotency_key) do nothing returning id into log_id;
  -- A historical collision is retained as-is: never convert, relabel or resend.
  if log_id is null then select id into log_id from public.email_logs where idempotency_key=key; end if;
  return log_id;
end $$;

create function private.enqueue_financial_order_notification() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.is_test then return new; end if;
  if new.payment_status='paid' and old.payment_status not in ('paid','refunded') then
    perform private.enqueue_order_notification(new.id,'payment_confirmed');
  end if;
  if new.refunded_amount_cents>old.refunded_amount_cents then
    perform private.enqueue_order_notification(new.id,'refund_confirmed');
  end if;
  return new;
end $$;
create trigger orders_financial_notification_outbox after update of payment_status,refunded_amount_cents on public.orders
  for each row execute function private.enqueue_financial_order_notification();

create function private.financial_order_notification_matches(e public.email_logs,o public.orders) returns boolean
language plpgsql immutable security invoker set search_path='' as $$
declare frozen jsonb:=e.event_snapshot->'order'; f jsonb:=e.event_snapshot->'financial';
begin
  if o.id is null or o.is_test or o.financial_review_required or e.order_id is distinct from o.id
    or e.user_id is distinct from o.user_id
    or frozen->'owner_user_id' is distinct from coalesce(to_jsonb(o.user_id),'null'::jsonb)
    or o.currency<>'EUR' or o.total_cents<=0
    or o.subtotal_cents::bigint+o.shipping_amount_cents::bigint<>o.total_cents::bigint
    or o.tax_amount_cents>o.total_cents or o.refunded_amount_cents<0 or o.refunded_amount_cents>o.total_cents
    or e.email_type not in ('payment_confirmed','refund_confirmed')
    or e.event_snapshot->'version' is distinct from '1'::jsonb
    or jsonb_typeof(f) is distinct from 'object' or jsonb_typeof(frozen) is distinct from 'object'
    or f->>'kind' is distinct from e.email_type or frozen->>'id' is distinct from o.id::text
    or frozen->'is_test' is distinct from 'false'::jsonb
    or frozen->'financial_review_required' is distinct from 'false'::jsonb
    or o.stripe_payment_intent_id is null or o.stripe_payment_intent_id !~ '^pi_[A-Za-z0-9_]{1,240}$'
    or f->>'payment_intent_id' is distinct from o.stripe_payment_intent_id
    or frozen->>'stripe_payment_intent_id' is distinct from o.stripe_payment_intent_id
    or f->'total_cents' is distinct from to_jsonb(o.total_cents)
    or frozen->'total_cents' is distinct from to_jsonb(o.total_cents)
    or frozen->'subtotal_cents' is distinct from to_jsonb(o.subtotal_cents)
    or frozen->'shipping_amount_cents' is distinct from to_jsonb(o.shipping_amount_cents)
    or frozen->'tax_amount_cents' is distinct from to_jsonb(o.tax_amount_cents)
    or frozen->>'currency' is distinct from o.currency then return false; end if;
  if e.email_type='payment_confirmed' then
    return o.payment_status='paid' and o.status not in ('cancelled','refunded') and o.refunded_amount_cents=0
      and frozen->>'payment_status'='paid' and frozen->>'status' not in ('cancelled','refunded')
      and frozen->'refunded_amount_cents'='0'::jsonb and f->'refunded_amount_cents'='0'::jsonb
      and e.idempotency_key='order:'||o.id::text||':payment_confirmed:once';
  end if;
  return o.refunded_amount_cents>0 and o.refunded_amount_cents<=o.total_cents
    and ((o.refunded_amount_cents<o.total_cents and o.payment_status='paid' and o.status<>'refunded'
          and frozen->>'payment_status'='paid' and frozen->>'status'<>'refunded')
      or (o.refunded_amount_cents=o.total_cents and o.payment_status='refunded' and o.status in ('refunded','cancelled')
          and frozen->>'payment_status'='refunded' and frozen->>'status' in ('refunded','cancelled')))
    and frozen->'refunded_amount_cents'=to_jsonb(o.refunded_amount_cents)
    and f->'refunded_amount_cents'=to_jsonb(o.refunded_amount_cents)
    and e.idempotency_key='order:'||o.id::text||':refund_confirmed:'||o.refunded_amount_cents::text;
end $$;

-- Same claim token/state machine and completion RPC. Only the validation branch
-- differs: financial truth is independent of mutable fulfillment progress.
create or replace function public.admin_claim_order_notification(p_actor uuid,p_id uuid,p_token uuid,p_ready boolean)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e public.email_logs; o public.orders; target uuid; valid boolean;
begin
  perform private.assert_admin(p_actor);
  if p_token is null or p_ready is null then raise exception 'Notification claim parameters required'; end if;
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
  if e.email_type in ('payment_confirmed','refund_confirmed') then
    valid:=private.financial_order_notification_matches(e,o);
  else
    valid:=not (o.id is null or o.is_test or e.order_id is distinct from o.id
      or e.event_snapshot->'order'->>'id' is distinct from o.id::text
      or e.event_snapshot->'order'->>'fulfillment_status' is distinct from o.fulfillment_status::text
      or (e.email_type<>'order_cancelled' and (o.payment_status<>'paid'
        or o.status in ('cancelled','refunded') or o.refunded_amount_cents<>0)));
  end if;
  if valid is distinct from true then
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

-- Quoted refunds require their independently bound financial ledger. The old
-- PI-only legacy helper cannot mutate a quoted order (test or future live).
do $guard$
declare body text; anchor text:='if not found then return; end if;';
begin
  select pg_get_functiondef('public.record_order_refund(text,integer)'::regprocedure) into body;
  if (length(body)-length(replace(body,anchor,'')))/length(anchor)<>1 then
    raise exception 'Review quoted legacy refund isolation drift'; end if;
  execute replace(body,anchor,anchor||E'\n  '||$a$if o.commerce_quote_id is not null then raise exception 'Quoted refunds require their reviewed financial ledger'; end if;$a$);
end $guard$;

revoke all on function private.enqueue_financial_order_notification(),
  private.financial_order_notification_matches(public.email_logs,public.orders) from public,anon,authenticated;
grant execute on function private.enqueue_financial_order_notification(),
  private.financial_order_notification_matches(public.email_logs,public.orders) to service_role;
commit;
