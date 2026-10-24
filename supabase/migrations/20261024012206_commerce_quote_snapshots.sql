-- Private, immutable quote snapshots; no live checkout, payment or stock effects.
begin;

alter table public.shipping_rates add column multi_variant_policy text not null default 'unknown'
  check(multi_variant_policy in('unknown','independent_parcels'));
-- Amend the existing flat RPC contract, without duplicating its audited guards.
-- Exact anchors are asserted: incompatible migration drift fails closed.
do $amend$ declare definition text; begin
  select pg_get_functiondef('public.admin_save_commerce_record(uuid,text,uuid,jsonb,timestamptz)'::regprocedure) into definition;
  if strpos(definition,'''customer_shipping_cents'',''goods_tax_bps''')=0
    or strpos(definition,'{"postal_prefix":"","min_quantity":1,"currency":"EUR","verification_state":"pending"}')=0
    or strpos(definition,'customer_shipping_cents=v_rate.customer_shipping_cents,goods_tax_bps')=0 then
    raise exception 'Commerce RPC definition changed; review multi-variant policy amendment';
  end if;
  definition:=replace(definition,'''customer_shipping_cents'',''goods_tax_bps''','''customer_shipping_cents'',''multi_variant_policy'',''goods_tax_bps''');
  definition:=replace(definition,'{"postal_prefix":"","min_quantity":1,"currency":"EUR","verification_state":"pending"}',
    '{"postal_prefix":"","min_quantity":1,"currency":"EUR","verification_state":"pending","multi_variant_policy":"unknown"}');
  definition:=replace(definition,'customer_shipping_cents=v_rate.customer_shipping_cents,goods_tax_bps',
    'customer_shipping_cents=v_rate.customer_shipping_cents,multi_variant_policy=v_rate.multi_variant_policy,goods_tax_bps');
  execute definition;
end $amend$;

create function public.commerce_cart_context(p_cart_id uuid,p_user_id uuid,p_guest_session text,p_country text,p_postal_code text,p_mode text)
returns jsonb language plpgsql stable security invoker set search_path='' set timezone='UTC' as $$
declare result jsonb; n bigint;
begin
  perform private.assert_cart_owner(p_cart_id,p_user_id,p_guest_session);
  if p_country is null or p_country !~ '^[A-Z]{2}$' or p_mode is null or length(trim(p_mode)) not between 1 and 100 then
    raise exception 'Invalid quote destination or mode';
  end if;
  if p_postal_code is null or length(p_postal_code) not between 1 and 20 or p_postal_code !~ '^[A-Za-z0-9 -]+$' then raise exception 'Invalid quote postal code'; end if;
  select count(*) into n from public.cart_items where cart_id=p_cart_id;
  if n>100 then raise exception 'Commerce context exceeds cart line limit'; end if;
  select count(*) into n from public.supplier_offers o where o.variant_id in
    (select variant_id from public.cart_items where cart_id=p_cart_id);
  if n>1000 then raise exception 'Commerce context exceeds offer limit'; end if;
  select count(*) into n from public.shipping_rates r where r.country=p_country and r.mode=p_mode and r.offer_id in
    (select o.id from public.supplier_offers o where o.variant_id in(select variant_id from public.cart_items where cart_id=p_cart_id));
  if n>1000 then raise exception 'Commerce context exceeds shipping rule limit'; end if;
  select count(*) into n from public.product_compatibilities where product_id in
    (select product_id from public.cart_items where cart_id=p_cart_id);
  if n>1000 then raise exception 'Commerce context exceeds compatibility rule limit'; end if;
  with ci as materialized(select * from public.cart_items where cart_id=p_cart_id),
    p as materialized(select * from public.products where id in(select product_id from ci)),
    v as materialized(select * from public.product_variants where id in(select variant_id from ci)),
    o as materialized(select * from public.supplier_offers where variant_id in(select id from v)),
    c as materialized(select * from public.product_compatibilities where product_id in(select id from p)),
    g as materialized(select * from public.vehicle_generations where id in(select generation_id from c))
  select jsonb_build_object(
    'cart',(select to_jsonb(t) from public.carts t where id=p_cart_id),'country',p_country,'postal_code',p_postal_code,'mode',p_mode,
    'cart_items',coalesce((select jsonb_agg(to_jsonb(t) order by id) from ci t),'[]'),
    'products',coalesce((select jsonb_agg(to_jsonb(t) order by id) from p t),'[]'),
    'product_images',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.product_images t where product_id in(select id from p)),'[]'),
    'variants',coalesce((select jsonb_agg(to_jsonb(t) order by id) from v t),'[]'),
    'offers',coalesce((select jsonb_agg(to_jsonb(t) order by id) from o t),'[]'),
    'rates',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.shipping_rates t where offer_id in(select id from o) and country=p_country and mode=p_mode),'[]'),
    'agents',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.commerce_agents t where id in(select responsible_agent_id from o)),'[]'),
    'suppliers',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.suppliers t where id in(select supplier_id from o)),'[]'),
    'links',coalesce((select jsonb_agg(to_jsonb(t) order by variant_id,compatibility_id) from public.variant_compatibilities t where variant_id in(select id from v)),'[]'),
    'compatibilities',coalesce((select jsonb_agg(to_jsonb(t) order by id) from c t),'[]'),
    'brands',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.brands t where id in(select brand_id from c)),'[]'),
    'models',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.vehicle_models t where id in(select vehicle_model_id from c) or id in(select vehicle_model_id from g)),'[]'),
    'generations',coalesce((select jsonb_agg(to_jsonb(t) order by id) from g t),'[]')) into result;
  return result;
end $$;

create table public.commerce_quotes (
  id uuid primary key default gen_random_uuid(),
  cart_id uuid references public.carts(id) on delete set null,
  owner_user_id uuid,
  owner_guest_session text,
  country text not null check(country ~ '^[A-Z]{2}$'),
  mode text not null check(length(trim(mode)) between 1 and 100),
  destination jsonb not null check(jsonb_typeof(destination)='object'),
  source_context jsonb not null check(jsonb_typeof(source_context)='object'),
  payload jsonb not null check(jsonb_typeof(payload)='object'),
  currency text not null default 'EUR' check(currency='EUR'),
  subtotal_cents integer not null check(subtotal_cents>=0),
  shipping_cents integer not null check(shipping_cents>=0),
  tax_cents integer not null check(tax_cents>=0),
  total_cents integer not null check(total_cents>=0),
  expires_at timestamptz not null,
  request_key uuid not null,
  state text not null default 'ready' check(state in('ready','superseded','consumed')),
  created_at timestamptz not null default clock_timestamp(),
  check((owner_user_id is not null)<>(owner_guest_session is not null)),
  check(owner_guest_session is null or length(owner_guest_session) between 16 and 128),
  check(total_cents::bigint=subtotal_cents::bigint+shipping_cents::bigint),
  check(tax_cents<=total_cents),
  check(expires_at>created_at and expires_at<=created_at+interval '45 minutes'),
  unique(cart_id,request_key)
);
create index commerce_quotes_cart_state_idx on public.commerce_quotes(cart_id,state);

alter table public.orders add column commerce_quote_id uuid unique references public.commerce_quotes(id) on delete restrict;
alter table public.order_items add column variant_id uuid references public.product_variants(id) on delete restrict;
alter table public.order_items add column variant_name text;
alter table public.order_items add column variant_attributes jsonb;
alter table public.order_items add column source_cart_item_id uuid;
create index order_items_variant_idx on public.order_items(variant_id);

create table public.commerce_order_lines (
  id uuid primary key default gen_random_uuid(),
  quote_id uuid not null references public.commerce_quotes(id) on delete restrict,
  order_id uuid not null references public.orders(id) on delete restrict,
  order_item_id uuid not null unique references public.order_items(id) on delete restrict,
  source_cart_item_id uuid not null,
  group_key text not null,
  line_snapshot jsonb not null check(jsonb_typeof(line_snapshot)='object'),
  group_snapshot jsonb not null check(jsonb_typeof(group_snapshot)='object'),
  offer_snapshot jsonb not null check(jsonb_typeof(offer_snapshot)='object'),
  rate_snapshot jsonb not null check(jsonb_typeof(rate_snapshot)='object'),
  agent_snapshot jsonb not null check(jsonb_typeof(agent_snapshot)='object'),
  supplier_snapshot jsonb not null check(jsonb_typeof(supplier_snapshot)='object'),
  created_at timestamptz not null default clock_timestamp(),
  unique(quote_id,source_cart_item_id)
);
create index commerce_order_lines_order_idx on public.commerce_order_lines(order_id);

create function private.guard_commerce_history() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if tg_op in('DELETE','TRUNCATE') then raise exception 'Commerce history is immutable'; end if;
  if tg_table_name='commerce_order_lines' then raise exception 'Commerce history is immutable'; end if;
  if tg_op='INSERT' then
    if new.state<>'ready' or new.cart_id is null
      or new.source_context->'cart'->>'id' is distinct from new.cart_id::text
      or new.source_context->'cart'->>'user_id' is distinct from new.owner_user_id::text
      or new.source_context->'cart'->>'guest_session_id' is distinct from new.owner_guest_session
      or new.payload->>'currency' is distinct from new.currency
      or new.source_context->>'country' is distinct from new.country
      or new.source_context->>'mode' is distinct from new.mode
      or new.destination->>'country' is distinct from new.country
      or new.destination->>'postal_code' is distinct from new.source_context->>'postal_code' then
      raise exception 'Quote insertion identity or initial state is invalid';
    end if;
    return new;
  end if;
  if (to_jsonb(new)-array['cart_id','state']) is distinct from (to_jsonb(old)-array['cart_id','state']) then
    raise exception 'Quote snapshot is immutable';
  end if;
  if new.cart_id is distinct from old.cart_id and not
    (old.cart_id is not null and new.cart_id is null and not exists(select 1 from public.carts where id=old.cart_id)) then
    raise exception 'Quote cart identity is immutable except deleted-cart detachment';
  end if;
  if new.state is distinct from old.state then
    if old.state<>'ready' then raise exception 'Invalid quote state transition'; end if;
    if new.state='consumed' then
      if not exists(select 1 from public.orders where commerce_quote_id=old.id and is_test and status='pending') then
        raise exception 'A pending test order is required before consuming quote';
      end if;
    elsif new.state='superseded' then
      if not exists(select 1 from public.commerce_quotes where id<>old.id and cart_id=old.cart_id and state='ready' and created_at>=old.created_at) then
        raise exception 'A newer ready quote is required before superseding quote';
      end if;
    else raise exception 'Invalid quote state transition'; end if;
  end if;
  return new;
end $$;
create trigger commerce_quotes_history before insert or update or delete on public.commerce_quotes for each row execute function private.guard_commerce_history();
create trigger commerce_quotes_no_truncate before truncate on public.commerce_quotes for each statement execute function private.guard_commerce_history();
create trigger commerce_order_lines_history before update or delete on public.commerce_order_lines for each row execute function private.guard_commerce_history();
create trigger commerce_order_lines_no_truncate before truncate on public.commerce_order_lines for each statement execute function private.guard_commerce_history();

-- Payload validation and the two write RPCs are below. No source table is
-- locked across a network call: calculation happens before the short save RPC.

create function private.commerce_context_row(p_source jsonb,p_key text,p_id uuid) returns jsonb
language plpgsql immutable security invoker set search_path='' as $$
declare r jsonb; n integer;
begin
  select count(*),jsonb_agg(value)->0 into n,r from jsonb_array_elements(p_source->p_key) where value->>'id'=p_id::text;
  if n<>1 then raise exception 'Invalid commerce source association'; end if;
  return r;
end $$;

create function private.commerce_quote_money(p_data jsonb,p_key text) returns bigint
language plpgsql immutable security invoker set search_path='' as $$
declare value bigint;
begin
  if jsonb_typeof(p_data->p_key) is distinct from 'number' or (p_data->>p_key) !~ '^[0-9]+$' then raise exception 'Invalid quote monetary amount'; end if;
  value:=(p_data->>p_key)::bigint;
  if value>2000000000 then raise exception 'Quote monetary amount exceeds supported limit'; end if;
  return value;
end $$;

create function private.check_commerce_quote_payload(p_source jsonb,p_payload jsonb,p_min_valid_until timestamptz)
returns timestamptz language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare
  g jsonb; l jsonb; ci public.cart_items; p public.products; v public.product_variants;
  o public.supplier_offers; r public.shipping_rates; a public.commerce_agents;
  ids uuid[]:='{}'; variants uuid[]:='{}'; q integer; line_count integer:=0; group_goods bigint;
  subtotal bigint:=0; shipping bigint:=0; taxes bigint:=0; specificity integer; matches integer;
  fx numeric; gross numeric; acquisition numeric; ship_net bigint; extras bigint; landed numeric; revenue numeric; customer_total bigint;
  expected jsonb; valid timestamptz; earliest timestamptz; reported timestamptz;
begin
  if jsonb_typeof(p_source) is distinct from 'object' or jsonb_typeof(p_payload) is distinct from 'object'
    or p_payload->>'currency' is distinct from 'EUR' or p_source->'cart'->>'currency' is distinct from 'EUR'
    or jsonb_typeof(p_payload->'groups') is distinct from 'array' then raise exception 'Invalid quote payload or currency'; end if;
  if jsonb_array_length(p_payload->'groups') not between 1 and 100 then raise exception 'Invalid quote group count'; end if;
  for g in select value from jsonb_array_elements(p_payload->'groups') loop
    if jsonb_typeof(g) is distinct from 'object' or jsonb_typeof(g->'lines') is distinct from 'array'
      or jsonb_array_length(g->'lines') not between 1 and 100 then raise exception 'Invalid quote group lines'; end if;
    v:=jsonb_populate_record(null::public.product_variants,private.commerce_context_row(p_source,'variants',(g->>'variant_id')::uuid));
    p:=jsonb_populate_record(null::public.products,private.commerce_context_row(p_source,'products',v.product_id));
    o:=jsonb_populate_record(null::public.supplier_offers,private.commerce_context_row(p_source,'offers',(g->>'offer_id')::uuid));
    r:=jsonb_populate_record(null::public.shipping_rates,private.commerce_context_row(p_source,'rates',(g->>'shipping_rate_id')::uuid));
    a:=jsonb_populate_record(null::public.commerce_agents,private.commerce_context_row(p_source,'agents',(g->>'responsible_agent_id')::uuid));
    perform private.commerce_context_row(p_source,'suppliers',(g->>'supplier_id')::uuid);
    if v.id=any(variants) then raise exception 'Duplicate quote variant group'; end if;
    variants:=array_append(variants,v.id);
    if p.status<>'active' or not p.is_verified or p.currency<>'EUR' or v.currency<>'EUR' or v.status<>'active' or not v.is_verified or v.evidence_ref is null
      or o.variant_id<>v.id or o.supplier_id::text is distinct from g->>'supplier_id' or o.responsible_agent_id is distinct from a.id
      or r.offer_id<>o.id or r.country is distinct from p_source->>'country' or r.mode is distinct from p_source->>'mode'
      or not a.is_active or a.role not in('orders','supervisor') then raise exception 'Quote source identity or verification mismatch'; end if;
    if o.verification_state<>'verified' or o.evidence_ref is null or o.availability<>'available'
      or o.valid_until is null or r.verification_state<>'verified' or r.evidence_ref is null or r.valid_until is null
      or o.unit_cost_cents is null or o.recoverable_tax_cents is null or o.available_quantity is null
      or o.preparation_days_min is null or o.preparation_days_max is null or r.delivery_days_min is null or r.delivery_days_max is null
      or r.shipping_cost_cents is null or r.shipping_recoverable_tax_cents is null or r.customer_shipping_cents is null
      or r.agent_fee_cents is null or r.import_duty_cents is null or r.nonrecoverable_tax_cents is null or r.other_cost_cents is null
      or r.goods_tax_bps is null or r.shipping_tax_bps is null then raise exception 'Quote source terms are incomplete'; end if;
    if v.requires_vehicle then
      -- Never acquire row locks under the source-table SHARE locks: the stable
      -- captured rows already provide integrity without a table/row lock cycle.
      if not exists(select 1 from jsonb_array_elements(p_source->'links') x where x.value->>'variant_id'=v.id::text)
        or exists(select 1 from jsonb_array_elements(p_source->'links') x where x.value->>'variant_id'=v.id::text
          and not exists(select 1 from jsonb_array_elements(p_source->'compatibilities') c
            where c.value->>'id'=x.value->>'compatibility_id' and c.value->>'product_id'=v.product_id::text
              and c.value->>'verification_state'='verified')) then
        raise exception 'Quote variant compatibility source is not verified';
      end if;
    end if;
    q:=0; group_goods:=0;
    for l in select value from jsonb_array_elements(g->'lines') loop
      ci:=jsonb_populate_record(null::public.cart_items,private.commerce_context_row(p_source,'cart_items',(l->>'cart_item_id')::uuid));
      if ci.id=any(ids) then raise exception 'Duplicate quote cart line'; end if;
      ids:=array_append(ids,ci.id);line_count:=line_count+1;
      if ci.cart_id::text is distinct from p_source->'cart'->>'id' or ci.product_id<>p.id or ci.variant_id is distinct from v.id
        or l->>'product_id' is distinct from p.id::text or l->>'variant_id' is distinct from v.id::text
        or l->'quantity' is distinct from to_jsonb(ci.quantity) or l->'unit_amount_cents' is distinct from to_jsonb(v.price_cents)
        or l->>'sku' is distinct from v.sku or l->>'product_name' is distinct from p.name or l->>'product_slug' is distinct from p.slug
        or l->>'variant_name' is distinct from v.name or l->'variant_attributes' is distinct from v.attributes
        or private.cart_vehicle_identity(l->'selected_vehicle') is distinct from private.cart_vehicle_identity(ci.selected_vehicle) then
        raise exception 'Quote line does not match persisted cart and variant';
      end if;
      if jsonb_typeof(l->'compatibility_result') is distinct from 'object'
        or l->'compatibility_result'->>'status' is distinct from (case when v.requires_vehicle then 'compatible' else 'not_required' end) then
        raise exception 'Quote line fitment result is not confirmed';
      end if;
      if l->>'image_url' is not null and not exists(select 1 from jsonb_array_elements(p_source->'product_images') i
        where i.value->>'product_id'=p.id::text and i.value->>'url'=l->>'image_url') then raise exception 'Quote image is not in source product'; end if;
      q:=q+ci.quantity;group_goods:=group_goods+v.price_cents::bigint*ci.quantity;
    end loop;
    if g->'line_ids' is distinct from (select jsonb_agg(value->'cart_item_id') from jsonb_array_elements(g->'lines')) then raise exception 'Quote group line IDs mismatch'; end if;
    if q<o.moq or q>v.stock or q>o.available_quantity then raise exception 'Quote aggregate quantity unavailable'; end if;
    -- Select region by complete set of eligible rates, never by the supplied ID.
    select max(length(upper(regexp_replace(value->>'postal_prefix','[ -]','','g')))) into specificity
      from jsonb_array_elements(p_source->'rates') where value->>'offer_id'=o.id::text
      and (value->>'min_quantity')::integer<=q and (value->>'max_quantity')::integer>=q
      and left(upper(regexp_replace(p_source->>'postal_code','[ -]','','g')),length(upper(regexp_replace(value->>'postal_prefix','[ -]','','g'))))=upper(regexp_replace(value->>'postal_prefix','[ -]','','g'));
    select count(*) into matches from jsonb_array_elements(p_source->'rates') where value->>'offer_id'=o.id::text
      and (value->>'min_quantity')::integer<=q and (value->>'max_quantity')::integer>=q
      and length(upper(regexp_replace(value->>'postal_prefix','[ -]','','g')))=specificity
      and left(upper(regexp_replace(p_source->>'postal_code','[ -]','','g')),specificity)=upper(regexp_replace(value->>'postal_prefix','[ -]','','g'));
    if matches<>1 or length(upper(regexp_replace(r.postal_prefix,'[ -]','','g'))) is distinct from specificity
      or r.min_quantity>q or r.max_quantity<q
      or left(upper(regexp_replace(p_source->>'postal_code','[ -]','','g')),specificity)<>upper(regexp_replace(r.postal_prefix,'[ -]','','g')) then
      raise exception 'Quote shipping rule is missing, ambiguous or not most specific';
    end if;
    if (select count(*) from jsonb_array_elements(p_payload->'groups') x where x.value->>'supplier_id'=o.supplier_id::text)>1
      and r.multi_variant_policy<>'independent_parcels' then raise exception 'Multi-variant shipping consolidation is unconfirmed'; end if;
    fx:=1;valid:=least(o.valid_until,r.valid_until);
    if o.currency<>'EUR' then
      if o.fx_rate is null or o.fx_evidence_ref is null or o.fx_valid_until is null then raise exception 'Quote exchange terms are incomplete'; end if;
      fx:=o.fx_rate;valid:=least(valid,o.fx_valid_until);
    elsif o.fx_rate is not null and o.fx_rate<>1 then raise exception 'Invalid same-currency exchange rate'; end if;
    if valid<p_min_valid_until then raise exception 'Quote source conditions expire too soon'; end if;
    gross:=round(o.unit_cost_cents::numeric*q*fx);
    acquisition:=round((o.unit_cost_cents-o.recoverable_tax_cents)::numeric*q*fx);
    ship_net:=r.shipping_cost_cents-r.shipping_recoverable_tax_cents;
    extras:=r.agent_fee_cents::bigint+r.import_duty_cents+r.nonrecoverable_tax_cents+r.other_cost_cents;
    landed:=acquisition+ship_net+extras;
    customer_total:=group_goods+r.customer_shipping_cents;
    revenue:=round(group_goods::numeric*10000/(10000+r.goods_tax_bps))+round(r.customer_shipping_cents::numeric*10000/(10000+r.shipping_tax_bps));
    if revenue<landed then raise exception 'Quote contribution margin is negative'; end if;
    expected:=jsonb_build_object('status','ready','variant_id',v.id,'offer_id',o.id,'shipping_rate_id',r.id,'responsible_agent_id',a.id,
      'supplier_id',o.supplier_id,'supplier_sku',o.supplier_sku,'supplier_variant',o.supplier_variant,'quantity',q,'currency','EUR',
      'supplier_gross_cents',gross,'acquisition_net_cents',acquisition,'shipping_net_cents',ship_net,'additional_costs_cents',extras,
      'landed_cost_cents',landed,'customer_shipping_cents',r.customer_shipping_cents,'unit_price_cents',v.price_cents,
      'customer_total_cents',customer_total,'revenue_net_cents',revenue,'sales_tax_cents',customer_total-revenue,'contribution_margin_cents',revenue-landed,
      'delivery_days_min',o.preparation_days_min+r.delivery_days_min,'delivery_days_max',o.preparation_days_max+r.delivery_days_max,
      'margin_basis','before_payment_fees_and_operating_expenses_not_net_profit');
    if jsonb_typeof(g->'evaluation') is distinct from 'object' or not ((g->'evaluation') @> expected)
      or g->'evaluation'->'reasons' is distinct from '[]'::jsonb
      or (g->'evaluation'->>'valid_until')::timestamptz is distinct from valid then raise exception 'Quote evaluation amounts or identities mismatch'; end if;
    perform private.commerce_quote_money(g->'evaluation',key) from jsonb_object_keys(g->'evaluation') key where key ~ '_cents$';
    subtotal:=subtotal+group_goods;shipping:=shipping+r.customer_shipping_cents;taxes:=taxes+(customer_total-revenue)::bigint;
    earliest:=case when earliest is null then valid else least(earliest,valid) end;
  end loop;
  if line_count<>jsonb_array_length(p_source->'cart_items') then raise exception 'Quote does not cover every cart line'; end if;
  if private.commerce_quote_money(p_payload,'subtotal_cents')<>subtotal or private.commerce_quote_money(p_payload,'shipping_cents')<>shipping
    or private.commerce_quote_money(p_payload,'tax_cents')<>taxes or private.commerce_quote_money(p_payload,'total_cents')<>subtotal+shipping then
    raise exception 'Quote total mismatch';
  end if;
  if coalesce(p_payload->>'valid_until','') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then raise exception 'Quote expiry must include timezone'; end if;
  reported:=(p_payload->>'valid_until')::timestamptz;
  if reported is distinct from earliest then raise exception 'Quote expiry does not match source conditions'; end if;
  return earliest;
end $$;

create function private.lock_commerce_quote_sources() returns void
language plpgsql security invoker set search_path='' as $$
begin
  -- Conservative, short global source barrier. EXCLUSIVE blocks ROW SHARE as
  -- well as writes (including FK row-lock acquisition); plain SELECT remains
  -- possible. NOWAIT prevents waiting behind an admin holding a row lock and
  -- subsequently trying a table-lock upgrade. No network work occurs here.
  lock table public.cart_items,public.profiles,public.products,public.product_images,public.product_variants,
    public.supplier_offers,public.shipping_rates,public.commerce_agents,public.suppliers,
    public.variant_compatibilities,public.product_compatibilities,public.brands,
    public.vehicle_models,public.vehicle_generations in exclusive mode nowait;
exception when lock_not_available then
  raise exception 'Commerce source busy; request a fresh quote';
end $$;

create function public.commerce_save_quote(p_cart_id uuid,p_user_id uuid,p_guest_session text,p_request_key uuid,
  p_destination jsonb,p_mode text,p_source jsonb,p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare previous public.commerce_quotes; actual jsonb; result public.commerce_quotes; valid timestamptz; captured_at timestamptz;
begin
  perform 1 from public.carts where id=p_cart_id for update;
  perform private.assert_cart_owner(p_cart_id,p_user_id,p_guest_session);
  if p_request_key is null or jsonb_typeof(p_destination) is distinct from 'object' then raise exception 'Invalid quote request identity'; end if;
  select * into previous from public.commerce_quotes where cart_id=p_cart_id and request_key=p_request_key for update;
  if found then
    if previous.owner_user_id is distinct from p_user_id or previous.owner_guest_session is distinct from p_guest_session
      or previous.destination is distinct from p_destination or previous.mode is distinct from p_mode
      or previous.source_context is distinct from p_source or previous.payload is distinct from p_payload then raise exception 'Quote request key content mismatch'; end if;
    return to_jsonb(previous);
  end if;
  perform private.lock_commerce_quote_sources();
  actual:=public.commerce_cart_context(p_cart_id,p_user_id,p_guest_session,p_destination->>'country',p_destination->>'postal_code',p_mode);
  if actual is distinct from p_source then raise exception 'Commerce source changed; request a fresh quote'; end if;
  captured_at:=clock_timestamp();
  valid:=private.check_commerce_quote_payload(actual,p_payload,captured_at+interval '35 minutes');
  insert into public.commerce_quotes(cart_id,owner_user_id,owner_guest_session,country,mode,destination,source_context,payload,
    subtotal_cents,shipping_cents,tax_cents,total_cents,expires_at,request_key,created_at)
  values(p_cart_id,p_user_id,p_guest_session,p_destination->>'country',p_mode,p_destination,actual,p_payload,
    private.commerce_quote_money(p_payload,'subtotal_cents'),private.commerce_quote_money(p_payload,'shipping_cents'),
    private.commerce_quote_money(p_payload,'tax_cents'),private.commerce_quote_money(p_payload,'total_cents'),
    least(valid,captured_at+interval '45 minutes'),p_request_key,captured_at) returning * into result;
  update public.commerce_quotes set state='superseded' where cart_id=p_cart_id and state='ready' and id<>result.id;
  insert into public.admin_audit(action,resource,metadata) values('commerce.quote.created',result.id::text,
    jsonb_build_object('cart_id',p_cart_id,'request_key',p_request_key));
  return to_jsonb(result);
end $$;

create function private.guard_quoted_order_identity() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if tg_table_name='orders' then
    if new.commerce_quote_id is distinct from old.commerce_quote_id then
      raise exception 'Quoted order identity is immutable';
    end if;
    if old.commerce_quote_id is not null and
      row(new.subtotal_cents,new.shipping_amount_cents,new.tax_amount_cents,new.total_cents,new.currency,new.is_test)
      is distinct from row(old.subtotal_cents,old.shipping_amount_cents,old.tax_amount_cents,old.total_cents,old.currency,old.is_test) then
      raise exception 'Quoted order financial snapshot and test mode are immutable';
    end if;
    return new;
  end if;
  if exists(select 1 from public.commerce_order_lines where order_item_id=old.id) then raise exception 'Quoted order line is immutable'; end if;
  if tg_op='DELETE' then return old; end if;
  return new;
end $$;
create trigger quoted_order_identity before update on public.orders
  for each row execute function private.guard_quoted_order_identity();
create trigger quoted_order_line_history before update or delete on public.order_items
  for each row execute function private.guard_quoted_order_identity();

create function public.commerce_order_from_quote(p_actor uuid,p_quote_id uuid,p_user_id uuid,p_guest_session text,p_is_test boolean)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare q public.commerce_quotes; o public.orders; current_source jsonb; g jsonb; l jsonb; item_id uuid;
begin
  perform private.assert_admin(p_actor);
  if p_is_test is distinct from true then raise exception 'Only pending test orders are supported; live checkout is disabled'; end if;
  -- Cart then quote lock: the same ordering as quote saving, never the reverse.
  select * into q from public.commerce_quotes where id=p_quote_id;
  if not found or q.cart_id is null then raise exception 'Quote cart is missing'; end if;
  perform 1 from public.carts where id=q.cart_id for update;
  perform private.assert_cart_owner(q.cart_id,p_user_id,p_guest_session);
  select * into strict q from public.commerce_quotes where id=p_quote_id for update;
  if q.cart_id is null or q.owner_user_id is distinct from p_user_id or q.owner_guest_session is distinct from p_guest_session then raise exception 'Quote owner mismatch'; end if;
  select * into o from public.orders where commerce_quote_id=q.id;
  if found then
    if not o.is_test then raise exception 'Existing quote order is not a test order'; end if;
    return jsonb_build_object('order_id',o.id,'order_number',o.order_number,'quote_id',q.id,'is_test',true,'reused',true);
  end if;
  if q.state<>'ready' or q.expires_at<=clock_timestamp() then raise exception 'Quote is expired, superseded or consumed'; end if;
  perform private.lock_commerce_quote_sources();
  current_source:=public.commerce_cart_context(q.cart_id,p_user_id,p_guest_session,q.country,q.destination->>'postal_code',q.mode);
  perform private.assert_admin(p_actor);
  if current_source is distinct from q.source_context then raise exception 'Commerce source changed; request a fresh quote'; end if;
  perform private.check_commerce_quote_payload(current_source,q.payload,clock_timestamp());
  insert into public.orders(order_number,user_id,cart_id,guest_session_id,status,payment_status,fulfillment_status,
    shipping_address,subtotal_cents,shipping_amount_cents,tax_amount_cents,total_cents,currency,requires_compatibility_review,is_test,commerce_quote_id)
  values('TY-'||to_char(clock_timestamp(),'YYYYMMDD')||'-'||upper(substr(replace(gen_random_uuid()::text,'-',''),1,8)),p_user_id,q.cart_id,p_guest_session,
    'pending','unpaid','requires_review',q.destination,q.subtotal_cents,q.shipping_cents,q.tax_cents,q.total_cents,'EUR',true,true,q.id)
    returning * into o;
  for g in select value from jsonb_array_elements(q.payload->'groups') loop
    for l in select value from jsonb_array_elements(g->'lines') loop
      insert into public.order_items(order_id,product_id,product_name,product_slug,sku,quantity,unit_amount_cents,currency,image_url,
        selected_vehicle,compatibility_result,variant_id,variant_name,variant_attributes,source_cart_item_id)
      values(o.id,(l->>'product_id')::uuid,l->>'product_name',l->>'product_slug',l->>'sku',(l->>'quantity')::integer,(l->>'unit_amount_cents')::integer,
        'EUR',l->>'image_url',l->'selected_vehicle',l->'compatibility_result',(l->>'variant_id')::uuid,l->>'variant_name',l->'variant_attributes',(l->>'cart_item_id')::uuid)
        returning id into item_id;
      insert into public.commerce_order_lines(quote_id,order_id,order_item_id,source_cart_item_id,group_key,line_snapshot,group_snapshot,
        offer_snapshot,rate_snapshot,agent_snapshot,supplier_snapshot)
      values(q.id,o.id,item_id,(l->>'cart_item_id')::uuid,g->>'variant_id',l,g,
        private.commerce_context_row(q.source_context,'offers',(g->>'offer_id')::uuid),
        private.commerce_context_row(q.source_context,'rates',(g->>'shipping_rate_id')::uuid),
        private.commerce_context_row(q.source_context,'agents',(g->>'responsible_agent_id')::uuid),
        private.commerce_context_row(q.source_context,'suppliers',(g->>'supplier_id')::uuid));
    end loop;
  end loop;
  update public.commerce_quotes set state='consumed' where id=q.id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
    values(p_actor,'commerce.quote.prepare_test_order',o.id::text,jsonb_build_object('quote_id',q.id,'is_test',true));
  return jsonb_build_object('order_id',o.id,'order_number',o.order_number,'quote_id',q.id,'is_test',true,'reused',false);
end $$;

alter table public.commerce_quotes enable row level security;
alter table public.commerce_order_lines enable row level security;
revoke all on public.commerce_quotes,public.commerce_order_lines from public,anon,authenticated,service_role;
grant select,insert,update on public.commerce_quotes to service_role;
grant select,insert on public.commerce_order_lines to service_role;
revoke all on function public.commerce_cart_context(uuid,uuid,text,text,text,text),
  private.guard_commerce_history(),private.guard_quoted_order_identity(),private.commerce_context_row(jsonb,text,uuid),private.commerce_quote_money(jsonb,text),
  private.check_commerce_quote_payload(jsonb,jsonb,timestamptz),private.lock_commerce_quote_sources(),
  public.commerce_save_quote(uuid,uuid,text,uuid,jsonb,text,jsonb,jsonb),public.commerce_order_from_quote(uuid,uuid,uuid,text,boolean)
  from public,anon,authenticated;
grant execute on function public.commerce_cart_context(uuid,uuid,text,text,text,text),
  private.guard_commerce_history(),private.guard_quoted_order_identity(),private.commerce_context_row(jsonb,text,uuid),private.commerce_quote_money(jsonb,text),
  private.check_commerce_quote_payload(jsonb,jsonb,timestamptz),private.lock_commerce_quote_sources(),
  public.commerce_save_quote(uuid,uuid,text,uuid,jsonb,text,jsonb,jsonb),public.commerce_order_from_quote(uuid,uuid,uuid,text,boolean)
  to service_role;
commit;
