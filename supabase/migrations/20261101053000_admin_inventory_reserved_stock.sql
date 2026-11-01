-- Products.stock is available inventory after Checkout reservations. Expose
-- the held units separately so the admin does not show a fictitious zero.
create or replace view public.admin_inventory with (security_invoker=true) as
with reserved as (
  select i.product_id, sum(i.quantity)::integer as reserved_stock
  from public.order_items i
  join public.orders o on o.id=i.order_id
  where o.stock_reserved_at is not null and o.stock_released_at is null
    and o.stock_applied_at is null and o.is_test=false
  group by i.product_id
)
select p.id,p.name,p.sku,p.stock,coalesce(r.reserved_stock,0)::integer as reserved_stock,p.status,
  coalesce(p.low_stock_threshold,s.low_stock_threshold) as low_stock_threshold,
  case when p.stock=0 then 'out' when p.stock<=coalesce(p.low_stock_threshold,s.low_stock_threshold)
    then 'low' else 'available' end as stock_status
from public.products p cross join public.shop_settings s
left join reserved r on r.product_id=p.id;

revoke all on public.admin_inventory from anon,authenticated;
grant select on public.admin_inventory to service_role;
