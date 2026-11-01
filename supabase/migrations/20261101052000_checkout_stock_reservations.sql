-- Reserve real inventory before opening Stripe Checkout. Sandbox orders never
-- touch stock. This migration is inert until the checkout route calls the RPC.
alter table public.orders
  add column stock_reserved_at timestamptz,
  add column stock_reservation_expires_at timestamptz,
  add column stock_released_at timestamptz,
  add column stock_shortfall_at timestamptz,
  add column checkout_attempt_key text unique,
  add column checkout_request_hash text;

create index orders_unsettled_reservations_idx
  on public.orders(stock_reservation_expires_at)
  where stock_reserved_at is not null and stock_released_at is null
    and stock_applied_at is null and payment_status in ('unpaid','failed');

-- At most one open Checkout per cart, even when two POSTs use different
-- idempotency keys or the cart changes between browser tabs. Legacy orders do
-- not participate, so this can be added without rewriting historical rows.
create unique index orders_one_open_checkout_per_cart_idx
  on public.orders(cart_id)
  where cart_id is not null and checkout_attempt_key is not null
    and payment_status in ('unpaid','failed') and stock_released_at is null;

-- Lock every distinct product in a stable order, check the entire basket, then
-- change stock. A missing or insufficient line makes no change to any line.
create function private.take_order_stock(p_order_id uuid, p_reason text)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare item record; v_stock integer; v_status text; v_count integer := 0;
begin
  for item in
    select product_id,sum(quantity)::integer as quantity
    from public.order_items where order_id = p_order_id
    group by product_id order by product_id
  loop
    v_count := v_count + 1;
    if item.product_id is null then return false; end if;
    select stock,status::text into v_stock,v_status
      from public.products where id = item.product_id for update;
    if not found or v_status <> 'active' or v_stock < item.quantity then return false; end if;
  end loop;
  if v_count = 0 then return false; end if;

  perform set_config('tymotors.reason',p_reason,true);
  perform set_config('tymotors.reference',p_order_id::text,true);
  for item in
    select product_id,sum(quantity)::integer as quantity
    from public.order_items where order_id = p_order_id
    group by product_id order by product_id
  loop
    update public.products set stock = stock - item.quantity where id = item.product_id;
  end loop;
  return true;
end $$;

create function public.reserve_checkout_stock(p_order_id uuid, p_expires_at timestamptz)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype;
begin
  select * into o from public.orders where id = p_order_id for update;
  if not found then return false; end if;
  if o.is_test then return true; end if;
  if o.stock_reserved_at is not null and o.stock_released_at is null then return true; end if;
  if o.payment_status <> 'unpaid' or o.stock_released_at is not null
    or o.stripe_session_id is not null then
    raise exception 'Order cannot be reserved for checkout';
  end if;
  if p_expires_at is null or p_expires_at <= now() then
    raise exception 'Checkout reservation requires a future expiry';
  end if;
  if not private.take_order_stock(o.id,'checkout_reservation') then
    raise exception 'Insufficient stock while reserving checkout';
  end if;
  update public.orders set stock_reserved_at = now(),
    stock_reservation_expires_at = p_expires_at where id = o.id;
  return true;
end $$;

-- The API passes values calculated from hydrated server-side catalogue rows.
-- One RPC inserts the order and all lines, applies the promotion, and reserves
-- the basket. Any failure rolls the whole statement back. An attempt key makes
-- a lost HTTP response retryable without creating a second reservation.
create function public.create_reserved_checkout_order(
  p_attempt_key text,p_order jsonb,p_items jsonb,p_expires_at timestamptz,
  p_promotion_code text default null
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; v_discount integer := 0; v_count integer;
  v_request_hash text;
begin
  if nullif(btrim(p_attempt_key),'') is null or length(p_attempt_key)>128 then
    raise exception 'Invalid checkout attempt key';
  end if;
  if jsonb_typeof(p_order) <> 'object' or jsonb_typeof(p_items) <> 'array'
    or jsonb_array_length(p_items) not between 1 and 20 then
    raise exception 'Invalid checkout order payload';
  end if;
  if nullif(p_order->>'cart_id','') is null then
    raise exception 'Checkout order requires a cart';
  end if;
  v_request_hash := md5((p_order - 'order_number')::text || p_items::text
    || coalesce(upper(btrim(p_promotion_code)),''));

  select * into o from public.orders where checkout_attempt_key=p_attempt_key for update;
  if found then
    if o.checkout_request_hash is distinct from v_request_hash then
      raise exception 'Checkout attempt payload changed';
    end if;
    if o.payment_status <> 'unpaid' or o.stock_released_at is not null then
      raise exception 'Checkout attempt already closed';
    end if;
    return jsonb_build_object('order_id',o.id,'order_number',o.order_number,
      'total_cents',o.total_cents,'discount_cents',o.discount_amount_cents,
      'stripe_session_id',o.stripe_session_id,'expires_at',o.stock_reservation_expires_at,
      'is_test',o.is_test,'reused',true);
  end if;
  select * into o from public.orders
    where cart_id=(p_order->>'cart_id')::uuid and checkout_attempt_key is not null
      and payment_status in ('unpaid','failed') and stock_released_at is null
    for update;
  if found then
    if o.payment_status <> 'unpaid' then
      raise exception 'Checkout session must be reconciled before retry';
    end if;
    if o.checkout_request_hash is distinct from v_request_hash then
      raise exception 'Active checkout for cart has changed';
    end if;
    return jsonb_build_object('order_id',o.id,'order_number',o.order_number,
      'total_cents',o.total_cents,'discount_cents',o.discount_amount_cents,
      'stripe_session_id',o.stripe_session_id,'expires_at',o.stock_reservation_expires_at,
      'is_test',o.is_test,'reused',true);
  end if;

  insert into public.orders(
    order_number,user_id,cart_id,guest_session_id,subtotal_cents,
    shipping_amount_cents,tax_amount_cents,total_cents,currency,
    requires_compatibility_review,is_test,customer_email,customer_name,
    checkout_attempt_key,checkout_request_hash
  ) values (
    p_order->>'order_number',nullif(p_order->>'user_id','')::uuid,
    nullif(p_order->>'cart_id','')::uuid,p_order->>'guest_session_id',
    (p_order->>'subtotal_cents')::integer,
    coalesce((p_order->>'shipping_amount_cents')::integer,0),
    coalesce((p_order->>'tax_amount_cents')::integer,0),
    (p_order->>'total_cents')::integer,coalesce(p_order->>'currency','EUR'),
    coalesce((p_order->>'requires_compatibility_review')::boolean,false),
    coalesce((p_order->>'is_test')::boolean,false),
    p_order->>'customer_email',p_order->>'customer_name',p_attempt_key,
    v_request_hash
  ) on conflict do nothing returning * into o;
  if not found then
    select * into o from public.orders where checkout_attempt_key=p_attempt_key for update;
    if not found then
      select * into o from public.orders
        where cart_id=(p_order->>'cart_id')::uuid and checkout_attempt_key is not null
          and payment_status in ('unpaid','failed') and stock_released_at is null
        for update;
    end if;
    if not found then raise exception 'Concurrent checkout conflict; retry'; end if;
    if o.payment_status <> 'unpaid' then
      raise exception 'Checkout session must be reconciled before retry';
    end if;
    if o.checkout_request_hash is distinct from v_request_hash then
      raise exception 'Checkout attempt payload changed';
    end if;
    if o.payment_status <> 'unpaid' or o.stock_released_at is not null then
      raise exception 'Checkout attempt already closed';
    end if;
    return jsonb_build_object('order_id',o.id,'order_number',o.order_number,
      'total_cents',o.total_cents,'discount_cents',o.discount_amount_cents,
      'stripe_session_id',o.stripe_session_id,'expires_at',o.stock_reservation_expires_at,
      'is_test',o.is_test,'reused',true);
  end if;

  insert into public.order_items(
    order_id,product_id,product_name,product_slug,sku,quantity,
    unit_amount_cents,currency,image_url,selected_vehicle,compatibility_result
  ) select o.id,i.product_id,i.product_name,i.product_slug,i.sku,i.quantity,
    i.unit_amount_cents,coalesce(i.currency,o.currency),i.image_url,
    i.selected_vehicle,i.compatibility_result
  from jsonb_to_recordset(p_items) as i(
    product_id uuid,product_name text,product_slug text,sku text,quantity integer,
    unit_amount_cents integer,currency text,image_url text,selected_vehicle jsonb,
    compatibility_result jsonb);

  select count(*),coalesce(sum(quantity*unit_amount_cents),0)
    into v_count,v_discount from public.order_items where order_id=o.id;
  if v_count <> jsonb_array_length(p_items)
    or v_discount <> o.subtotal_cents
    or o.total_cents <> o.subtotal_cents+o.shipping_amount_cents+o.tax_amount_cents
    or exists(select 1 from public.order_items where order_id=o.id and currency<>o.currency)
  then raise exception 'Checkout order totals or lines do not match'; end if;

  v_discount := 0;
  if nullif(btrim(p_promotion_code),'') is not null then
    select (public.apply_order_promotion(o.id,upper(btrim(p_promotion_code)))->>'discount_cents')::integer
      into v_discount;
  end if;
  if not public.reserve_checkout_stock(o.id,p_expires_at) then
    raise exception 'Checkout reservation failed';
  end if;
  select * into o from public.orders where id=o.id;
  return jsonb_build_object('order_id',o.id,'order_number',o.order_number,
    'total_cents',o.total_cents,'discount_cents',v_discount,
    'stripe_session_id',o.stripe_session_id,'expires_at',o.stock_reservation_expires_at,
    'is_test',o.is_test,'reused',false);
end $$;

create function public.release_checkout_stock(p_order_id uuid, p_reason text)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; item record;
begin
  -- A failed PaymentIntent does not prove that the Checkout Session is closed;
  -- the buyer may still retry payment in the same live session.
  if p_reason not in ('stripe_creation_failed','stripe_expired','stripe_async_failed') then
    raise exception 'Invalid reservation release reason';
  end if;
  select * into o from public.orders where id = p_order_id for update;
  if not found then return false; end if;
  if o.is_test or o.payment_status in ('paid','refunded')
    or o.stock_applied_at is not null or o.stock_reserved_at is null
    or o.stock_released_at is not null then return false; end if;
  if p_reason='stripe_creation_failed' and o.stripe_session_id is not null then
    raise exception 'Open Checkout session must be expired before release';
  end if;

  perform set_config('tymotors.reason','checkout_release_' || p_reason,true);
  perform set_config('tymotors.reference',o.id::text,true);
  for item in
    select product_id,sum(quantity)::integer as quantity
    from public.order_items where order_id = o.id
    group by product_id order by product_id
  loop
    if item.product_id is null then raise exception 'Reserved order lost a product'; end if;
    update public.products set stock = stock + item.quantity where id = item.product_id;
    if not found then raise exception 'Reserved order lost a product'; end if;
  end loop;
  update public.orders set stock_released_at = now() where id = o.id;
  return true;
end $$;

-- Preserve the existing test flow. Real orders use their reservation; legacy
-- sessions or payments arriving after release recheck stock atomically.
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
    if o.stripe_session_id is null or left(o.stripe_session_id,8) <> 'cs_test_' then
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

-- Do not send a captured, out-of-stock payment to a supplier. It needs a human
-- decision (replacement or refund) and remains visible in the admin.
create or replace function private.queue_supplier_order()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.payment_status in ('paid','refunded') and old.payment_status not in ('paid','refunded') then
    if new.is_test then
      insert into public.order_tracking_events(order_id,event_key,title,description,source)
      values(new.id,'payment_confirmed','Paiement de test confirmé',
        'Essai Stripe : aucun débit réel ni expédition.','system')
      on conflict(order_id,event_key) where event_key in
        ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent',
         'quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled')
      do nothing;
    elsif new.stock_shortfall_at is not null then
      insert into public.order_tracking_events(order_id,event_key,title,description,source)
      values(new.id,'payment_stock_review','Paiement reçu — vérification nécessaire',
        'Le stock doit être confirmé avant la préparation de cette commande.','system')
      on conflict do nothing;
    else
      perform private.ensure_supplier_order(new.id);
    end if;
  end if;
  return new;
end $$;

revoke all on function private.take_order_stock(uuid,text),
  public.reserve_checkout_stock(uuid,timestamptz),
  public.release_checkout_stock(uuid,text),
  public.create_reserved_checkout_order(text,jsonb,jsonb,timestamptz,text)
  from public,anon,authenticated;
grant execute on function private.take_order_stock(uuid,text),
  public.reserve_checkout_stock(uuid,timestamptz),
  public.release_checkout_stock(uuid,text),
  public.create_reserved_checkout_order(text,jsonb,jsonb,timestamptz,text)
  to service_role;

notify pgrst, 'reload schema';
