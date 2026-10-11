create index if not exists supplier_orders_approved_by_idx
  on public.supplier_orders (approved_by)
  where approved_by is not null;
