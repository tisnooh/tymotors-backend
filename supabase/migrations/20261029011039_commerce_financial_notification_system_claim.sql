-- Preparation only. No worker startup, transport, toggle endpoint or backfill.
begin;
alter table public.shop_settings add column financial_notification_auto_enabled boolean not null default false;
comment on column public.shop_settings.financial_notification_auto_enabled is
  'Persistent emergency stop for financial notification claims. False by default; activation requires a separately approved configuration change.';

create function private.claim_order_notification_core(p_actor uuid,p_id uuid,p_token uuid,p_ready boolean,p_principal text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e public.email_logs; o public.orders; target uuid; valid boolean; enabled boolean;
begin
  if p_principal is null or p_principal not in ('admin','systemfinancial') then
    raise exception 'Invalid notification claim principal'; end if;
  if p_principal='admin' then
    perform private.assert_admin(p_actor);
  elsif p_actor is not null then
    raise exception 'System financial claims cannot impersonate an administrator';
  end if;
  if p_token is null or p_ready is null then raise exception 'Notification claim parameters required'; end if;
  if p_principal='systemfinancial' then
    -- Shared singleton lock survives through the claim transaction. A concurrent
    -- stop UPDATE waits for already-started claims; subsequent claims see false.
    begin
      select financial_notification_auto_enabled into enabled from public.shop_settings where id for share;
    exception when insufficient_privilege then enabled:=false;
    end;
    if enabled is distinct from true then return jsonb_build_object('claimed',false,'state','disabled'); end if;
  end if;
  -- Preserve the authoritative order -> log lock ordering of manual claims.
  select order_id into target from public.email_logs where id=p_id;
  select * into o from public.orders where id=target for update;
  select * into e from public.email_logs where id=p_id for update;
  if p_principal='admin' then perform private.assert_admin(p_actor); end if;
  if e.id is null then raise exception 'Notification not found'; end if;
  if p_principal='systemfinancial' and (e.event_snapshot is null
    or e.email_type not in ('payment_confirmed','refund_confirmed')
    or e.metadata->>'source' is distinct from 'atomic_financial_transition'
    or o.id is null or o.is_test) then
    return jsonb_build_object('claimed',false,'state','not_eligible');
  end if;
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
  values(p_actor,'email.outbox_claim',e.id::text,jsonb_build_object('order_id',e.order_id,'email_type',e.email_type)
    ||case when p_principal='systemfinancial' then jsonb_build_object('principal','systemfinancial') else '{}'::jsonb end);
  return jsonb_build_object('claimed',true,'state','claimed');
end $$;

-- Signature, actor checks, financial checks and outcomes remain identical.
create or replace function public.admin_claim_order_notification(p_actor uuid,p_id uuid,p_token uuid,p_ready boolean)
returns jsonb language sql security invoker set search_path='' as $$
  select private.claim_order_notification_core(p_actor,p_id,p_token,p_ready,'admin');
$$;

create function public.commerce_claim_financial_notification(p_id uuid,p_token uuid,p_ready boolean)
returns jsonb language sql security invoker set search_path='' as $$
  select private.claim_order_notification_core(null,p_id,p_token,p_ready,'systemfinancial');
$$;

revoke all on function private.claim_order_notification_core(uuid,uuid,uuid,boolean,text),
  public.commerce_claim_financial_notification(uuid,uuid,boolean) from public,anon,authenticated;
grant execute on function private.claim_order_notification_core(uuid,uuid,uuid,boolean,text),
  public.commerce_claim_financial_notification(uuid,uuid,boolean) to service_role;
commit;
