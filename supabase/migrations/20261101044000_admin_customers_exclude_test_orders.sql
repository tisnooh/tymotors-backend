-- Registered customers may appear before their first purchase. Sandbox-only
-- email addresses and the administrator account do not count as customers.
create or replace view public.admin_customers with (security_invoker=true) as
with commercial_orders as (
  select * from public.orders where is_test = false
), identities as (
  select lower(email) as email,max(full_name) as full_name,max(phone) as phone
  from public.profiles where email is not null and role <> 'admin'
  group by lower(email)
  union
  select lower(customer_email),null,null
  from commercial_orders where customer_email is not null
), people as (
  select email,max(full_name) full_name,max(phone) phone from identities group by email
)
select p.email,coalesce(p.full_name,max(o.customer_name)) as full_name,p.phone,
  count(o.id) as order_count,
  coalesce(sum(o.total_cents-o.refunded_amount_cents)
    filter(where o.paid_at is not null and o.status <> 'cancelled'),0) as spent_cents,
  coalesce(sum(o.refunded_amount_cents),0) as refunded_cents,
  max(o.created_at) as last_order_at
from people p left join commercial_orders o on lower(o.customer_email) = p.email
group by p.email,p.full_name,p.phone;
