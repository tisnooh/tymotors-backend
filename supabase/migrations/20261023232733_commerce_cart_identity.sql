-- A cart line identifies product + variant + the complete selected vehicle.
-- Existing product-only clients remain supported only when that line is unique.
begin;

alter table public.cart_items add column variant_id uuid references public.product_variants(id) on delete restrict;
alter table public.cart_items drop constraint cart_items_cart_id_product_id_key;

create function private.cart_vehicle_identity(p_vehicle jsonb) returns jsonb
language plpgsql immutable security invoker set search_path='' as $$
begin
  if p_vehicle is null or p_vehicle='null'::jsonb then return '{}'::jsonb; end if;
  if jsonb_typeof(p_vehicle)<>'object' then raise exception 'Vehicle selection must be an object'; end if;
  return jsonb_strip_nulls(jsonb_build_object(
    'brand_slug',nullif(lower(trim(p_vehicle->>'brand_slug')),''),
    'model',nullif(lower(trim(p_vehicle->>'model')),''),
    'chassis',nullif(lower(trim(p_vehicle->>'chassis')),''),
    'generation',nullif(lower(trim(p_vehicle->>'generation')),''),
    'year',p_vehicle->'year','body_type',nullif(lower(trim(p_vehicle->>'body_type')),''),
    'trim',nullif(lower(trim(p_vehicle->>'trim')),''),
    'facelift',nullif(nullif(p_vehicle->>'facelift','unknown'),''),
    'has_camera',p_vehicle->'has_camera','has_parking_sensors',p_vehicle->'has_parking_sensors'));
end $$;

-- The full JSON is compared again in the RPC; a digest collision cannot merge
-- different vehicles. It would cause a unique violation, never data replacement.
create unique index cart_items_commerce_identity on public.cart_items(
  cart_id,product_id,coalesce(variant_id,'00000000-0000-0000-0000-000000000000'::uuid),
  md5(private.cart_vehicle_identity(selected_vehicle)::text));
create index cart_items_variant_idx on public.cart_items(variant_id);

create function private.assert_cart_owner(p_cart uuid,p_user uuid,p_guest text) returns void
language plpgsql security invoker set search_path='' as $$
begin
  if not exists(select 1 from public.carts c where c.id=p_cart and (
    (p_user is not null and p_guest is null and c.user_id=p_user)
    or (p_user is null and p_guest is not null and length(p_guest) between 16 and 128 and c.guest_session_id=p_guest)
  )) then raise exception 'Cart not found or not owned'; end if;
end $$;

create function private.check_cart_quantity(p_product uuid,p_variant uuid,p_quantity integer,p_test boolean) returns void
language plpgsql security invoker set search_path='' as $$
declare p public.products; v public.product_variants;
begin
  if p_quantity is null or p_quantity not between 1 and 20 then raise exception 'Cart quantity exceeds supported limit'; end if;
  select * into p from public.products where id=p_product for share;
  if not found or (p.status<>'active' and not (coalesce(p_test,false) and p.status='draft')) then raise exception 'Product unavailable'; end if;
  if p_variant is not null then
    select * into v from public.product_variants where id=p_variant for share;
    if not found or v.product_id<>p_product then raise exception 'Variant does not belong to product'; end if;
    if v.status<>'active' or not v.is_verified or v.stock<p_quantity or v.currency<>p.currency then
      raise exception 'Variant unavailable';
    end if;
    perform private.check_commerce_variant(v.id);
  else
    -- Never silently collapse a multivariant article to the legacy base SKU.
    if exists(select 1 from public.product_variants where product_id=p_product and status<>'archived') then
      raise exception 'Explicit variant selection required';
    end if;
    if not (coalesce(p_test,false) and p.status='draft') and (not p.is_verified or p.stock<p_quantity) then raise exception 'Insufficient stock'; end if;
  end if;
end $$;

create function private.check_cart_stock(p_cart uuid,p_product uuid,p_variant uuid,p_line uuid,p_new_quantity integer,p_test boolean)
returns void language plpgsql security invoker set search_path='' as $$
declare total_quantity bigint; available integer; draft_test boolean;
begin
  perform private.check_cart_quantity(p_product,p_variant,p_new_quantity,p_test);
  select coalesce(sum(quantity),0)+p_new_quantity into total_quantity from public.cart_items
    where cart_id=p_cart and product_id=p_product and variant_id is not distinct from p_variant
      and (p_line is null or id<>p_line);
  if p_variant is null then
    select stock,(coalesce(p_test,false) and status='draft') into available,draft_test from public.products where id=p_product;
  else
    select stock,false into available,draft_test from public.product_variants where id=p_variant;
  end if;
  if not draft_test and total_quantity>available then raise exception 'Insufficient stock across cart lines'; end if;
end $$;

create function private.guard_cart_variant() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.variant_id is not null and not exists(select 1 from public.product_variants where id=new.variant_id and product_id=new.product_id) then
    raise exception 'Variant does not belong to product';
  end if;
  return new;
end $$;
create trigger cart_items_variant_guard before insert or update of product_id,variant_id on public.cart_items
for each row execute function private.guard_cart_variant();

create function public.commerce_cart_add(p_cart_id uuid,p_user_id uuid,p_guest_session text,
  p_product_id uuid,p_variant_id uuid,p_quantity integer,p_vehicle jsonb,p_test_mode boolean default false)
returns uuid language plpgsql security invoker set search_path='' as $$
declare v public.cart_items; q integer;
begin
  perform private.assert_cart_owner(p_cart_id,p_user_id,p_guest_session);
  perform 1 from public.carts where id=p_cart_id for update;
  select * into v from public.cart_items where cart_id=p_cart_id and product_id=p_product_id
    and variant_id is not distinct from p_variant_id
    and private.cart_vehicle_identity(selected_vehicle)=private.cart_vehicle_identity(p_vehicle) for update;
  q:=coalesce(v.quantity,0)+p_quantity;
  if p_quantity is null or p_quantity not between 1 and 20 then raise exception 'Cart quantity exceeds supported limit'; end if;
  perform private.check_cart_stock(p_cart_id,p_product_id,p_variant_id,v.id,q,p_test_mode);
  if v.id is null then
    if (select count(*) from public.cart_items where cart_id=p_cart_id)>=100 then raise exception 'Cart line limit reached'; end if;
    insert into public.cart_items(cart_id,product_id,variant_id,quantity,selected_vehicle)
      values(p_cart_id,p_product_id,p_variant_id,q,nullif(p_vehicle,'null'::jsonb)) returning id into v.id;
  else
    update public.cart_items set quantity=q,updated_at=clock_timestamp() where id=v.id;
  end if;
  return v.id;
end $$;

create function public.commerce_cart_update(p_cart_id uuid,p_user_id uuid,p_guest_session text,
  p_line_id uuid,p_product_id uuid,p_quantity integer,p_test_mode boolean default false)
returns boolean language plpgsql security invoker set search_path='' as $$
declare v public.cart_items;
begin
  perform private.assert_cart_owner(p_cart_id,p_user_id,p_guest_session);
  perform 1 from public.carts where id=p_cart_id for update;
  if p_line_id is not null then
    select * into v from public.cart_items where id=p_line_id and cart_id=p_cart_id for update;
    if found and p_product_id is not null and v.product_id<>p_product_id then raise exception 'Cart line product mismatch'; end if;
  else
    if (select count(*) from public.cart_items where cart_id=p_cart_id and product_id=p_product_id)>1 then
      raise exception 'Cart line is ambiguous; use cart_item_id';
    end if;
    select * into v from public.cart_items where cart_id=p_cart_id and product_id=p_product_id for update;
  end if;
  if v.id is null then return false; end if;
  if p_quantity=0 then delete from public.cart_items where id=v.id;
  else
    perform private.check_cart_stock(p_cart_id,v.product_id,v.variant_id,v.id,p_quantity,p_test_mode);
    update public.cart_items set quantity=p_quantity,updated_at=clock_timestamp() where id=v.id;
  end if;
  return true;
end $$;

create function public.commerce_cart_claim(p_cart_id uuid,p_user_id uuid,p_guest_session text,p_test_mode boolean default false)
returns boolean language plpgsql security invoker set search_path='' as $$
declare g uuid; i public.cart_items; target public.cart_items; q integer;
begin
  if p_user_id is null then raise exception 'User required'; end if;
  perform private.assert_cart_owner(p_cart_id,p_user_id,null);
  select id into g from public.carts where guest_session_id=p_guest_session;
  if g is null then return false; end if;
  perform private.assert_cart_owner(g,null,p_guest_session);
  -- Stable lock order makes two concurrent claims/adds serialize without losing lines.
  perform 1 from public.carts where id in (g,p_cart_id) order by id for update;
  -- A concurrent successful claim may already have consumed this guest cart.
  if not exists(select 1 from public.carts where id=g) then return false; end if;
  for i in select * from public.cart_items where cart_id=g order by id loop
    select * into target from public.cart_items where cart_id=p_cart_id and product_id=i.product_id
      and variant_id is not distinct from i.variant_id
      and private.cart_vehicle_identity(selected_vehicle)=private.cart_vehicle_identity(i.selected_vehicle) for update;
    q:=i.quantity+coalesce(target.quantity,0);
    perform private.check_cart_stock(p_cart_id,i.product_id,i.variant_id,target.id,q,p_test_mode);
    if target.id is null then
      if (select count(*) from public.cart_items where cart_id=p_cart_id)>=100 then raise exception 'Cart line limit reached'; end if;
      insert into public.cart_items(cart_id,product_id,variant_id,quantity,selected_vehicle)
        values(p_cart_id,i.product_id,i.variant_id,q,i.selected_vehicle);
    else update public.cart_items set quantity=q,updated_at=clock_timestamp() where id=target.id; end if;
  end loop;
  delete from public.carts where id=g;
  return true;
end $$;

revoke all on function private.cart_vehicle_identity(jsonb),private.assert_cart_owner(uuid,uuid,text),
  private.check_cart_quantity(uuid,uuid,integer,boolean),private.guard_cart_variant(),
  private.check_cart_stock(uuid,uuid,uuid,uuid,integer,boolean),
  public.commerce_cart_add(uuid,uuid,text,uuid,uuid,integer,jsonb,boolean),
  public.commerce_cart_update(uuid,uuid,text,uuid,uuid,integer,boolean),
  public.commerce_cart_claim(uuid,uuid,text,boolean) from public,anon,authenticated;
grant execute on function private.cart_vehicle_identity(jsonb),private.assert_cart_owner(uuid,uuid,text),
  private.check_cart_quantity(uuid,uuid,integer,boolean),private.guard_cart_variant(),
  private.check_cart_stock(uuid,uuid,uuid,uuid,integer,boolean),
  public.commerce_cart_add(uuid,uuid,text,uuid,uuid,integer,jsonb,boolean),
  public.commerce_cart_update(uuid,uuid,text,uuid,uuid,integer,boolean),
  public.commerce_cart_claim(uuid,uuid,text,boolean) to service_role;

commit;
