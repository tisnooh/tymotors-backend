-- Additive back-office migration. No production records are deleted.
alter table public.products add column if not exists low_stock_threshold integer check (low_stock_threshold >= 0);
alter table public.products add column if not exists tags text[] not null default '{}';
alter table public.orders add column if not exists stock_applied_at timestamptz;
alter table public.orders add column if not exists refunded_amount_cents integer not null default 0 check (refunded_amount_cents >= 0);
alter table public.orders add column if not exists discount_amount_cents integer not null default 0 check (discount_amount_cents >= 0);
alter table public.orders add column if not exists sales_channel text not null default 'website';
alter table public.orders add column if not exists delivered_at timestamptz;
alter table public.order_items add column if not exists cost_price_cents integer check (cost_price_cents >= 0);
-- Preserve historical idempotency without inventing historical purchase costs.
update public.orders set stock_applied_at = coalesce(paid_at, updated_at)
where stock_applied_at is null and payment_status in ('paid', 'refunded');
-- Legacy fully refunded orders have no partial refund information.
update public.orders set refunded_amount_cents = total_cents where payment_status = 'refunded';

create table public.shop_settings (
  id boolean primary key default true check (id),
  shop_name text not null default 'TYMotors',
  contact_email text,
  low_stock_threshold integer not null default 5 check (low_stock_threshold between 0 and 100000),
  currency text not null default 'EUR' check (currency = 'EUR'),
  updated_at timestamptz not null default now()
);
insert into public.shop_settings(id) values(true);

create table public.inventory_movements (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id),
  quantity integer not null check(quantity <> 0),
  stock_after integer not null check(stock_after >= 0),
  reason text not null,
  reference text,
  admin_user_id uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now()
);
create table public.sales_channels (
  slug text primary key,
  name text not null,
  mode text not null check(mode in ('website','manual'))
);
insert into public.sales_channels values ('website','Site TYMotors','website'),('leboncoin','Leboncoin','manual');
create table public.product_channels (
  product_id uuid not null references public.products(id) on delete cascade,
  channel_slug text not null references public.sales_channels(slug),
  status text not null default 'unpublished' check(status in ('unpublished','draft','to_publish','published','needs_update','error')),
  listing_id text,
  listing_url text check(listing_url is null or listing_url ~ '^https://'),
  published_at timestamptz,
  notes text,
  updated_at timestamptz not null default now(),
  primary key(product_id, channel_slug)
);
create table public.returns (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id),
  order_item_id uuid not null references public.order_items(id),
  quantity integer not null check(quantity between 1 and 20),
  reason text not null,
  status text not null default 'requested' check(status in ('requested','review','accepted','received','refunded','rejected')),
  amount_cents integer not null check(amount_cents >= 0),
  restocked_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.promotions (
  id uuid primary key default gen_random_uuid(),
  code text not null unique check(code ~ '^[A-Z0-9_-]{3,40}$'),
  active boolean not null default false,
  discount_type text not null check(discount_type in ('percent','fixed')),
  value integer not null check(value > 0),
  starts_at timestamptz,
  ends_at timestamptz,
  minimum_amount_cents integer not null default 0 check(minimum_amount_cents >= 0),
  max_uses integer check(max_uses > 0),
  product_ids uuid[] not null default '{}',
  category_ids uuid[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check(discount_type <> 'percent' or value <= 100),
  check(ends_at is null or starts_at is null or ends_at > starts_at)
);
alter table public.orders add column if not exists promotion_id uuid references public.promotions(id);
create index admin_orders_email_idx on public.orders(lower(customer_email), created_at desc);
create index admin_orders_fulfillment_idx on public.orders(fulfillment_status, created_at desc);
create index admin_orders_paid_idx on public.orders(paid_at desc) where paid_at is not null;
create index admin_orders_promotion_idx on public.orders(promotion_id) where promotion_id is not null;
create index admin_profiles_email_idx on public.profiles(lower(email));
create index admin_audit_resource_idx on public.admin_audit(resource, created_at desc);
create index inventory_product_date_idx on public.inventory_movements(product_id, created_at desc);
create index inventory_admin_idx on public.inventory_movements(admin_user_id);
create index returns_order_idx on public.returns(order_id, created_at desc);
create index returns_item_idx on public.returns(order_item_id);
create index channels_slug_idx on public.product_channels(channel_slug);

do $$
declare t text;
begin
  foreach t in array array['shop_settings','inventory_movements','sales_channels','product_channels','returns','promotions'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from anon, authenticated',t);
    execute format('grant all on public.%I to service_role',t);
  end loop;
end $$;

-- Defense in depth: every admin RPC verifies the current database role.
create function private.assert_admin(p_actor uuid) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  if not exists(select 1 from public.profiles where id=p_actor and role='admin') then
    raise exception 'Admin role required' using errcode='42501';
  end if;
  perform set_config('tymotors.actor',p_actor::text,true);
end $$;

create function private.log_stock() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare delta integer;
begin
  delta := new.stock - case when tg_op='INSERT' then 0 else old.stock end;
  if delta <> 0 then
    insert into public.inventory_movements(product_id,quantity,stock_after,reason,reference,admin_user_id)
    values(new.id,delta,new.stock,coalesce(nullif(current_setting('tymotors.reason',true),''),'correction'),
      nullif(current_setting('tymotors.reference',true),''),
      nullif(current_setting('tymotors.actor',true),'')::uuid);
  end if;
  return new;
end $$;
create trigger stock_history after insert or update of stock on public.products
for each row execute function private.log_stock();

create function public.admin_adjust_stock(p_actor uuid,p_product_id uuid,p_expected integer,p_delta integer,p_reason text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare p public.products%rowtype;
begin
  perform private.assert_admin(p_actor);
  if p_delta=0 or abs(p_delta)>100000 or length(trim(p_reason))<3 then raise exception 'Invalid stock adjustment'; end if;
  select * into strict p from public.products where id=p_product_id for update;
  if p.stock<>p_expected then raise exception 'Stock changed. Reload before saving.' using errcode='40001'; end if;
  if p.stock+p_delta<0 then raise exception 'Insufficient stock'; end if;
  perform set_config('tymotors.reason',p_reason,true);
  update public.products set stock=stock+p_delta where id=p.id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'stock.adjust',p.id::text,jsonb_build_object('before',p.stock,'after',p.stock+p_delta,'reason',p_reason));
  return jsonb_build_object('stock',p.stock+p_delta);
end $$;

-- One transaction for product, images, compatibility, supplier and audit.
create function public.admin_save_product(p_actor uuid,p_id uuid,p_expected timestamptz,p_base jsonb,p_images jsonb,p_rules jsonb,p_supplier jsonb)
returns uuid language plpgsql security invoker set search_path = '' as $$
declare old_p public.products%rowtype; p public.products%rowtype; rule jsonb; img jsonb; final_status public.product_status;
begin
  perform private.assert_admin(p_actor);
  if p_id is not null then
    select * into strict old_p from public.products where id=p_id for update;
    if p_expected is null or p_expected<>old_p.updated_at then raise exception 'Product changed. Reload before saving.' using errcode='40001'; end if;
    if (p_base->>'stock')::integer<>old_p.stock then raise exception 'Use inventory adjustment to change existing stock'; end if;
  end if;
  p := jsonb_populate_record(null::public.products,p_base);
  p.id := coalesce(p_id,gen_random_uuid());
  final_status := p.status;
  perform set_config('tymotors.reason','initial_stock',true);
  insert into public.products(id,slug,sku,name,subtitle,description,category_id,subcategory,price_cents,compare_at_price_cents,
    currency,stock,status,is_verified,featured,badges,rating,review_count,specs,package_contents,installation_difficulty,
    installation_minutes,tools_required,warranty_months,delivery_estimate,legacy_compatible_brands,low_stock_threshold,tags)
  values(p.id,p.slug,p.sku,p.name,p.subtitle,p.description,p.category_id,p.subcategory,p.price_cents,p.compare_at_price_cents,
    p.currency,p.stock,'draft',p.is_verified,p.featured,p.badges,p.rating,p.review_count,p.specs,p.package_contents,p.installation_difficulty,
    p.installation_minutes,p.tools_required,p.warranty_months,p.delivery_estimate,p.legacy_compatible_brands,p.low_stock_threshold,p.tags)
  on conflict(id) do update set slug=excluded.slug,sku=excluded.sku,name=excluded.name,subtitle=excluded.subtitle,
    description=excluded.description,category_id=excluded.category_id,subcategory=excluded.subcategory,
    price_cents=excluded.price_cents,compare_at_price_cents=excluded.compare_at_price_cents,currency=excluded.currency,
    status='draft',is_verified=excluded.is_verified,featured=excluded.featured,badges=excluded.badges,
    rating=excluded.rating,review_count=excluded.review_count,specs=excluded.specs,package_contents=excluded.package_contents,
    installation_difficulty=excluded.installation_difficulty,installation_minutes=excluded.installation_minutes,
    tools_required=excluded.tools_required,warranty_months=excluded.warranty_months,delivery_estimate=excluded.delivery_estimate,
    legacy_compatible_brands=excluded.legacy_compatible_brands,low_stock_threshold=excluded.low_stock_threshold,tags=excluded.tags;
  delete from public.product_images where product_id=p.id and url not in(select value->>'url' from jsonb_array_elements(p_images));
  for img in select value from jsonb_array_elements(p_images) loop
    insert into public.product_images(product_id,url,display_order,image_type,is_verified)
    values(p.id,img->>'url',(img->>'display_order')::integer,img->>'image_type',p.is_verified)
    on conflict(product_id,url) do update set display_order=excluded.display_order,is_verified=excluded.is_verified;
  end loop;
  delete from public.product_compatibilities where product_id=p.id;
  for rule in select value from jsonb_array_elements(p_rules) loop
    insert into public.product_compatibilities select
      (jsonb_populate_record(null::public.product_compatibilities,
        rule || jsonb_build_object('id',gen_random_uuid(),'product_id',p.id,'created_at',now(),'updated_at',now()))).*;
  end loop;
  -- Retain supplier verification dates not edited by this form.
  p_supplier := coalesce((select to_jsonb(s) from public.product_supplier_data s where product_id=p.id),'{}') || p_supplier;
  delete from public.product_supplier_data where product_id=p.id;
  insert into public.product_supplier_data select
    (jsonb_populate_record(null::public.product_supplier_data,
      p_supplier || jsonb_build_object('product_id',p.id,'updated_at',now()))).*;
  update public.products set status=final_status where id=p.id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,case when p_id is null then 'product.create' else 'product.update' end,p.id::text,
    jsonb_build_object('before',jsonb_build_object('price_cents',old_p.price_cents,'status',old_p.status),
      'after',jsonb_build_object('price_cents',p.price_cents,'status',final_status)));
  return p.id;
end $$;

create function public.admin_update_order(p_actor uuid,p_id uuid,p_status text,p_tracking text,p_expected timestamptz)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype;
begin
  perform private.assert_admin(p_actor);
  select * into strict o from public.orders where id=p_id for update;
  if p_expected is null or o.updated_at<>p_expected then raise exception 'Order changed. Reload before saving.' using errcode='40001'; end if;
  if p_status<>o.fulfillment_status::text then
    if o.fulfillment_status in ('cancelled','delivered') then raise exception 'This order is closed'; end if;
    if p_status in ('processing','shipped','delivered') and o.payment_status<>'paid' then raise exception 'Payment required'; end if;
    if p_status='delivered' and o.fulfillment_status<>'shipped' then raise exception 'Ship the order first'; end if;
    if p_status='shipped' and (o.fulfillment_status not in ('unfulfilled','processing','requires_review') or nullif(trim(p_tracking),'') is null) then raise exception 'Tracking number required'; end if;
    if p_status='cancelled' and o.fulfillment_status='shipped' then raise exception 'Use a return for shipped orders'; end if;
    if p_status not in ('processing','shipped','delivered','cancelled','requires_review') then raise exception 'Invalid transition'; end if;
  end if;
  update public.orders set fulfillment_status=p_status::public.fulfillment_status,tracking_number=nullif(trim(p_tracking),''),
    status=case when p_status='cancelled' then 'cancelled'::public.order_status else status end,
    shipped_at=case when p_status='shipped' then coalesce(shipped_at,now()) else shipped_at end,
    delivered_at=case when p_status='delivered' then coalesce(delivered_at,now()) else delivered_at end
  where id=p_id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'order.update',p_id::text,jsonb_build_object('before',jsonb_build_object('status',o.fulfillment_status,'tracking',o.tracking_number),
    'after',jsonb_build_object('status',p_status,'tracking',p_tracking)));
  return jsonb_build_object('updated',true);
end $$;

create or replace function public.complete_paid_order(p_order_id uuid,p_payment_intent_id text,p_customer_email text,p_customer_name text,p_shipping_address jsonb,p_billing_address jsonb)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; item record;
begin
  select * into o from public.orders where id=p_order_id for update;
  if not found then return false; end if;
  if o.stock_applied_at is not null or o.payment_status in ('paid','refunded') then return true; end if;
  perform set_config('tymotors.reason','paid_order',true);
  perform set_config('tymotors.reference',o.id::text,true);
  -- Stable locking order avoids deadlocks between multi-product checkouts.
  for item in select product_id,sum(quantity)::integer quantity from public.order_items where order_id=o.id group by product_id order by product_id loop
    if item.product_id is null then raise exception 'Missing product'; end if;
    update public.products set stock=stock-item.quantity where id=item.product_id and stock>=item.quantity;
    if not found then raise exception 'Insufficient stock while completing order'; end if;
  end loop;
  update public.order_items i set cost_price_cents=s.cost_price_cents from public.product_supplier_data s
  where i.order_id=o.id and i.product_id=s.product_id;
  update public.orders set payment_status='paid',status=case when status='cancelled' then status else 'paid'::public.order_status end,
    fulfillment_status=case when status='cancelled' or requires_compatibility_review then 'requires_review'::public.fulfillment_status else fulfillment_status end,
    stripe_payment_intent_id=p_payment_intent_id,customer_email=coalesce(p_customer_email,customer_email),
    customer_name=coalesce(p_customer_name,customer_name),shipping_address=coalesce(p_shipping_address,'{}'),
    billing_address=coalesce(p_billing_address,'{}'),paid_at=now(),stock_applied_at=now() where id=o.id;
  if o.cart_id is not null then delete from public.cart_items where cart_id=o.cart_id; end if;
  insert into public.admin_audit(action,resource,metadata) values('order.paid',o.id::text,jsonb_build_object('payment_intent',p_payment_intent_id));
  return true;
end $$;

create function public.record_order_refund(p_payment_intent text,p_refunded integer)
returns void language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype;
begin
  select * into o from public.orders where stripe_payment_intent_id=p_payment_intent for update;
  if not found then return; end if;
  if p_refunded<o.refunded_amount_cents or p_refunded>o.total_cents then return; end if;
  update public.orders set refunded_amount_cents=p_refunded,
    payment_status=case when p_refunded=total_cents then 'refunded'::public.payment_status else payment_status end,
    status=case when p_refunded=total_cents then 'refunded'::public.order_status else status end where id=o.id;
  if p_refunded<>o.refunded_amount_cents then
    insert into public.admin_audit(action,resource,metadata) values('order.refund_confirmed',o.id::text,
      jsonb_build_object('before',o.refunded_amount_cents,'after',p_refunded));
  end if;
end $$;

create function public.admin_return_action(p_actor uuid,p_id uuid,p_data jsonb)
returns uuid language plpgsql security invoker set search_path = '' as $$
declare r public.returns%rowtype; i public.order_items%rowtype; o public.orders%rowtype; next_status text; q integer;
begin
  perform private.assert_admin(p_actor);
  if p_id is null then
    select * into strict i from public.order_items where id=(p_data->>'order_item_id')::uuid;
    select * into strict o from public.orders where id=i.order_id for update;
    if o.paid_at is null then raise exception 'A paid order is required'; end if;
    q := (p_data->>'quantity')::integer;
    if q<1 or q+coalesce((select sum(quantity) from public.returns where order_item_id=i.id and status<>'rejected'),0)>i.quantity then raise exception 'Return quantity exceeds purchased quantity'; end if;
    insert into public.returns(order_id,order_item_id,quantity,reason,amount_cents)
    values(i.order_id,i.id,q,p_data->>'reason',i.unit_amount_cents*q) returning * into r;
  else
    select * into strict r from public.returns where id=p_id for update;
    next_status := coalesce(p_data->>'status',r.status);
    if next_status<>r.status and not (
      (r.status='requested' and next_status in ('review','accepted','rejected')) or
      (r.status='review' and next_status in ('accepted','rejected')) or
      (r.status='accepted' and next_status='received') or
      (r.status='received' and next_status='refunded')
    ) then raise exception 'Invalid return transition'; end if;
    if next_status='refunded' then
      select * into strict o from public.orders where id=r.order_id for update;
      -- V1 closure only after a confirmed FULL order refund; partial allocations need a later model.
      if o.payment_status<>'refunded' then raise exception 'Confirm the full refund with Stripe first'; end if;
    end if;
    if coalesce((p_data->>'restock')::boolean,false) then
      if r.status<>'received' or r.restocked_at is not null then raise exception 'Receive and inspect the product before restocking'; end if;
      select * into strict i from public.order_items where id=r.order_item_id;
      perform set_config('tymotors.reason','verified_return',true);
      perform set_config('tymotors.reference',r.id::text,true);
      update public.products set stock=stock+r.quantity where id=i.product_id;
      if not found then raise exception 'Product not found'; end if;
      r.restocked_at := now();
    end if;
    update public.returns set status=next_status,restocked_at=r.restocked_at,notes=coalesce(p_data->>'notes',notes),updated_at=now() where id=r.id;
  end if;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'return.update',r.order_id::text,jsonb_build_object('return_id',r.id,'changes',p_data));
  return r.id;
end $$;

-- Views are restricted to the backend service role and never exposed to customers.
create view public.admin_inventory with (security_invoker=true) as
select p.id,p.name,p.sku,p.stock,0::integer as reserved_stock,p.status,
  coalesce(p.low_stock_threshold,s.low_stock_threshold) as low_stock_threshold,
  case when p.stock=0 then 'out' when p.stock<=coalesce(p.low_stock_threshold,s.low_stock_threshold) then 'low' else 'available' end as stock_status
from public.products p cross join public.shop_settings s;

create view public.admin_customers with (security_invoker=true) as
with identities as (
  select lower(email) as email,max(full_name) as full_name,max(phone) as phone from public.profiles where email is not null group by lower(email)
  union
  select lower(customer_email),null,null from public.orders where customer_email is not null
), people as (select email,max(full_name) full_name,max(phone) phone from identities group by email)
select p.email,coalesce(p.full_name,max(o.customer_name)) as full_name,p.phone,count(o.id) as order_count,
  coalesce(sum(o.total_cents-o.refunded_amount_cents) filter(where o.paid_at is not null and o.status<>'cancelled'),0) as spent_cents,
  coalesce(sum(o.refunded_amount_cents),0) as refunded_cents,max(o.created_at) as last_order_at
from people p left join public.orders o on lower(o.customer_email)=p.email group by p.email,p.full_name,p.phone;
revoke all on public.admin_inventory,public.admin_customers from anon,authenticated;
grant select on public.admin_inventory,public.admin_customers to service_role;

create function public.admin_dashboard(p_actor uuid) returns jsonb
language sql security invoker set search_path = '' as $$
with guard as materialized (select private.assert_admin(p_actor)),
paid as (select o.* from public.orders o,guard where o.paid_at is not null and o.status<>'cancelled' and o.currency='EUR'),
periods as (
  select 'today' as name,date_trunc('day',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris' as start
  union all select 'week',date_trunc('week',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris'
  union all select 'month',date_trunc('month',now() at time zone 'Europe/Paris') at time zone 'Europe/Paris'
), revenue as (
  select periods.name,coalesce(sum(p.total_cents),0) as gross,coalesce(sum(p.refunded_amount_cents),0) as refunds,
  coalesce(sum(p.total_cents-p.refunded_amount_cents),0) as net from periods left join paid p on p.paid_at>=periods.start group by periods.name
), top_products as (
  select i.product_id,i.product_name,sum(i.quantity) quantity,sum(i.quantity*i.unit_amount_cents) gross_cents
  from public.order_items i join paid p on p.id=i.order_id where p.payment_status='paid'
  group by i.product_id,i.product_name order by quantity desc limit 5
), margin_orders as (
  select p.id,sum((i.unit_amount_cents-i.cost_price_cents)*i.quantity)-p.discount_amount_cents amount,
    count(*) filter(where i.cost_price_cents is null) missing
  from public.order_items i join paid p on p.id=i.order_id where p.refunded_amount_cents=0
  group by p.id,p.discount_amount_cents
), margin as (
  select sum(amount) filter(where missing=0) amount,coalesce(sum(missing),0) missing from margin_orders
)
select jsonb_build_object(
  'revenue',(select jsonb_object_agg(name,to_jsonb(revenue)-'name') from revenue),
  'order_count',(select count(*) from public.orders),
  'to_process',(select count(*) from public.orders where payment_status='paid' and status<>'cancelled' and fulfillment_status in ('unfulfilled','processing','requires_review')),
  'average_cents',(select coalesce(round(avg(total_cents-refunded_amount_cents)),0) from paid),
  'estimated_margin_cents',(select amount from margin),'missing_cost_lines',(select missing from margin),
  'customer_count',(select count(*) from public.admin_customers),
  'low_stock',(select coalesce(jsonb_agg(x),'[]') from (select * from public.admin_inventory where stock_status in ('low','out') and status<>'archived' order by stock,name limit 8) x),
  'top_products',(select coalesce(jsonb_agg(top_products),'[]') from top_products),
  'recent_orders',(select coalesce(jsonb_agg(x),'[]') from (select id,order_number,customer_name,total_cents,payment_status,created_at from public.orders order by created_at desc limit 6) x)
) from guard;
$$;

-- Block bypasses of the API's audit and transactional stock workflow.
revoke insert,update,delete on public.products,public.product_images,public.product_compatibilities,public.product_supplier_data from authenticated;
revoke update on public.orders from authenticated;
revoke all on function private.assert_admin(uuid),private.log_stock() from public,anon,authenticated;
grant usage on schema private to service_role;
grant execute on function private.assert_admin(uuid),private.log_stock() to service_role;
do $$
declare r record;
begin
  for r in select oid::regprocedure signature from pg_proc where pronamespace='public'::regnamespace and
    proname in ('admin_adjust_stock','admin_save_product','admin_update_order','admin_return_action','admin_dashboard','record_order_refund','complete_paid_order')
  loop
    execute format('revoke all on function %s from public,anon,authenticated',r.signature);
    execute format('grant execute on function %s to service_role',r.signature);
  end loop;
end $$;
create function public.admin_save_record(p_actor uuid,p_kind text,p_id uuid,p_data jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare result jsonb; previous jsonb; promo public.promotions%rowtype; ident uuid;
begin
  perform private.assert_admin(p_actor);
  if p_kind='archive' then
    select to_jsonb(p) into strict previous from public.products p where id=p_id for update;
    update public.products set status='archived',featured=false where id=p_id returning to_jsonb(products) into result;
  elsif p_kind='settings' then
    select to_jsonb(s) into previous from public.shop_settings s where id for update;
    update public.shop_settings set shop_name=p_data->>'shop_name',contact_email=p_data->>'contact_email',
      low_stock_threshold=(p_data->>'low_stock_threshold')::integer,updated_at=now() where id returning to_jsonb(shop_settings) into result;
  elsif p_kind='channel' then
    if p_data->>'channel_slug'='website' then raise exception 'Use product status'; end if;
    select to_jsonb(c) into previous from public.product_channels c where product_id=p_id and channel_slug=p_data->>'channel_slug' for update;
    insert into public.product_channels(product_id,channel_slug,status,listing_id,listing_url,notes,published_at)
    values(p_id,p_data->>'channel_slug',p_data->>'status',p_data->>'listing_id',p_data->>'listing_url',p_data->>'notes',
      case when p_data->>'status'='published' then now() else null end)
    on conflict(product_id,channel_slug) do update set status=excluded.status,listing_id=excluded.listing_id,
      listing_url=excluded.listing_url,notes=excluded.notes,updated_at=now(),
      published_at=case when excluded.status='published' then coalesce(product_channels.published_at,now()) else product_channels.published_at end
    returning to_jsonb(product_channels) into result;
  elsif p_kind='promotion' then
    if p_id is not null then select to_jsonb(p) into strict previous from public.promotions p where id=p_id for update; end if;
    promo := jsonb_populate_record(null::public.promotions,p_data);
    if exists(select 1 from unnest(promo.product_ids) v where not exists(select 1 from public.products p where p.id=v)) or
       exists(select 1 from unnest(promo.category_ids) v where not exists(select 1 from public.categories c where c.id=v)) then
      raise exception 'Unknown product or category';
    end if;
    ident := coalesce(p_id,gen_random_uuid());
    insert into public.promotions(id,code,active,discount_type,value,starts_at,ends_at,minimum_amount_cents,max_uses,product_ids,category_ids)
    values(ident,promo.code,promo.active,promo.discount_type,promo.value,promo.starts_at,promo.ends_at,promo.minimum_amount_cents,promo.max_uses,promo.product_ids,promo.category_ids)
    on conflict(id) do update set code=excluded.code,active=excluded.active,discount_type=excluded.discount_type,value=excluded.value,
      starts_at=excluded.starts_at,ends_at=excluded.ends_at,minimum_amount_cents=excluded.minimum_amount_cents,max_uses=excluded.max_uses,
      product_ids=excluded.product_ids,category_ids=excluded.category_ids,updated_at=now()
    returning to_jsonb(promotions) into result;
  else raise exception 'Unknown operation'; end if;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,p_kind||'.save',coalesce(p_id::text,ident::text,'shop_settings'),jsonb_build_object('before',previous,'after',result));
  return result;
end $$;

create function public.apply_order_promotion(p_order_id uuid,p_code text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; p public.promotions%rowtype; eligible bigint; discount integer; uses integer;
begin
  select * into strict o from public.orders where id=p_order_id for update;
  if o.status<>'pending' or o.stripe_session_id is not null or o.promotion_id is not null then raise exception 'Order cannot accept a promotion'; end if;
  select * into strict p from public.promotions where code=p_code for update;
  if not p.active or (p.starts_at is not null and p.starts_at>now()) or (p.ends_at is not null and p.ends_at<=now()) or o.subtotal_cents<p.minimum_amount_cents then
    raise exception 'Promotion unavailable for this order';
  end if;
  select count(*) into uses from public.orders where promotion_id=p.id and (stock_applied_at is not null or status='pending');
  if p.max_uses is not null and uses>=p.max_uses then raise exception 'Promotion usage limit reached'; end if;
  select coalesce(sum(i.quantity*i.unit_amount_cents),0) into eligible from public.order_items i join public.products product on product.id=i.product_id
  where i.order_id=o.id and ((cardinality(p.product_ids)=0 and cardinality(p.category_ids)=0) or product.id=any(p.product_ids) or product.category_id=any(p.category_ids));
  discount := least(eligible,case when p.discount_type='percent' then floor(eligible*p.value/100.0)::integer else p.value end);
  if discount<=0 then raise exception 'No eligible products'; end if;
  update public.orders set promotion_id=p.id,discount_amount_cents=discount,total_cents=total_cents-discount where id=o.id;
  return jsonb_build_object('discount_cents',discount,'promotion_id',p.id);
end $$;
revoke all on function public.admin_save_record(uuid,text,uuid,jsonb),public.apply_order_promotion(uuid,text) from public,anon,authenticated;
grant execute on function public.admin_save_record(uuid,text,uuid,jsonb),public.apply_order_promotion(uuid,text) to service_role;
notify pgrst, 'reload schema';
