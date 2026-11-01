-- Orders created before the is_test column existed defaulted to false.
-- Only Stripe sandbox sessions with no external supplier order may be reclassified.
do $$
begin
  if exists (
    select 1 from public.orders o join public.supplier_orders s on s.order_id = o.id
    where o.is_test = false and o.stripe_session_id like 'cs_test_%'
      and (s.status not in ('pending_validation','cancelled')
        or s.alibaba_order_id is not null or s.agent_order_id is not null)
  ) then
    raise exception 'Legacy sandbox order has supplier activity; review manually';
  end if;
end $$;

update public.supplier_orders s set status = 'cancelled'
from public.orders o
where s.order_id = o.id and o.is_test = false
  and o.stripe_session_id like 'cs_test_%' and s.status = 'pending_validation';

with changed as (
  update public.orders o set is_test = true
  where o.is_test = false and o.stripe_session_id like 'cs_test_%'
  returning o.id
)
insert into public.admin_audit(action,resource,metadata)
select 'order.test_reclassified',id::text,
  jsonb_build_object('reason','Legacy Stripe sandbox session; no supplier purchase')
from changed;
