-- Keep publication requirements aligned with live checkout. The offer must
-- identify the exact supplier SKU and include both purchase and shipping cost.
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
         where s.product_id = new.id
           and s.supplier_verified
           and nullif(btrim(s.supplier_name), '') is not null
           and nullif(btrim(s.supplier_reference), '') is not null
           and s.cost_price_cents is not null
           and s.shipping_cost_cents is not null
       ) then
      raise exception 'product is incomplete or unverified and cannot be activated';
    end if;
  end if;
  return new;
end;
$$;
