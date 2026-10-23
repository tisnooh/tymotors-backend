-- Private commerce foundations only. No catalogue, price, inventory or order backfill.
begin;

create table public.commerce_agents (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references public.profiles(id) on delete restrict,
  name text not null check (length(trim(name)) between 2 and 160),
  role text not null check (role in ('sourcing','catalogue','pricing','orders','supervisor')),
  is_active boolean not null default false,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp()
);
create index commerce_agents_profile_idx on public.commerce_agents(profile_id);

create table public.product_variants (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete restrict,
  sku text not null check (length(trim(sku)) between 1 and 100),
  name text not null check (length(trim(name)) between 1 and 160),
  attributes jsonb not null default '{}' check (jsonb_typeof(attributes)='object'),
  currency text not null default 'EUR' check (currency='EUR'),
  price_cents integer not null check (price_cents between 0 and 2000000000),
  stock integer not null default 0 check (stock between 0 and 100000),
  status text not null default 'draft' check (status in ('draft','active','archived')),
  is_verified boolean not null default false,
  requires_vehicle boolean not null default true,
  sale_tax_bps integer check (sale_tax_bps between 0 and 10000),
  evidence_ref text check (evidence_ref is null or length(trim(evidence_ref)) between 1 and 1000),
  is_default boolean not null default false,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(product_id,sku),
  check (status<>'active' or (is_verified and evidence_ref is not null))
);
create unique index product_variants_one_active_default on public.product_variants(product_id)
  where is_default and status='active';

create table public.supplier_offers (
  id uuid primary key default gen_random_uuid(),
  variant_id uuid not null references public.product_variants(id) on delete restrict,
  supplier_id uuid not null references public.suppliers(id) on delete restrict,
  supplier_sku text not null check (length(trim(supplier_sku)) between 1 and 200),
  supplier_variant text not null check (length(trim(supplier_variant)) between 1 and 500),
  url text not null check (length(url)<=2000 and url ~ '^https://[^/[:space:]@?#]+([/?#][^[:space:]]*)?$'),
  verification_state text not null default 'pending' check (verification_state in ('pending','verified','rejected')),
  evidence_ref text check (evidence_ref is null or length(trim(evidence_ref)) between 1 and 1000),
  is_primary boolean not null default false,
  availability text not null default 'unknown' check (availability in ('unknown','available','unavailable')),
  available_quantity integer check (available_quantity between 0 and 1000000),
  valid_until timestamptz,
  unit_cost_cents integer check (unit_cost_cents between 0 and 2000000000),
  recoverable_tax_cents integer check (recoverable_tax_cents between 0 and 2000000000),
  currency text not null default 'EUR' check (currency in ('EUR','USD','GBP','CNY')),
  fx_rate numeric(20,10) check (fx_rate>0 and fx_rate<=1000000),
  fx_evidence_ref text check (fx_evidence_ref is null or length(trim(fx_evidence_ref)) between 1 and 1000),
  fx_valid_until timestamptz,
  moq integer not null default 1 check (moq between 1 and 1000000),
  preparation_days_min integer check (preparation_days_min between 0 and 730),
  preparation_days_max integer check (preparation_days_max between 0 and 730),
  responsible_agent_id uuid references public.commerce_agents(id) on delete restrict,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  check (recoverable_tax_cents is null or (unit_cost_cents is not null and recoverable_tax_cents<=unit_cost_cents)),
  check (preparation_days_min is null or preparation_days_max is null or preparation_days_max>=preparation_days_min),
  check (verification_state<>'verified' or evidence_ref is not null)
);
create unique index supplier_offers_one_primary on public.supplier_offers(variant_id) where is_primary;
create index supplier_offers_variant_idx on public.supplier_offers(variant_id);
create index supplier_offers_supplier_idx on public.supplier_offers(supplier_id);
create index supplier_offers_agent_idx on public.supplier_offers(responsible_agent_id);

create table public.shipping_rates (
  id uuid primary key default gen_random_uuid(),
  offer_id uuid not null references public.supplier_offers(id) on delete restrict,
  country text not null check (country ~ '^[A-Z]{2}$'),
  postal_prefix text not null default '' check (length(postal_prefix)<=20 and postal_prefix ~ '^[A-Za-z0-9 -]*$'),
  mode text not null check (length(trim(mode)) between 1 and 100),
  min_quantity integer not null default 1 check (min_quantity between 1 and 1000000),
  max_quantity integer not null check (max_quantity between min_quantity and 1000000),
  currency text not null default 'EUR' check (currency='EUR'),
  shipping_cost_cents integer check (shipping_cost_cents between 0 and 2000000000),
  shipping_recoverable_tax_cents integer check (shipping_recoverable_tax_cents between 0 and 2000000000),
  customer_shipping_cents integer check (customer_shipping_cents between 0 and 2000000000),
  goods_tax_bps integer check (goods_tax_bps between 0 and 10000),
  shipping_tax_bps integer check (shipping_tax_bps between 0 and 10000),
  agent_fee_cents integer check (agent_fee_cents between 0 and 2000000000),
  import_duty_cents integer check (import_duty_cents between 0 and 2000000000),
  nonrecoverable_tax_cents integer check (nonrecoverable_tax_cents between 0 and 2000000000),
  other_cost_cents integer check (other_cost_cents between 0 and 2000000000),
  verification_state text not null default 'pending' check (verification_state in ('pending','verified','rejected')),
  evidence_ref text check (evidence_ref is null or length(trim(evidence_ref)) between 1 and 1000),
  valid_until timestamptz,
  delivery_days_min integer check (delivery_days_min between 0 and 730),
  delivery_days_max integer check (delivery_days_max between 0 and 730),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  check (shipping_recoverable_tax_cents is null or (shipping_cost_cents is not null and shipping_recoverable_tax_cents<=shipping_cost_cents)),
  check (delivery_days_min is null or delivery_days_max is null or delivery_days_max>=delivery_days_min),
  check (verification_state<>'verified' or evidence_ref is not null)
);
create index shipping_rates_offer_country_idx on public.shipping_rates(offer_id,country);

create table public.variant_compatibilities (
  variant_id uuid not null references public.product_variants(id) on delete restrict,
  compatibility_id uuid not null references public.product_compatibilities(id) on delete restrict,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key(variant_id,compatibility_id)
);
create index variant_compatibilities_rule_idx on public.variant_compatibilities(compatibility_id);

-- A relation is not a new compatibility claim: reuse the existing rule verbatim.
create function private.check_commerce_variant(p_id uuid) returns void
language plpgsql security invoker set search_path='' as $$
declare v public.product_variants;
begin
  select * into v from public.product_variants where id=p_id;
  if not found then return; end if;
  -- Lock the source rules against concurrent mutation until this transaction ends.
  perform 1 from public.product_compatibilities c join public.variant_compatibilities vc
    on vc.compatibility_id=c.id where vc.variant_id=p_id order by c.id for share of c;
  if exists(select 1 from public.variant_compatibilities vc join public.product_compatibilities c on c.id=vc.compatibility_id
    where vc.variant_id=p_id and c.product_id<>v.product_id) then
    raise exception 'Compatibility must belong to the same product';
  end if;
  if v.status='active' and v.requires_vehicle and (
    not exists(select 1 from public.variant_compatibilities where variant_id=p_id)
    or exists(select 1 from public.variant_compatibilities vc join public.product_compatibilities c on c.id=vc.compatibility_id
      where vc.variant_id=p_id and c.verification_state<>'verified')
  ) then raise exception 'Active vehicle variant requires verified compatibility rules'; end if;
end $$;

create function private.guard_commerce_record() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  case tg_table_name
    when 'product_variants' then
      if new.product_id is distinct from old.product_id then raise exception 'Variant product_id is immutable'; end if;
    when 'supplier_offers' then
      if new.variant_id is distinct from old.variant_id or new.supplier_id is distinct from old.supplier_id then raise exception 'Offer variant_id and supplier_id are immutable'; end if;
    when 'shipping_rates' then
      if new.offer_id is distinct from old.offer_id then raise exception 'Shipping offer_id is immutable'; end if;
    else null;
  end case;
  new.created_at:=old.created_at;
  new.updated_at:=clock_timestamp();
  return new;
end $$;

create function private.guard_variant_compatibility() returns trigger
language plpgsql security invoker set search_path='' as $$
declare p uuid; c uuid;
begin
  select product_id into p from public.product_variants where id=new.variant_id;
  select product_id into c from public.product_compatibilities where id=new.compatibility_id;
  if p is distinct from c then raise exception 'Compatibility must belong to the same product'; end if;
  if tg_op='UPDATE' then
    if new.variant_id<>old.variant_id or new.compatibility_id<>old.compatibility_id then raise exception 'Compatibility association keys are immutable'; end if;
    new.created_at:=old.created_at;
    new.updated_at:=clock_timestamp();
  end if;
  return new;
end $$;

create function private.recheck_commerce_variant() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if tg_table_name='product_variants' then
    perform private.check_commerce_variant(new.id);
  else
    if tg_op<>'INSERT' then perform private.check_commerce_variant(old.variant_id); end if;
    if tg_op<>'DELETE' then perform private.check_commerce_variant(new.variant_id); end if;
  end if;
  return null;
end $$;

create function private.guard_commerce_source_rule() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if exists(select 1 from public.variant_compatibilities vc join public.product_variants v on v.id=vc.variant_id
    where vc.compatibility_id=old.id and (new.product_id<>v.product_id or
      (v.status='active' and v.requires_vehicle and new.verification_state<>'verified'))) then
    raise exception 'Linked commerce compatibility would become invalid';
  end if;
  return new;
end $$;

create trigger commerce_agents_guard before update on public.commerce_agents
  for each row execute function private.guard_commerce_record();
create trigger product_variants_guard before update on public.product_variants
  for each row execute function private.guard_commerce_record();
create trigger supplier_offers_guard before update on public.supplier_offers
  for each row execute function private.guard_commerce_record();
create trigger shipping_rates_guard before update on public.shipping_rates
  for each row execute function private.guard_commerce_record();
create trigger variant_compatibilities_guard before insert or update on public.variant_compatibilities
  for each row execute function private.guard_variant_compatibility();
create trigger commerce_source_rule_guard before update of product_id,verification_state on public.product_compatibilities
  for each row execute function private.guard_commerce_source_rule();
create constraint trigger commerce_variant_integrity after insert or update on public.product_variants
  deferrable initially deferred for each row execute function private.recheck_commerce_variant();
create constraint trigger commerce_variant_link_integrity after insert or update or delete on public.variant_compatibilities
  deferrable initially deferred for each row execute function private.recheck_commerce_variant();

create function public.admin_save_commerce_record(p_actor uuid,p_kind text,p_id uuid,p_data jsonb,p_expected timestamptz default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  v_table text; v_allowed text[]; v_old jsonb; v_data jsonb; v_result jsonb; v_id uuid;
  v_agent public.commerce_agents; v_variant public.product_variants; v_offer public.supplier_offers; v_rate public.shipping_rates;
  v_compat uuid;
begin
  perform private.assert_admin(p_actor);
  if p_data is null or jsonb_typeof(p_data)<>'object' then raise exception 'Commerce data must be an object'; end if;
  case p_kind
    when 'agent' then
      v_table:='commerce_agents'; v_allowed:=array['profile_id','name','role','is_active'];
      v_data:='{"is_active":false}'::jsonb;
    when 'variant' then
      v_table:='product_variants'; v_allowed:=array['product_id','sku','name','attributes','currency','price_cents','stock','status','is_verified','requires_vehicle','sale_tax_bps','evidence_ref','is_default','compatibility_ids'];
      v_data:='{"attributes":{},"currency":"EUR","stock":0,"status":"draft","is_verified":false,"requires_vehicle":true,"is_default":false}'::jsonb;
    when 'offer' then
      v_table:='supplier_offers'; v_allowed:=array['variant_id','supplier_id','supplier_sku','supplier_variant','url','verification_state','evidence_ref','is_primary','availability','available_quantity','valid_until','unit_cost_cents','recoverable_tax_cents','currency','fx_rate','fx_evidence_ref','fx_valid_until','moq','preparation_days_min','preparation_days_max','responsible_agent_id'];
      v_data:='{"verification_state":"pending","is_primary":false,"availability":"unknown","currency":"EUR","moq":1}'::jsonb;
    when 'shipping_rate' then
      v_table:='shipping_rates'; v_allowed:=array['offer_id','country','postal_prefix','mode','min_quantity','max_quantity','currency','shipping_cost_cents','shipping_recoverable_tax_cents','customer_shipping_cents','goods_tax_bps','shipping_tax_bps','agent_fee_cents','import_duty_cents','nonrecoverable_tax_cents','other_cost_cents','verification_state','evidence_ref','valid_until','delivery_days_min','delivery_days_max'];
      v_data:='{"postal_prefix":"","min_quantity":1,"currency":"EUR","verification_state":"pending"}'::jsonb;
    else raise exception 'Unknown commerce record kind';
  end case;
  if exists(select 1 from jsonb_object_keys(p_data) k where not (k=any(v_allowed))) then raise exception 'Unknown or immutable commerce field'; end if;
  if p_id is not null then
    execute format('select to_jsonb(t) from public.%I t where id=$1 for update',v_table) into v_old using p_id;
    if v_old is null then raise exception 'Commerce record not found'; end if;
    if p_expected is null or (v_old->>'updated_at')::timestamptz<>p_expected then raise exception 'Commerce record changed; reload' using errcode='40001'; end if;
    v_data:=v_old;
  elsif p_expected is not null then raise exception 'New commerce record cannot have expected timestamp';
  end if;
  v_id:=coalesce(p_id,gen_random_uuid());
  v_data:=v_data || (p_data-'compatibility_ids') || jsonb_build_object('id',v_id,'updated_at',clock_timestamp());
  if p_id is null then v_data:=v_data || jsonb_build_object('created_at',clock_timestamp()); end if;
  case p_kind
    when 'agent' then
      v_agent:=jsonb_populate_record(null::public.commerce_agents,v_data);
      if p_id is null then insert into public.commerce_agents select v_agent.* returning to_jsonb(commerce_agents) into v_result;
      else update public.commerce_agents set profile_id=v_agent.profile_id,name=v_agent.name,role=v_agent.role,is_active=v_agent.is_active,updated_at=clock_timestamp() where id=v_id returning to_jsonb(commerce_agents) into v_result; end if;
    when 'variant' then
      v_variant:=jsonb_populate_record(null::public.product_variants,v_data);
      if jsonb_typeof(v_variant.attributes)<>'object' then raise exception 'Variant attributes must be an object'; end if;
      if (select count(*) from jsonb_object_keys(v_variant.attributes))>30 or exists(
        select 1 from jsonb_each(v_variant.attributes) a where length(a.key)>100 or jsonb_typeof(a.value)<>'string' or length(a.value #>> '{}')>500
      ) then raise exception 'Invalid variant attributes'; end if;
      if p_id is null then insert into public.product_variants select v_variant.*;
      else update public.product_variants set product_id=v_variant.product_id,sku=v_variant.sku,name=v_variant.name,attributes=v_variant.attributes,currency=v_variant.currency,price_cents=v_variant.price_cents,stock=v_variant.stock,status=v_variant.status,is_verified=v_variant.is_verified,requires_vehicle=v_variant.requires_vehicle,sale_tax_bps=v_variant.sale_tax_bps,evidence_ref=v_variant.evidence_ref,is_default=v_variant.is_default where id=v_id; end if;
      if p_data ? 'compatibility_ids' then
        if jsonb_typeof(p_data->'compatibility_ids')<>'array' then raise exception 'compatibility_ids must be an array'; end if;
        if jsonb_array_length(p_data->'compatibility_ids')>100 then raise exception 'Too many compatibility associations'; end if;
        delete from public.variant_compatibilities where variant_id=v_id;
        for v_compat in select value::uuid from jsonb_array_elements_text(p_data->'compatibility_ids') loop
          insert into public.variant_compatibilities(variant_id,compatibility_id) values(v_id,v_compat);
        end loop;
      end if;
      perform private.check_commerce_variant(v_id);
      select to_jsonb(v) || jsonb_build_object('compatibility_ids',coalesce((select jsonb_agg(compatibility_id order by compatibility_id) from public.variant_compatibilities where variant_id=v_id),'[]')) into v_result from public.product_variants v where id=v_id;
    when 'offer' then
      v_offer:=jsonb_populate_record(null::public.supplier_offers,v_data);
      if p_id is null then insert into public.supplier_offers select v_offer.* returning to_jsonb(supplier_offers) into v_result;
      else update public.supplier_offers set variant_id=v_offer.variant_id,supplier_id=v_offer.supplier_id,supplier_sku=v_offer.supplier_sku,supplier_variant=v_offer.supplier_variant,url=v_offer.url,verification_state=v_offer.verification_state,evidence_ref=v_offer.evidence_ref,is_primary=v_offer.is_primary,availability=v_offer.availability,available_quantity=v_offer.available_quantity,valid_until=v_offer.valid_until,unit_cost_cents=v_offer.unit_cost_cents,recoverable_tax_cents=v_offer.recoverable_tax_cents,currency=v_offer.currency,fx_rate=v_offer.fx_rate,fx_evidence_ref=v_offer.fx_evidence_ref,fx_valid_until=v_offer.fx_valid_until,moq=v_offer.moq,preparation_days_min=v_offer.preparation_days_min,preparation_days_max=v_offer.preparation_days_max,responsible_agent_id=v_offer.responsible_agent_id where id=v_id returning to_jsonb(supplier_offers) into v_result; end if;
    when 'shipping_rate' then
      v_rate:=jsonb_populate_record(null::public.shipping_rates,v_data);
      if p_id is null then insert into public.shipping_rates select v_rate.* returning to_jsonb(shipping_rates) into v_result;
      else update public.shipping_rates set offer_id=v_rate.offer_id,country=v_rate.country,postal_prefix=v_rate.postal_prefix,mode=v_rate.mode,min_quantity=v_rate.min_quantity,max_quantity=v_rate.max_quantity,currency=v_rate.currency,shipping_cost_cents=v_rate.shipping_cost_cents,shipping_recoverable_tax_cents=v_rate.shipping_recoverable_tax_cents,customer_shipping_cents=v_rate.customer_shipping_cents,goods_tax_bps=v_rate.goods_tax_bps,shipping_tax_bps=v_rate.shipping_tax_bps,agent_fee_cents=v_rate.agent_fee_cents,import_duty_cents=v_rate.import_duty_cents,nonrecoverable_tax_cents=v_rate.nonrecoverable_tax_cents,other_cost_cents=v_rate.other_cost_cents,verification_state=v_rate.verification_state,evidence_ref=v_rate.evidence_ref,valid_until=v_rate.valid_until,delivery_days_min=v_rate.delivery_days_min,delivery_days_max=v_rate.delivery_days_max where id=v_id returning to_jsonb(shipping_rates) into v_result; end if;
  end case;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
    values(p_actor,'commerce.'||p_kind||'.save',v_id::text,jsonb_build_object('before',v_old,'after',v_result));
  return v_result;
end $$;

do $$ declare t text; begin
  foreach t in array array['commerce_agents','product_variants','supplier_offers','shipping_rates','variant_compatibilities'] loop
    execute format('alter table public.%I enable row level security',t);
    execute format('revoke all on public.%I from public,anon,authenticated',t);
    execute format('grant select,insert,update,delete on public.%I to service_role',t);
  end loop;
end $$;
revoke all on function private.check_commerce_variant(uuid),private.guard_commerce_record(),private.guard_variant_compatibility(),private.recheck_commerce_variant(),private.guard_commerce_source_rule(),public.admin_save_commerce_record(uuid,text,uuid,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function private.check_commerce_variant(uuid),private.guard_commerce_record(),private.guard_variant_compatibility(),private.recheck_commerce_variant(),private.guard_commerce_source_rule(),public.admin_save_commerce_record(uuid,text,uuid,jsonb,timestamptz) to service_role;

commit;
