-- Background delivery never reclaims a blocked receipt; manual review remains separate.
begin;
create or replace function public.commerce_claim_financial_notification(p_id uuid,p_token uuid,p_ready boolean)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare target uuid; e public.email_logs; o public.orders; enabled boolean;
begin
  -- Keep the core's gate -> order -> log lock order, including concurrent stops.
  begin
    select financial_notification_auto_enabled into enabled
      from public.shop_settings where id for share;
  exception when insufficient_privilege then enabled:=false;
  end;
  if enabled is distinct from true then
    return jsonb_build_object('claimed',false,'state','disabled'); end if;
  select order_id into target from public.email_logs where id=p_id;
  select * into o from public.orders where id=target for update;
  select * into e from public.email_logs where id=p_id for update;
  if not found then return jsonb_build_object('claimed',false,'state','not_found'); end if;
  if e.order_id is distinct from target then
    return jsonb_build_object('claimed',false,'state','not_eligible'); end if;
  -- Preserve the core's eligibility result for historical and unrelated rows.
  if e.event_snapshot is null or e.email_type not in ('payment_confirmed','refund_confirmed')
    or e.metadata->>'source' is distinct from 'atomic_financial_transition'
    or o.id is null or o.is_test then
    return jsonb_build_object('claimed',false,'state','not_eligible'); end if;
  if e.delivery_state is distinct from 'pending' then
    return jsonb_build_object('claimed',false,'state',coalesce(e.delivery_state,'unknown')); end if;
  return private.claim_order_notification_core(null,p_id,p_token,p_ready,'systemfinancial');
end $$;
revoke all on function public.commerce_claim_financial_notification(uuid,uuid,boolean)
  from public,anon,authenticated;
grant execute on function public.commerce_claim_financial_notification(uuid,uuid,boolean) to service_role;
commit;
