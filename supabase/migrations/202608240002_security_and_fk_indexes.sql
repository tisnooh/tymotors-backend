-- Follow-up for projects where the initial migration was already applied.
-- Keep the role helper outside the exposed API schema and remove overlapping
-- permissive SELECT policies while retaining admin write access.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to anon, authenticated;

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
revoke all on function private.is_admin() from public, anon, authenticated;
grant execute on function private.is_admin() to anon, authenticated;

alter policy profiles_select_own on public.profiles
  using ((select auth.uid()) = id or (select private.is_admin()));
alter policy public_read_brands on public.brands
  using (is_active or (select private.is_admin()));
alter policy public_read_vehicle_models on public.vehicle_models
  using (is_active or (select private.is_admin()));
alter policy public_read_vehicle_generations on public.vehicle_generations
  using (is_active or (select private.is_admin()));
alter policy public_read_vehicle_hotspots on public.vehicle_hotspots
  using (is_verified or (select private.is_admin()));
alter policy public_read_categories on public.categories
  using (is_active or (select private.is_admin()));
alter policy public_read_products on public.products
  using (status = 'active' or (select private.is_admin()));
alter policy public_read_product_images on public.product_images
  using (exists (
    select 1 from public.products p
    where p.id = product_id and (p.status = 'active' or (select private.is_admin()))
  ));
alter policy public_read_product_compatibilities on public.product_compatibilities
  using (exists (
    select 1 from public.products p
    where p.id = product_id and (p.status = 'active' or (select private.is_admin()))
  ));
alter policy orders_select_own on public.orders
  using ((select auth.uid()) = user_id or (select private.is_admin()));
alter policy order_items_select_own on public.order_items
  using (exists (
    select 1 from public.orders o
    where o.id = order_id
      and (o.user_id = (select auth.uid()) or (select private.is_admin()))
  ));
alter policy admin_update_orders on public.orders
  using ((select private.is_admin())) with check ((select private.is_admin()));
alter policy admin_read_supplier_data on public.product_supplier_data
  using ((select private.is_admin()));
alter policy admin_read_stripe_events on public.stripe_events
  using ((select private.is_admin()));
alter policy admin_read_contacts on public.contact_messages
  using ((select private.is_admin()));
alter policy admin_update_contacts on public.contact_messages
  using ((select private.is_admin())) with check ((select private.is_admin()));
alter policy admin_read_newsletter on public.newsletter_subscriptions
  using ((select private.is_admin()));
alter policy admin_read_audit on public.admin_audit
  using ((select private.is_admin()));

drop policy admin_all_brands on public.brands;
drop policy admin_all_vehicle_models on public.vehicle_models;
drop policy admin_all_vehicle_generations on public.vehicle_generations;
drop policy admin_all_vehicle_hotspots on public.vehicle_hotspots;
drop policy admin_all_categories on public.categories;
drop policy admin_all_products on public.products;
drop policy admin_all_product_images on public.product_images;
drop policy admin_all_product_compatibilities on public.product_compatibilities;
drop policy admin_all_supplier_data on public.product_supplier_data;

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

revoke all on function public.is_admin() from public, anon, authenticated;
drop function public.is_admin();

create index if not exists admin_audit_admin_user_idx on public.admin_audit(admin_user_id);
create index if not exists cart_items_product_idx on public.cart_items(product_id);
create index if not exists categories_parent_idx on public.categories(parent_id);
create index if not exists contact_messages_user_idx on public.contact_messages(user_id);
create index if not exists customer_addresses_user_idx on public.customer_addresses(user_id);
create index if not exists newsletter_subscriptions_user_idx on public.newsletter_subscriptions(user_id);
create index if not exists order_items_product_idx on public.order_items(product_id);
create index if not exists orders_cart_idx on public.orders(cart_id);
create index if not exists product_compatibilities_product_idx on public.product_compatibilities(product_id);
create index if not exists product_compatibilities_model_idx on public.product_compatibilities(vehicle_model_id);
create index if not exists product_compatibilities_generation_idx on public.product_compatibilities(generation_id);
create index if not exists product_compatibilities_verified_by_idx on public.product_compatibilities(verified_by);
create index if not exists products_category_idx on public.products(category_id);
create index if not exists saved_vehicles_generation_idx on public.saved_vehicles(generation_id);
create index if not exists wishlists_product_idx on public.wishlists(product_id);
