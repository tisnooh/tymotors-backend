create table public.suppliers (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(name) between 2 and 160),
  url text check (url is null or (url ~ '^https://' and length(url) <= 1000)),
  notes text not null default '' check (length(notes) <= 5000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (name, url)
);
create table public.supplier_products (
  supplier_id uuid not null references public.suppliers(id) on delete cascade,
  product_id uuid not null references public.products(id) on delete cascade,
  primary key (supplier_id, product_id)
);
create index supplier_products_product_idx on public.supplier_products(product_id);
alter table public.suppliers enable row level security;
alter table public.supplier_products enable row level security;
revoke all on public.suppliers, public.supplier_products from public, anon, authenticated;
grant select, insert, update, delete on public.suppliers, public.supplier_products to service_role;

-- Import only existing supplier references; no scraping or supplier verification.
insert into public.suppliers(name,url)
select distinct supplier_name, supplier_url from public.product_supplier_data
where length(supplier_name) between 2 and 160 and supplier_url ~ '^https://' and length(supplier_url) <= 1000
on conflict do nothing;
insert into public.supplier_products(supplier_id,product_id)
select s.id,p.product_id from public.product_supplier_data p
join public.suppliers s on s.name=p.supplier_name and s.url=p.supplier_url
on conflict do nothing;

create function public.admin_save_supplier(p_actor uuid, p_id uuid, p_data jsonb, p_expected timestamptz default null)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v public.suppliers; v_product uuid;
begin
  perform private.assert_admin(p_actor);
  if p_id is null then
    insert into public.suppliers(name,url,notes) values(p_data->>'name',nullif(p_data->>'url',''),coalesce(p_data->>'notes','')) returning * into v;
  else
    select * into v from public.suppliers where id=p_id for update;
    if not found then raise exception 'Supplier not found'; end if;
    if p_expected is null or v.updated_at <> p_expected then raise exception 'Data changed. Reload'; end if;
    update public.suppliers set name=p_data->>'name',url=nullif(p_data->>'url',''),notes=coalesce(p_data->>'notes',''),updated_at=clock_timestamp()
    where id=p_id returning * into v;
  end if;
  delete from public.supplier_products where supplier_id=v.id;
  for v_product in select value::uuid from jsonb_array_elements_text(coalesce(p_data->'product_ids','[]'::jsonb)) loop
    insert into public.supplier_products values(v.id,v_product) on conflict do nothing;
  end loop;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'supplier.save',v.id::text,jsonb_build_object('name',v.name));
  return to_jsonb(v);
end; $$;
revoke all on function public.admin_save_supplier(uuid,uuid,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function public.admin_save_supplier(uuid,uuid,jsonb,timestamptz) to service_role;
