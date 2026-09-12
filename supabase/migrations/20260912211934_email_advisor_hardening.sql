-- Cover the email log FK used by account/admin history lookups.
create index if not exists email_logs_user_idx on public.email_logs(user_id);

-- These operational tables are deliberately service-role/backend-only.
-- Explicit deny policies document that boundary while keeping RLS fail-closed.
drop policy if exists backend_only_inventory_movements on public.inventory_movements;
create policy backend_only_inventory_movements on public.inventory_movements
for all to authenticated using (false) with check (false);

drop policy if exists backend_only_product_channels on public.product_channels;
create policy backend_only_product_channels on public.product_channels
for all to authenticated using (false) with check (false);

drop policy if exists backend_only_promotions on public.promotions;
create policy backend_only_promotions on public.promotions
for all to authenticated using (false) with check (false);

drop policy if exists backend_only_returns on public.returns;
create policy backend_only_returns on public.returns
for all to authenticated using (false) with check (false);

drop policy if exists backend_only_sales_channels on public.sales_channels;
create policy backend_only_sales_channels on public.sales_channels
for all to authenticated using (false) with check (false);

drop policy if exists backend_only_shop_settings on public.shop_settings;
create policy backend_only_shop_settings on public.shop_settings
for all to authenticated using (false) with check (false);
