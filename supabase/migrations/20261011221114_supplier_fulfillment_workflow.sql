-- Manual supplier approval and professional customer tracking.
-- No marketplace purchase or agent shipment is executed by this migration.

create table public.supplier_orders (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null unique references public.orders(id) on delete cascade,
  status text not null default 'pending_validation' check (status in (
    'pending_validation','approved','ordered','received_by_agent','quality_control',
    'ready_to_ship','requires_attention','cancelled'
  )),
  agent_provider text not null default 'CJdropshipping',
  agent_connection_status text not null default 'not_connected' check (agent_connection_status in ('not_connected','onboarding','connected')),
  alibaba_order_id text,
  agent_order_id text,
  notes text,
  approved_by uuid references public.profiles(id) on delete set null,
  approved_at timestamptz,
  ordered_at timestamptz,
  received_by_agent_at timestamptz,
  quality_checked_at timestamptz,
  ready_to_ship_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.supplier_order_items (
  id uuid primary key default gen_random_uuid(),
  supplier_order_id uuid not null references public.supplier_orders(id) on delete cascade,
  order_item_id uuid not null unique references public.order_items(id) on delete cascade,
  product_id uuid references public.products(id) on delete set null,
  product_name text not null,
  sku text not null,
  quantity integer not null check (quantity between 1 and 20),
  supplier_name text,
  supplier_reference text,
  supplier_url text,
  exact_source_url text,
  unit_cost_cents integer check (unit_cost_cents >= 0),
  currency text not null default 'EUR' check (currency ~ '^[A-Z]{3}$'),
  created_at timestamptz not null default now()
);

create table public.order_tracking_events (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  event_key text not null,
  title text not null,
  description text,
  location text,
  source text not null default 'system' check (source in ('system','admin','supplier','agent','carrier')),
  is_customer_visible boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index supplier_orders_status_created_idx on public.supplier_orders(status, created_at desc);
create index supplier_order_items_supplier_idx on public.supplier_order_items(supplier_order_id);
create index supplier_order_items_product_idx on public.supplier_order_items(product_id);
create index order_tracking_events_order_idx on public.order_tracking_events(order_id, occurred_at, id);
create unique index order_tracking_event_unique_idx on public.order_tracking_events(order_id, event_key)
  where event_key in ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled');

create trigger supplier_orders_updated_at before update on public.supplier_orders
for each row execute function public.set_updated_at();

alter table public.supplier_orders enable row level security;
alter table public.supplier_order_items enable row level security;
alter table public.order_tracking_events enable row level security;
revoke all on public.supplier_orders,public.supplier_order_items,public.order_tracking_events from anon,authenticated;
grant select,insert,update,delete on public.supplier_orders,public.supplier_order_items,public.order_tracking_events to service_role;

create or replace function private.ensure_supplier_order(p_order_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare v_supplier_order_id uuid;
begin
  insert into public.supplier_orders(order_id)
  select o.id from public.orders o
  where o.id=p_order_id and o.payment_status in ('paid','refunded')
  on conflict(order_id) do update set order_id=excluded.order_id
  returning id into v_supplier_order_id;

  if v_supplier_order_id is null then return null; end if;

  insert into public.supplier_order_items(
    supplier_order_id,order_item_id,product_id,product_name,sku,quantity,
    supplier_name,supplier_reference,supplier_url,exact_source_url,unit_cost_cents,currency
  )
  select v_supplier_order_id,i.id,i.product_id,i.product_name,i.sku,i.quantity,
    s.supplier_name,s.supplier_reference,s.supplier_url,s.exact_source_url,
    coalesce(i.cost_price_cents,s.cost_price_cents),i.currency
  from public.order_items i
  left join public.product_supplier_data s on s.product_id=i.product_id
  where i.order_id=p_order_id
  on conflict(order_item_id) do nothing;

  insert into public.order_tracking_events(order_id,event_key,title,description,source)
  values(p_order_id,'payment_confirmed','Paiement confirmé','Votre commande est enregistrée et va être vérifiée par notre équipe.','system')
  on conflict(order_id,event_key) where event_key in ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled') do nothing;

  return v_supplier_order_id;
end $$;

create or replace function private.queue_supplier_order()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.payment_status in ('paid','refunded') and old.payment_status not in ('paid','refunded') then
    perform private.ensure_supplier_order(new.id);
  end if;
  return new;
end $$;

create trigger queue_supplier_order_after_payment
after update of payment_status on public.orders
for each row execute function private.queue_supplier_order();

-- Backfill already-paid orders safely and idempotently.
select private.ensure_supplier_order(id) from public.orders where payment_status in ('paid','refunded');

create or replace function public.admin_update_supplier_order(
  p_actor uuid,
  p_order_id uuid,
  p_status text,
  p_alibaba_order_id text,
  p_agent_order_id text,
  p_agent_provider text,
  p_agent_connection_status text,
  p_notes text,
  p_expected timestamptz
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare current_row public.supplier_orders%rowtype; missing_links integer; v_event_key text; event_title text; event_description text; event_source text;
begin
  perform private.assert_admin(p_actor);
  select * into strict current_row from public.supplier_orders where order_id=p_order_id for update;
  if current_row.updated_at<>p_expected then raise exception 'Supplier order changed; reload before saving'; end if;
  if p_status not in ('pending_validation','approved','ordered','received_by_agent','quality_control','ready_to_ship','requires_attention','cancelled') then
    raise exception 'Invalid supplier status';
  end if;
  if p_status<>current_row.status and not (
    (current_row.status='pending_validation' and p_status in ('approved','requires_attention','cancelled')) or
    (current_row.status='approved' and p_status in ('ordered','requires_attention','cancelled')) or
    (current_row.status='ordered' and p_status in ('received_by_agent','requires_attention','cancelled')) or
    (current_row.status='received_by_agent' and p_status in ('quality_control','ready_to_ship','requires_attention','cancelled')) or
    (current_row.status='quality_control' and p_status in ('ready_to_ship','requires_attention','cancelled')) or
    (current_row.status='requires_attention' and p_status in ('approved','ordered','received_by_agent','quality_control','ready_to_ship','cancelled')) or
    (current_row.status=p_status)
  ) then raise exception 'Invalid supplier order transition'; end if;

  if p_status='approved' then
    select count(*) into missing_links from public.supplier_order_items
      where supplier_order_id=current_row.id and nullif(trim(coalesce(exact_source_url,'')),'') is null;
    if missing_links>0 then raise exception 'Every item requires an exact Alibaba product link before approval'; end if;
  end if;
  if p_status in ('ordered','received_by_agent','quality_control','ready_to_ship') and nullif(trim(coalesce(p_alibaba_order_id,current_row.alibaba_order_id,'')),'') is null then
    raise exception 'Alibaba order ID required';
  end if;
  if p_status in ('received_by_agent','quality_control','ready_to_ship') and nullif(trim(coalesce(p_agent_order_id,current_row.agent_order_id,'')),'') is null then
    raise exception 'Agent order ID required';
  end if;

  update public.supplier_orders set
    status=p_status,
    alibaba_order_id=coalesce(nullif(trim(p_alibaba_order_id),''),alibaba_order_id),
    agent_order_id=coalesce(nullif(trim(p_agent_order_id),''),agent_order_id),
    agent_provider=coalesce(nullif(trim(p_agent_provider),''),agent_provider),
    agent_connection_status=p_agent_connection_status,
    notes=nullif(trim(p_notes),''),
    approved_by=case when p_status='approved' then p_actor else approved_by end,
    approved_at=case when p_status='approved' then coalesce(approved_at,now()) else approved_at end,
    ordered_at=case when p_status='ordered' then coalesce(ordered_at,now()) else ordered_at end,
    received_by_agent_at=case when p_status='received_by_agent' then coalesce(received_by_agent_at,now()) else received_by_agent_at end,
    quality_checked_at=case when p_status='quality_control' then coalesce(quality_checked_at,now()) else quality_checked_at end,
    ready_to_ship_at=case when p_status='ready_to_ship' then coalesce(ready_to_ship_at,now()) else ready_to_ship_at end
  where id=current_row.id;

  if p_status in ('approved','ordered','received_by_agent','quality_control','ready_to_ship') then
    update public.orders set fulfillment_status='processing'
    where id=p_order_id and fulfillment_status in ('unfulfilled','requires_review');
  end if;

  event_title := case p_status
    when 'approved' then 'Commande vérifiée'
    when 'ordered' then 'Commande transmise au fournisseur'
    when 'received_by_agent' then 'Réception au centre logistique'
    when 'quality_control' then 'Contrôle qualité'
    when 'ready_to_ship' then 'Prête à être expédiée'
    when 'cancelled' then 'Commande annulée'
    else null end;
  v_event_key := case p_status
    when 'approved' then 'supplier_approved'
    when 'ordered' then 'supplier_ordered'
    when 'received_by_agent' then 'received_by_agent'
    when 'quality_control' then 'quality_control'
    when 'ready_to_ship' then 'ready_to_ship'
    when 'cancelled' then 'order_cancelled'
    else null end;
  event_description := case p_status
    when 'approved' then 'Les références et la compatibilité de votre commande ont été validées.'
    when 'ordered' then 'Les articles ont été commandés auprès du fournisseur.'
    when 'received_by_agent' then 'Le centre logistique a réceptionné les articles.'
    when 'quality_control' then 'Les articles sont contrôlés avant leur expédition.'
    when 'ready_to_ship' then 'Votre colis est préparé et attend sa prise en charge par le transporteur.'
    when 'cancelled' then 'Le traitement logistique de cette commande a été annulé.'
    else null end;
  event_source := case when p_status in ('received_by_agent','quality_control','ready_to_ship') then 'agent' else 'admin' end;
  if event_title is not null then
    insert into public.order_tracking_events(order_id,event_key,title,description,source,metadata)
    values(p_order_id,v_event_key,event_title,event_description,event_source,
      jsonb_build_object('supplier_status',p_status,'agent_provider',coalesce(nullif(trim(p_agent_provider),''),current_row.agent_provider)))
    on conflict(order_id,event_key) where event_key in ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled')
    do update set title=excluded.title,description=excluded.description,source=excluded.source,metadata=excluded.metadata,occurred_at=now();
  end if;

  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'supplier_order.update',p_order_id::text,jsonb_build_object(
    'before',jsonb_build_object('status',current_row.status,'alibaba_order_id',current_row.alibaba_order_id,'agent_order_id',current_row.agent_order_id),
    'after',jsonb_build_object('status',p_status,'alibaba_order_id',p_alibaba_order_id,'agent_order_id',p_agent_order_id)
  ));
  return (select to_jsonb(s) from public.supplier_orders s where s.id=current_row.id);
end $$;

-- Keep the public fulfillment timeline in the same transaction as order state changes.
create or replace function public.admin_update_order(p_actor uuid,p_id uuid,p_status text,p_tracking text,p_expected timestamptz)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; title text; description text;
begin
  perform private.assert_admin(p_actor);
  select * into strict o from public.orders where id=p_id for update;
  if o.updated_at<>p_expected then raise exception 'Order changed; reload before saving'; end if;
  if p_status<>o.fulfillment_status::text then
    if o.fulfillment_status in ('cancelled','delivered') then raise exception 'This order is closed'; end if;
    if o.fulfillment_status='shipped' and p_status<>'delivered' then raise exception 'Invalid transition'; end if;
    if p_status not in ('unfulfilled','processing','shipped','delivered','cancelled','requires_review') then raise exception 'Invalid status'; end if;
    if p_status='delivered' and o.fulfillment_status<>'shipped' then raise exception 'Ship the order first'; end if;
    if p_status='shipped' and (o.fulfillment_status not in ('unfulfilled','processing','requires_review') or nullif(trim(p_tracking),'') is null) then raise exception 'Tracking number required'; end if;
    if p_status='cancelled' and o.fulfillment_status='shipped' then raise exception 'Use a return for shipped orders'; end if;
  end if;
  update public.orders set fulfillment_status=p_status::public.fulfillment_status,tracking_number=nullif(trim(p_tracking),''),
    status=case when p_status='cancelled' then 'cancelled'::public.order_status else status end,
    shipped_at=case when p_status='shipped' then coalesce(shipped_at,now()) else shipped_at end,
    delivered_at=case when p_status='delivered' then coalesce(delivered_at,now()) else delivered_at end
  where id=p_id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'order.update',p_id::text,jsonb_build_object('before',jsonb_build_object('status',o.fulfillment_status,'tracking',o.tracking_number),
    'after',jsonb_build_object('status',p_status,'tracking',p_tracking)));

  title := case p_status when 'shipped' then 'Commande expédiée' when 'delivered' then 'Commande livrée' when 'cancelled' then 'Commande annulée' else null end;
  description := case p_status when 'shipped' then 'Votre colis a été confié au transporteur.' when 'delivered' then 'Le transporteur indique que votre colis a été livré.' when 'cancelled' then 'Cette commande a été annulée.' else null end;
  if title is not null and p_status<>o.fulfillment_status::text then
    insert into public.order_tracking_events(order_id,event_key,title,description,source,metadata)
    values(p_id,'order_'||p_status,title,description,'admin',jsonb_build_object('tracking_number',nullif(trim(p_tracking),'')))
    on conflict(order_id,event_key) where event_key in ('payment_confirmed','supplier_approved','supplier_ordered','received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled')
    do update set title=excluded.title,description=excluded.description,metadata=excluded.metadata,occurred_at=now();
  end if;
  return jsonb_build_object('updated',true);
end $$;

revoke all on function private.ensure_supplier_order(uuid),private.queue_supplier_order() from public,anon,authenticated;
revoke all on function public.admin_update_supplier_order(uuid,uuid,text,text,text,text,text,text,timestamptz) from public,anon,authenticated;
grant execute on function private.ensure_supplier_order(uuid),private.queue_supplier_order() to service_role;
grant execute on function public.admin_update_supplier_order(uuid,uuid,text,text,text,text,text,text,timestamptz) to service_role;
