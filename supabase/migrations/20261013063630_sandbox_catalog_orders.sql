-- Server-owned sandbox marker. Do not publish drafts or invent real inventory.
alter table public.orders add column is_test boolean not null default false;

create or replace function public.complete_paid_order(
  p_order_id uuid,p_payment_intent_id text,p_customer_email text,p_customer_name text,
  p_shipping_address jsonb,p_billing_address jsonb
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; item record;
begin
  select * into o from public.orders where id=p_order_id for update;
  if not found then return false; end if;
  if o.stock_applied_at is not null or o.payment_status in ('paid','refunded') then return true; end if;
  if o.is_test then
    if o.stripe_session_id is null or left(o.stripe_session_id,8) <> 'cs_test_' then
      raise exception 'A test order requires a sandbox Checkout session';
    end if;
  else
    perform set_config('tymotors.reason','paid_order',true);
    perform set_config('tymotors.reference',o.id::text,true);
    -- Real purchases retain the stable locking order and actual inventory check.
    for item in select product_id,sum(quantity)::integer quantity from public.order_items
      where order_id=o.id group by product_id order by product_id loop
      if item.product_id is null then raise exception 'Missing product'; end if;
      update public.products set stock=stock-item.quantity where id=item.product_id and stock>=item.quantity;
      if not found then raise exception 'Insufficient stock while completing order'; end if;
    end loop;
    update public.order_items i set cost_price_cents=s.cost_price_cents from public.product_supplier_data s
    where i.order_id=o.id and i.product_id=s.product_id;
  end if;
  update public.orders set payment_status='paid',status=case when status='cancelled' then status else 'paid'::public.order_status end,
    fulfillment_status=case when status='cancelled' or requires_compatibility_review or is_test then 'requires_review'::public.fulfillment_status else fulfillment_status end,
    stripe_payment_intent_id=p_payment_intent_id,customer_email=coalesce(p_customer_email,customer_email),
    customer_name=coalesce(p_customer_name,customer_name),shipping_address=coalesce(p_shipping_address,'{}'),
    billing_address=coalesce(p_billing_address,'{}'),paid_at=now(),
    stock_applied_at=case when is_test then null else now() end where id=o.id;
  if o.cart_id is not null then delete from public.cart_items where cart_id=o.cart_id; end if;
  insert into public.admin_audit(action,resource,metadata)
    values('order.paid',o.id::text,jsonb_build_object('payment_intent',p_payment_intent_id,'is_test',o.is_test));
  return true;
end $$;

-- Sandbox orders stay visible in the admin, but never enter the supplier queue.
create or replace function private.queue_supplier_order()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.payment_status in ('paid','refunded') and old.payment_status not in ('paid','refunded') then
    if new.is_test then
      insert into public.order_tracking_events(order_id,event_key,title,description,source)
      values(new.id,'payment_confirmed','Paiement de test confirmé','Essai Stripe : aucun débit réel ni expédition.','system')
      on conflict(order_id,event_key) where event_key in ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled') do nothing;
    else
      perform private.ensure_supplier_order(new.id);
    end if;
  end if;
  return new;
end $$;

revoke all on function public.complete_paid_order(uuid,text,text,text,jsonb,jsonb),private.queue_supplier_order() from public,anon,authenticated;
grant execute on function public.complete_paid_order(uuid,text,text,text,jsonb,jsonb),private.queue_supplier_order() to service_role;

-- Guard explicit supplier creation and test returns against real operations.
create function private.guard_test_operations()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if exists(select 1 from public.orders where id=new.order_id and is_test) then
    if tg_table_name='supplier_orders' then
      raise exception 'Test orders cannot enter supplier fulfillment';
    elsif new.restocked_at is not null then
      raise exception 'Test returns cannot restock real inventory';
    end if;
  end if;
  return new;
end $$;
create trigger guard_test_supplier before insert or update on public.supplier_orders
for each row execute function private.guard_test_operations();
create trigger guard_test_restock before insert or update on public.returns
for each row execute function private.guard_test_operations();
revoke all on function private.guard_test_operations() from public,anon,authenticated;
grant execute on function private.guard_test_operations() to service_role;
