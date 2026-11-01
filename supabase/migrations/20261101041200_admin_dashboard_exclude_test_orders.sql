-- Keep sandbox orders visible in the recent-order list, but never count them
-- as commercial revenue, orders to fulfill, or product sales.
create or replace function public.admin_dashboard(p_actor uuid) returns jsonb
language sql security invoker set search_path = '' as $$
with guard as materialized (select private.assert_admin(p_actor)),
paid as (
  select o.* from public.orders o,guard
  where o.paid_at is not null and o.status <> 'cancelled'
    and o.currency = 'EUR' and o.is_test = false
),
periods as (
  select 'today' as name,date_trunc('day',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris' as start
  union all select 'week',date_trunc('week',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris'
  union all select 'month',date_trunc('month',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris'
), revenue as (
  select periods.name,coalesce(sum(p.total_cents),0) as gross,coalesce(sum(p.refunded_amount_cents),0) as refunds,
  coalesce(sum(p.total_cents-p.refunded_amount_cents),0) as net
  from periods left join paid p on p.paid_at >= periods.start group by periods.name
), top_products as (
  select i.product_id,i.product_name,sum(i.quantity) quantity,sum(i.quantity*i.unit_amount_cents) gross_cents
  from public.order_items i join paid p on p.id = i.order_id where p.payment_status = 'paid'
  group by i.product_id,i.product_name order by quantity desc limit 5
), margin_orders as (
  select p.id,sum((i.unit_amount_cents-i.cost_price_cents)*i.quantity)-p.discount_amount_cents amount,
    count(*) filter(where i.cost_price_cents is null) missing
  from public.order_items i join paid p on p.id = i.order_id where p.refunded_amount_cents = 0
  group by p.id,p.discount_amount_cents
), margin as (
  select sum(amount) filter(where missing = 0) amount,coalesce(sum(missing),0) missing from margin_orders
)
select jsonb_build_object(
  'revenue',(select jsonb_object_agg(name,to_jsonb(revenue)-'name') from revenue),
  'order_count',(select count(*) from public.orders where is_test = false),
  'to_process',(select count(*) from public.orders where is_test = false and payment_status = 'paid'
    and status <> 'cancelled' and fulfillment_status in ('unfulfilled','processing','requires_review')),
  'average_cents',(select coalesce(round(avg(total_cents-refunded_amount_cents)),0) from paid),
  'estimated_margin_cents',(select amount from margin),'missing_cost_lines',(select missing from margin),
  'customer_count',(select count(*) from public.admin_customers),
  'low_stock',(select coalesce(jsonb_agg(x),'[]') from
    (select * from public.admin_inventory where stock_status in ('low','out')
      and status <> 'archived' order by stock,name limit 8) x),
  'top_products',(select coalesce(jsonb_agg(top_products),'[]') from top_products),
  'recent_orders',(select coalesce(jsonb_agg(x),'[]') from
    (select id,order_number,customer_name,total_cents,payment_status,is_test,created_at
      from public.orders order by created_at desc limit 6) x)
) from guard;
$$;
