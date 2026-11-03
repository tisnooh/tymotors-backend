-- Internal zero-euro Checkout diagnostic. This is never a sellable catalogue item.
-- Apply only after reviewing the backend endpoint and its isolated database tests.

create unique index if not exists orders_one_open_zero_diagnostic_per_admin
  on public.orders(user_id)
  where sales_channel='diagnostic' and is_test and payment_status='unpaid';

create or replace function private.guard_zero_diagnostic_product()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if tg_op='UPDATE' and old.sku='TY-INTERNAL-ZERO-DIAGNOSTIC'
    and new.sku is distinct from old.sku then
    raise exception 'Internal diagnostic product SKU is immutable';
  end if;
  if new.sku='TY-INTERNAL-ZERO-DIAGNOSTIC' and (
    new.status is distinct from 'archived'::public.product_status
    or new.is_verified is distinct from false or new.price_cents <> 0
    or new.stock <> 0 or new.featured is distinct from false
    or new.specs->>'internal_diagnostic' is distinct from 'true'
  ) then
    raise exception 'Internal diagnostic product cannot be published or stocked';
  end if;
  return new;
end $$;

create trigger guard_zero_diagnostic_product_before_write
before insert or update on public.products
for each row execute function private.guard_zero_diagnostic_product();

create or replace function private.guard_zero_diagnostic_order()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
  if (tg_op='UPDATE' and old.sales_channel='diagnostic') or new.sales_channel='diagnostic' then
    if new.sales_channel is distinct from 'diagnostic'
      or new.is_test is distinct from true or new.user_id is null
      or new.cart_id is not null or new.guest_session_id is not null
      or new.subtotal_cents <> 0 or new.shipping_amount_cents <> 0
      or new.tax_amount_cents <> 0 or new.discount_amount_cents <> 0
      or new.total_cents <> 0 or new.currency <> 'EUR'
      or coalesce(new.checkout_attempt_key,'') !~ '^admin-zero:[0-9a-f-]{36}$'
    then
      raise exception 'Internal diagnostic order must stay zero-value and isolated';
    end if;
    if tg_op='UPDATE' and old.sales_channel='diagnostic' and (
      new.user_id is distinct from old.user_id
      or new.checkout_attempt_key is distinct from old.checkout_attempt_key
      or new.order_number is distinct from old.order_number
      or (old.stripe_session_id is not null
          and new.stripe_session_id is distinct from old.stripe_session_id)
    ) then
      raise exception 'Internal diagnostic order identity is immutable';
    end if;
  end if;
  return new;
end $$;

create trigger guard_zero_diagnostic_order_before_write
before insert or update on public.orders
for each row execute function private.guard_zero_diagnostic_order();

create or replace function private.guard_zero_diagnostic_line()
returns trigger language plpgsql security invoker set search_path = '' as $$
declare v_channel text; v_old_channel text; v_sku text;
begin
  if tg_op='UPDATE' then
    select sales_channel into v_old_channel from public.orders where id=old.order_id;
  end if;
  select sales_channel into v_channel from public.orders
  where id=case when tg_op='DELETE' then old.order_id else new.order_id end;
  if tg_op='DELETE' then
    if v_channel='diagnostic' or old.sku='TY-INTERNAL-ZERO-DIAGNOSTIC' then
      raise exception 'Internal diagnostic line cannot be deleted';
    end if;
    return old;
  end if;
  select sku into v_sku from public.products where id=new.product_id;
  if v_channel='diagnostic' or v_old_channel='diagnostic'
    or new.sku='TY-INTERNAL-ZERO-DIAGNOSTIC'
    or v_sku='TY-INTERNAL-ZERO-DIAGNOSTIC' then
    if v_old_channel='diagnostic' and new.order_id is distinct from old.order_id then
      raise exception 'Internal diagnostic line cannot be moved';
    end if;
    if v_channel is distinct from 'diagnostic' then
      raise exception 'Internal diagnostic product cannot enter a commercial order';
    end if;
    if new.sku is distinct from 'TY-INTERNAL-ZERO-DIAGNOSTIC'
      or v_sku is distinct from new.sku or new.quantity <> 1
      or new.unit_amount_cents <> 0 or new.currency <> 'EUR' then
      raise exception 'Internal diagnostic order requires its exact zero-value product';
    end if;
    if tg_op='INSERT' and exists (
      select 1 from public.order_items where order_id=new.order_id
    ) then
      raise exception 'Internal diagnostic order allows one line only';
    end if;
  end if;
  return new;
end $$;

create trigger guard_zero_diagnostic_line_before_write
before insert or update or delete on public.order_items
for each row execute function private.guard_zero_diagnostic_line();

create or replace function public.create_admin_zero_diagnostic_order(p_admin_id uuid)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_profile public.profiles%rowtype; v_product public.products%rowtype;
  v_category uuid; v_order public.orders%rowtype;
begin
  select * into v_profile from public.profiles where id=p_admin_id and role='admin';
  if not found then raise exception 'Administrator required for zero-value diagnostic'; end if;

  -- The product is archived and has no inventory, image or supplier. The
  -- catalogue's public queries exclude archived products.
  select * into v_product from public.products
    where sku='TY-INTERNAL-ZERO-DIAGNOSTIC' for update;
  if not found then
    select id into v_category from public.categories order by id limit 1;
    if v_category is null then raise exception 'A category is required for internal diagnostic'; end if;
    insert into public.products(slug,sku,name,description,category_id,price_cents,
      currency,stock,status,is_verified,featured,specs)
    values('internal-zero-diagnostic','TY-INTERNAL-ZERO-DIAGNOSTIC',
      'Diagnostic interne Stripe 0 €',
      'Diagnostic technique interne ; aucun article physique ni expédition.',
      v_category,0,'EUR',0,'archived',false,false,
      '{"internal_diagnostic":true,"physical":false}'::jsonb)
    on conflict do nothing returning * into v_product;
    if not found then
      select * into v_product from public.products
        where sku='TY-INTERNAL-ZERO-DIAGNOSTIC' for update;
    end if;
  end if;
  if v_product.sku is distinct from 'TY-INTERNAL-ZERO-DIAGNOSTIC'
    or v_product.status is distinct from 'archived'::public.product_status
    or v_product.price_cents <> 0 or v_product.stock <> 0
    or v_product.is_verified is distinct from false then
    raise exception 'Internal diagnostic product is not isolated';
  end if;

  select * into v_order from public.orders
  where user_id=p_admin_id and sales_channel='diagnostic' and is_test
    and payment_status='unpaid' order by created_at desc limit 1 for update;
  if found then
    return jsonb_build_object('order_id',v_order.id,'order_number',v_order.order_number,
      'stripe_session_id',v_order.stripe_session_id,'reused',true);
  end if;

  insert into public.orders(order_number,user_id,customer_email,subtotal_cents,
    shipping_amount_cents,tax_amount_cents,total_cents,currency,is_test,
    sales_channel,checkout_attempt_key,requires_compatibility_review)
  values('TY-DIAG-' || upper(substr(replace(gen_random_uuid()::text,'-',''),1,16)),
    p_admin_id,v_profile.email,0,0,0,0,'EUR',true,'diagnostic',
    'admin-zero:' || gen_random_uuid()::text,false)
  on conflict do nothing returning * into v_order;
  if not found then
    select * into v_order from public.orders
      where user_id=p_admin_id and sales_channel='diagnostic' and is_test
        and payment_status='unpaid' order by created_at desc limit 1 for update;
    if not found then raise exception 'Concurrent zero-value diagnostic conflict'; end if;
    return jsonb_build_object('order_id',v_order.id,'order_number',v_order.order_number,
      'stripe_session_id',v_order.stripe_session_id,'reused',true);
  end if;

  insert into public.order_items(order_id,product_id,product_name,product_slug,sku,
    quantity,unit_amount_cents,currency,compatibility_result)
  values(v_order.id,v_product.id,v_product.name,v_product.slug,v_product.sku,
    1,0,'EUR','{"status":"not_applicable","reason":"admin-only zero-value diagnostic"}'::jsonb);
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_admin_id,'diagnostic.zero_checkout.created',v_order.id::text,
    jsonb_build_object('scope','stripe_order_only','amount_cents',0));
  return jsonb_build_object('order_id',v_order.id,'order_number',v_order.order_number,
    'stripe_session_id',null,'reused',false);
end $$;

-- Existing sandbox behaviour is preserved. Only the strongly identified
-- internal zero-euro order may complete from a live Checkout session.
create or replace function public.complete_paid_order(
  p_order_id uuid,p_payment_intent_id text,p_customer_email text,p_customer_name text,
  p_shipping_address jsonb,p_billing_address jsonb
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; v_stock_secured boolean := false;
begin
  select * into o from public.orders where id = p_order_id for update;
  if not found then return false; end if;
  if o.stock_applied_at is not null or o.payment_status in ('paid','refunded') then return true; end if;
  if o.is_test then
    if o.sales_channel='diagnostic' then
      if o.total_cents <> 0 or coalesce(o.checkout_attempt_key,'') !~ '^admin-zero:[0-9a-f-]{36}$'
        or o.stripe_session_id is null or left(o.stripe_session_id,8) <> 'cs_live_'
        or p_payment_intent_id is not null
        or (select count(*) from public.order_items where order_id=o.id) <> 1
        or not exists (
          select 1 from public.order_items i join public.products p on p.id=i.product_id
          where i.order_id=o.id and i.sku='TY-INTERNAL-ZERO-DIAGNOSTIC'
            and p.sku=i.sku and p.status='archived' and i.unit_amount_cents=0
            and i.quantity=1
        ) then
        raise exception 'Invalid live zero-value diagnostic order';
      end if;
    elsif o.stripe_session_id is null or left(o.stripe_session_id,8) <> 'cs_test_' then
      raise exception 'A test order requires a sandbox Checkout session';
    end if;
  else
    v_stock_secured := o.stock_reserved_at is not null and o.stock_released_at is null;
    if not v_stock_secured then
      v_stock_secured := private.take_order_stock(o.id,'paid_order_late');
    end if;
    if v_stock_secured then
      update public.order_items i set cost_price_cents=s.cost_price_cents
      from public.product_supplier_data s
      where i.order_id=o.id and i.product_id=s.product_id;
    end if;
  end if;
  update public.orders set payment_status='paid',
    status=case when status='cancelled' then status else 'paid'::public.order_status end,
    fulfillment_status=case when status='cancelled' or requires_compatibility_review
      or is_test or not v_stock_secured then 'requires_review'::public.fulfillment_status
      else fulfillment_status end,
    stripe_payment_intent_id=p_payment_intent_id,
    customer_email=coalesce(p_customer_email,customer_email),
    customer_name=coalesce(p_customer_name,customer_name),
    shipping_address=coalesce(p_shipping_address,'{}'),
    billing_address=coalesce(p_billing_address,'{}'),paid_at=now(),
    stock_applied_at=case when is_test or not v_stock_secured then null else now() end,
    stock_shortfall_at=case when is_test or v_stock_secured then null else now() end
  where id=o.id;
  if o.cart_id is not null then delete from public.cart_items where cart_id=o.cart_id; end if;
  insert into public.admin_audit(action,resource,metadata)
    values('order.paid',o.id::text,jsonb_build_object('payment_intent',p_payment_intent_id,
      'is_test',o.is_test,'stock_secured',v_stock_secured));
  return true;
end $$;

revoke all on function public.create_admin_zero_diagnostic_order(uuid)
  from public,anon,authenticated;
grant execute on function public.create_admin_zero_diagnostic_order(uuid) to service_role;
revoke all on function private.guard_zero_diagnostic_product(),
  private.guard_zero_diagnostic_order(),private.guard_zero_diagnostic_line()
  from public,anon,authenticated;

notify pgrst, 'reload schema';
