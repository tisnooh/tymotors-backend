-- TYMotors Supabase foundation.
-- All historical products are imported as draft/unverified by the companion importer.

create extension if not exists pgcrypto;

-- Helper functions used by RLS live outside the exposed Data API schema.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to anon, authenticated;

create type public.app_role as enum ('customer', 'admin');
create type public.product_status as enum ('draft', 'active', 'archived');
create type public.order_status as enum ('pending', 'paid', 'payment_failed', 'cancelled', 'refunded');
create type public.payment_status as enum ('unpaid', 'paid', 'failed', 'refunded');
create type public.fulfillment_status as enum ('unfulfilled', 'processing', 'shipped', 'delivered', 'cancelled', 'requires_review');
create type public.compatibility_state as enum ('unverified', 'verified', 'rejected');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  phone text,
  stripe_customer_id text unique,
  role public.app_role not null default 'customer',
  billing_address jsonb not null default '{}'::jsonb,
  shipping_address jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.brands (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  name text not null,
  tagline text,
  description text,
  image_url text,
  logo_text text,
  display_order integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.vehicle_models (
  id uuid primary key default gen_random_uuid(),
  brand_id uuid not null references public.brands(id) on delete cascade,
  slug text not null check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  name text not null,
  display_order integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (brand_id, slug)
);

create table public.vehicle_generations (
  id uuid primary key default gen_random_uuid(),
  vehicle_model_id uuid not null references public.vehicle_models(id) on delete cascade,
  slug text not null check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  name text not null,
  chassis_codes text[] not null default '{}',
  year_from integer check (year_from between 1950 and 2100),
  year_to integer check (year_to between 1950 and 2100),
  body_types text[] not null default '{}',
  trims text[] not null default '{}',
  stage_image_url text,
  stage_image_alt text,
  image_verified boolean not null default false,
  display_order integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (vehicle_model_id, slug),
  check (year_from is null or year_to is null or year_from <= year_to)
);

create table public.vehicle_hotspots (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references public.vehicle_generations(id) on delete cascade,
  zone_slug text not null check (zone_slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  label text not null,
  category_slug text not null,
  x_percent numeric(5,2) not null check (x_percent between 0 and 100),
  y_percent numeric(5,2) not null check (y_percent between 0 and 100),
  image_url text,
  image_alt text,
  is_verified boolean not null default false,
  display_order integer not null default 0,
  unique (generation_id, zone_slug)
);

create table public.categories (
  id uuid primary key default gen_random_uuid(),
  parent_id uuid references public.categories(id) on delete set null,
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  name text not null,
  tagline text,
  description text,
  image_url text,
  display_order integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  sku text not null unique,
  name text not null,
  subtitle text,
  description text not null,
  category_id uuid not null references public.categories(id),
  subcategory text,
  price_cents integer not null check (price_cents >= 0),
  compare_at_price_cents integer check (compare_at_price_cents is null or compare_at_price_cents > price_cents),
  currency text not null default 'EUR' check (currency ~ '^[A-Z]{3}$'),
  stock integer not null default 0 check (stock >= 0),
  status public.product_status not null default 'draft',
  is_verified boolean not null default false,
  featured boolean not null default false,
  badges text[] not null default '{}',
  rating numeric(2,1) check (rating between 0 and 5),
  review_count integer not null default 0 check (review_count >= 0),
  specs jsonb not null default '{}'::jsonb,
  package_contents text[] not null default '{}',
  installation_difficulty text check (installation_difficulty in ('easy','medium','advanced','professional')),
  installation_minutes integer check (installation_minutes between 0 and 1440),
  tools_required text[] not null default '{}',
  warranty_months integer check (warranty_months between 0 and 120),
  delivery_estimate text,
  legacy_compatible_brands text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (status <> 'active' or is_verified)
);

create table public.product_images (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  url text not null,
  public_id text,
  alt_text text,
  image_type text not null default 'gallery' check (image_type in ('main','gallery','installed','detail','package','fitment')),
  width integer check (width is null or width > 0),
  height integer check (height is null or height > 0),
  is_verified boolean not null default false,
  display_order integer not null default 0,
  created_at timestamptz not null default now(),
  unique (product_id, url)
);

create table public.product_compatibilities (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete cascade,
  brand_id uuid not null references public.brands(id),
  vehicle_model_id uuid references public.vehicle_models(id),
  generation_id uuid references public.vehicle_generations(id),
  model_name text,
  chassis text,
  generation_name text,
  year_from integer check (year_from between 1950 and 2100),
  year_to integer check (year_to between 1950 and 2100),
  body_types text[] not null default '{}',
  facelift text not null default 'unknown' check (facelift in ('pre-lci','lci','any','unknown')),
  required_trims text[] not null default '{}',
  excluded_trims text[] not null default '{}',
  camera_compatible boolean,
  parking_sensor_compatible boolean,
  notes text,
  verification_state public.compatibility_state not null default 'unverified',
  verified_at timestamptz,
  verified_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (year_from is null or year_to is null or year_from <= year_to)
);

create table public.product_supplier_data (
  product_id uuid primary key references public.products(id) on delete cascade,
  supplier_name text,
  supplier_reference text,
  supplier_url text,
  exact_source_url text,
  cost_price_cents integer check (cost_price_cents is null or cost_price_cents >= 0),
  shipping_cost_cents integer check (shipping_cost_cents is null or shipping_cost_cents >= 0),
  landed_cost_cents integer check (landed_cost_cents is null or landed_cost_cents >= 0),
  margin_amount_cents integer,
  margin_percent numeric(7,2),
  moq integer check (moq is null or moq > 0),
  supplier_verified boolean not null default false,
  last_checked_at timestamptz,
  notes text,
  updated_at timestamptz not null default now()
);

create table public.saved_vehicles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  generation_id uuid references public.vehicle_generations(id),
  nickname text,
  year integer check (year between 1950 and 2100),
  body_type text,
  trim text,
  has_camera boolean,
  has_parking_sensors boolean,
  created_at timestamptz not null default now(),
  unique (user_id, generation_id, year, body_type, trim)
);

create table public.customer_addresses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  address_type text not null check (address_type in ('shipping','billing')),
  label text,
  recipient_name text not null,
  line1 text not null,
  line2 text,
  postal_code text not null,
  city text not null,
  region text,
  country_code text not null check (country_code ~ '^[A-Z]{2}$'),
  phone text,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.carts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade,
  guest_session_id text,
  currency text not null default 'EUR',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((user_id is not null) <> (guest_session_id is not null))
);
create unique index carts_user_unique on public.carts(user_id) where user_id is not null;
create unique index carts_guest_unique on public.carts(guest_session_id) where guest_session_id is not null;

create table public.cart_items (
  id uuid primary key default gen_random_uuid(),
  cart_id uuid not null references public.carts(id) on delete cascade,
  product_id uuid not null references public.products(id) on delete cascade,
  quantity integer not null check (quantity between 1 and 20),
  selected_vehicle jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (cart_id, product_id)
);

create table public.wishlists (
  user_id uuid not null references public.profiles(id) on delete cascade,
  product_id uuid not null references public.products(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, product_id)
);

create table public.orders (
  id uuid primary key default gen_random_uuid(),
  order_number text not null unique,
  user_id uuid references public.profiles(id) on delete set null,
  cart_id uuid references public.carts(id) on delete set null,
  guest_session_id text,
  stripe_session_id text unique,
  stripe_payment_intent_id text unique,
  status public.order_status not null default 'pending',
  payment_status public.payment_status not null default 'unpaid',
  fulfillment_status public.fulfillment_status not null default 'unfulfilled',
  customer_email text,
  customer_name text,
  shipping_address jsonb not null default '{}'::jsonb,
  billing_address jsonb not null default '{}'::jsonb,
  subtotal_cents integer not null check (subtotal_cents >= 0),
  shipping_amount_cents integer not null default 0 check (shipping_amount_cents >= 0),
  tax_amount_cents integer not null default 0 check (tax_amount_cents >= 0),
  total_cents integer not null check (total_cents >= 0),
  currency text not null default 'EUR' check (currency ~ '^[A-Z]{3}$'),
  requires_compatibility_review boolean not null default false,
  tracking_number text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  paid_at timestamptz,
  shipped_at timestamptz
);

create table public.order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  product_id uuid references public.products(id) on delete set null,
  product_name text not null,
  product_slug text not null,
  sku text not null,
  quantity integer not null check (quantity between 1 and 20),
  unit_amount_cents integer not null check (unit_amount_cents >= 0),
  currency text not null default 'EUR',
  image_url text,
  selected_vehicle jsonb,
  compatibility_result jsonb,
  created_at timestamptz not null default now()
);

create table public.stripe_events (
  event_id text primary key,
  event_type text not null,
  status text not null default 'processing' check (status in ('processing','completed','failed')),
  payload jsonb,
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table public.newsletter_subscriptions (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  locale text not null default 'fr',
  user_id uuid references public.profiles(id) on delete set null,
  consent_at timestamptz not null default now(),
  unsubscribed_at timestamptz
);

create table public.contact_messages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete set null,
  name text not null,
  email text not null,
  subject text not null,
  message text not null,
  status text not null default 'new' check (status in ('new','in_progress','closed')),
  created_at timestamptz not null default now()
);

create table public.admin_audit (
  id uuid primary key default gen_random_uuid(),
  admin_user_id uuid references public.profiles(id) on delete set null,
  action text not null,
  resource text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index products_public_catalog_idx on public.products(status, category_id, featured, created_at desc);
create index product_compatibility_lookup_idx on public.product_compatibilities(brand_id, vehicle_model_id, generation_id, year_from, year_to);
create index vehicle_models_brand_idx on public.vehicle_models(brand_id, display_order);
create index vehicle_generations_model_idx on public.vehicle_generations(vehicle_model_id, display_order);
create index orders_user_created_idx on public.orders(user_id, created_at desc);
create index orders_status_created_idx on public.orders(status, created_at desc);
create index order_items_order_idx on public.order_items(order_id);
create index cart_items_cart_idx on public.cart_items(cart_id);
create index product_images_product_idx on public.product_images(product_id, display_order);
create index admin_audit_admin_user_idx on public.admin_audit(admin_user_id);
create index cart_items_product_idx on public.cart_items(product_id);
create index categories_parent_idx on public.categories(parent_id);
create index contact_messages_user_idx on public.contact_messages(user_id);
create index customer_addresses_user_idx on public.customer_addresses(user_id);
create index newsletter_subscriptions_user_idx on public.newsletter_subscriptions(user_id);
create index order_items_product_idx on public.order_items(product_id);
create index orders_cart_idx on public.orders(cart_id);
create index product_compatibilities_product_idx on public.product_compatibilities(product_id);
create index product_compatibilities_model_idx on public.product_compatibilities(vehicle_model_id);
create index product_compatibilities_generation_idx on public.product_compatibilities(generation_id);
create index product_compatibilities_verified_by_idx on public.product_compatibilities(verified_by);
create index products_category_idx on public.products(category_id);
create index saved_vehicles_generation_idx on public.saved_vehicles(generation_id);
create index wishlists_product_idx on public.wishlists(product_id);

create or replace function public.set_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'profiles','brands','vehicle_models','vehicle_generations','categories','products',
    'product_compatibilities','product_supplier_data','customer_addresses','carts','cart_items','orders'
  ] loop
    execute format('create trigger set_%I_updated_at before update on public.%I for each row execute function public.set_updated_at()', table_name, table_name);
  end loop;
end $$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (new.id, new.email, nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function private.is_admin()
returns boolean
language sql
stable
security definer set search_path = ''
as $$
  select exists (
    select 1 from public.profiles
    where id = (select auth.uid()) and role = 'admin'
  );
$$;
revoke all on function private.is_admin() from public;
grant execute on function private.is_admin() to anon, authenticated;

create or replace function public.validate_product_publication()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  if new.status = 'active' then
    if not new.is_verified
       or new.stock < 0
       or new.delivery_estimate is null
       or new.installation_difficulty is null
       or cardinality(new.package_contents) = 0
       or not exists (
         select 1 from public.product_images i
         where i.product_id = new.id and i.is_verified
       )
       or not exists (
         select 1 from public.product_compatibilities c
         where c.product_id = new.id and c.verification_state = 'verified'
       )
       or not exists (
         select 1 from public.product_supplier_data s
         where s.product_id = new.id and s.supplier_verified and s.cost_price_cents is not null
       ) then
      raise exception 'product is incomplete or unverified and cannot be activated';
    end if;
  end if;
  return new;
end;
$$;

create trigger validate_product_before_publication
before insert or update of status on public.products
for each row execute function public.validate_product_publication();

create or replace function public.decrement_product_stock(p_product_id uuid, p_quantity integer)
returns boolean
language plpgsql
security definer set search_path = ''
as $$
declare changed integer;
begin
  if p_quantity < 1 or p_quantity > 20 then
    raise exception 'invalid quantity';
  end if;
  update public.products
  set stock = stock - p_quantity
  where id = p_product_id and status = 'active' and stock >= p_quantity;
  get diagnostics changed = row_count;
  return changed = 1;
end;
$$;
revoke all on function public.decrement_product_stock(uuid, integer) from public, anon, authenticated;
grant execute on function public.decrement_product_stock(uuid, integer) to service_role;

create or replace function public.complete_paid_order(
  p_order_id uuid,
  p_payment_intent_id text,
  p_customer_email text,
  p_customer_name text,
  p_shipping_address jsonb,
  p_billing_address jsonb
)
returns boolean
language plpgsql
security definer set search_path = ''
as $$
declare
  current_order public.orders%rowtype;
  item record;
begin
  select * into current_order from public.orders where id = p_order_id for update;
  if not found then return false; end if;
  if current_order.payment_status = 'paid' then return true; end if;

  for item in select product_id, quantity from public.order_items where order_id = p_order_id loop
    if item.product_id is not null then
      update public.products
      set stock = stock - item.quantity
      where id = item.product_id and status = 'active' and stock >= item.quantity;
      if not found then
        raise exception 'insufficient stock while completing order';
      end if;
    end if;
  end loop;

  update public.orders set
    status = 'paid', payment_status = 'paid', stripe_payment_intent_id = p_payment_intent_id,
    customer_email = coalesce(p_customer_email, customer_email),
    customer_name = coalesce(p_customer_name, customer_name),
    shipping_address = coalesce(p_shipping_address, '{}'::jsonb),
    billing_address = coalesce(p_billing_address, '{}'::jsonb),
    paid_at = now()
  where id = p_order_id;

  if current_order.cart_id is not null then
    delete from public.cart_items where cart_id = current_order.cart_id;
  end if;
  return true;
end;
$$;
revoke all on function public.complete_paid_order(uuid, text, text, text, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.complete_paid_order(uuid, text, text, text, jsonb, jsonb) to service_role;

alter table public.profiles enable row level security;
alter table public.brands enable row level security;
alter table public.vehicle_models enable row level security;
alter table public.vehicle_generations enable row level security;
alter table public.vehicle_hotspots enable row level security;
alter table public.categories enable row level security;
alter table public.products enable row level security;
alter table public.product_images enable row level security;
alter table public.product_compatibilities enable row level security;
alter table public.product_supplier_data enable row level security;
alter table public.saved_vehicles enable row level security;
alter table public.customer_addresses enable row level security;
alter table public.carts enable row level security;
alter table public.cart_items enable row level security;
alter table public.wishlists enable row level security;
alter table public.orders enable row level security;
alter table public.order_items enable row level security;
alter table public.stripe_events enable row level security;
alter table public.newsletter_subscriptions enable row level security;
alter table public.contact_messages enable row level security;
alter table public.admin_audit enable row level security;

create policy profiles_select_own on public.profiles for select to authenticated using ((select auth.uid()) = id or (select private.is_admin()));
create policy profiles_update_own on public.profiles for update to authenticated using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
revoke update on public.profiles from authenticated;
grant update (full_name, phone, billing_address, shipping_address, updated_at) on public.profiles to authenticated;

create policy public_read_brands on public.brands for select to anon, authenticated using (is_active or (select private.is_admin()));
create policy public_read_vehicle_models on public.vehicle_models for select to anon, authenticated using (is_active or (select private.is_admin()));
create policy public_read_vehicle_generations on public.vehicle_generations for select to anon, authenticated using (is_active or (select private.is_admin()));
create policy public_read_vehicle_hotspots on public.vehicle_hotspots for select to anon, authenticated using (is_verified or (select private.is_admin()));
create policy public_read_categories on public.categories for select to anon, authenticated using (is_active or (select private.is_admin()));
create policy public_read_products on public.products for select to anon, authenticated using (status = 'active' or (select private.is_admin()));
create policy public_read_product_images on public.product_images for select to anon, authenticated using (
  exists (select 1 from public.products p where p.id = product_id and (p.status = 'active' or (select private.is_admin())))
);
create policy public_read_product_compatibilities on public.product_compatibilities for select to anon, authenticated using (
  exists (select 1 from public.products p where p.id = product_id and (p.status = 'active' or (select private.is_admin())))
);

create policy admin_insert_brands on public.brands for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_brands on public.brands for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_brands on public.brands for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_vehicle_models on public.vehicle_models for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_vehicle_models on public.vehicle_models for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_vehicle_models on public.vehicle_models for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_vehicle_generations on public.vehicle_generations for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_vehicle_generations on public.vehicle_generations for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_vehicle_generations on public.vehicle_generations for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_vehicle_hotspots on public.vehicle_hotspots for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_vehicle_hotspots on public.vehicle_hotspots for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_vehicle_hotspots on public.vehicle_hotspots for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_categories on public.categories for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_categories on public.categories for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_categories on public.categories for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_products on public.products for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_products on public.products for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_products on public.products for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_product_images on public.product_images for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_product_images on public.product_images for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_product_images on public.product_images for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_product_compatibilities on public.product_compatibilities for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_product_compatibilities on public.product_compatibilities for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_product_compatibilities on public.product_compatibilities for delete to authenticated using ((select private.is_admin()));
create policy admin_insert_supplier_data on public.product_supplier_data for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_supplier_data on public.product_supplier_data for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_supplier_data on public.product_supplier_data for delete to authenticated using ((select private.is_admin()));

create policy saved_vehicles_own on public.saved_vehicles for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy addresses_own on public.customer_addresses for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy carts_own on public.carts for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy cart_items_own on public.cart_items for all to authenticated using (
  exists (select 1 from public.carts c where c.id = cart_id and c.user_id = (select auth.uid()))
) with check (
  exists (select 1 from public.carts c where c.id = cart_id and c.user_id = (select auth.uid()))
);
create policy wishlists_own on public.wishlists for all to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy orders_select_own on public.orders for select to authenticated using ((select auth.uid()) = user_id or (select private.is_admin()));
create policy order_items_select_own on public.order_items for select to authenticated using (
  exists (select 1 from public.orders o where o.id = order_id and (o.user_id = (select auth.uid()) or (select private.is_admin())))
);
create policy admin_update_orders on public.orders for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_read_supplier_data on public.product_supplier_data for select to authenticated using ((select private.is_admin()));
create policy admin_read_stripe_events on public.stripe_events for select to authenticated using ((select private.is_admin()));
create policy admin_read_contacts on public.contact_messages for select to authenticated using ((select private.is_admin()));
create policy admin_update_contacts on public.contact_messages for update to authenticated using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_read_newsletter on public.newsletter_subscriptions for select to authenticated using ((select private.is_admin()));
create policy admin_read_audit on public.admin_audit for select to authenticated using ((select private.is_admin()));

-- Anonymous newsletter/contact writes go through the rate-limited FastAPI backend.
-- Guest carts and all payment/order writes also go through the backend service role.

-- Supabase is transitioning new projects to opt-in Data API grants. Keep the
-- exposed surface explicit so security does not depend on project creation date.
revoke all on all tables in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

grant select on public.brands, public.vehicle_models, public.vehicle_generations,
  public.vehicle_hotspots, public.categories, public.products, public.product_images,
  public.product_compatibilities to anon;

grant select on public.profiles to authenticated;
grant update (full_name, phone, billing_address, shipping_address, updated_at)
  on public.profiles to authenticated;

grant select, insert, update, delete on public.brands, public.vehicle_models,
  public.vehicle_generations, public.vehicle_hotspots, public.categories,
  public.products, public.product_images, public.product_compatibilities,
  public.product_supplier_data to authenticated;

grant select, insert, update, delete on public.saved_vehicles,
  public.customer_addresses, public.carts, public.cart_items, public.wishlists
  to authenticated;
grant select, update on public.orders to authenticated;
grant select on public.order_items, public.stripe_events,
  public.newsletter_subscriptions, public.admin_audit to authenticated;
grant select, update on public.contact_messages to authenticated;

grant all privileges on all tables in schema public to service_role;
grant usage, select on all sequences in schema public to service_role;

grant execute on function private.is_admin() to anon, authenticated;
grant execute on function public.decrement_product_stock(uuid, integer) to service_role;
grant execute on function public.complete_paid_order(uuid, text, text, text, jsonb, jsonb) to service_role;

alter default privileges for role postgres in schema public
  revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke execute on functions from public, anon, authenticated;
