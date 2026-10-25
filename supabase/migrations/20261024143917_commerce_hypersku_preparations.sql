-- Internal HyperSKU review only: no vendor endpoint, transmission or spending.
begin;
create table public.commerce_hypersku_mappings (
  id uuid primary key default gen_random_uuid(),
  offer_id uuid not null references public.supplier_offers(id) on delete restrict,
  shipping_rate_id uuid not null references public.shipping_rates(id) on delete restrict,
  is_test boolean not null default false,
  state text not null default 'pending' check(state in ('pending','verified','rejected')),
  hypersku_product_ref text check(length(btrim(hypersku_product_ref)) between 1 and 200),
  hypersku_variant_ref text check(length(btrim(hypersku_variant_ref)) between 1 and 200),
  equivalence_evidence_ref text check(length(btrim(equivalence_evidence_ref)) between 1 and 2000),
  provider_quote_ref text check(length(btrim(provider_quote_ref)) between 1 and 2000),
  valid_until timestamptz,
  offer_snapshot jsonb not null check(jsonb_typeof(offer_snapshot)='object'),
  rate_snapshot jsonb not null check(jsonb_typeof(rate_snapshot)='object'),
  verified_by uuid references public.profiles(id) on delete restrict,
  verified_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(offer_id,shipping_rate_id,is_test),
  check(state<>'verified' or (hypersku_product_ref is not null and hypersku_variant_ref is not null
    and equivalence_evidence_ref is not null and provider_quote_ref is not null and valid_until is not null
    and verified_by is not null and verified_at is not null))
);
create index commerce_hypersku_mapping_rate on public.commerce_hypersku_mappings(shipping_rate_id);
create trigger commerce_hypersku_mapping_updated before update on public.commerce_hypersku_mappings
for each row execute function public.set_updated_at();

create table public.commerce_hypersku_preparations (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null unique references public.commerce_test_tasks(id) on delete restrict,
  order_id uuid not null references public.orders(id) on delete restrict,
  mapping_id uuid not null references public.commerce_hypersku_mappings(id) on delete restrict,
  responsible_agent_id uuid not null,
  prepared_by uuid not null references public.profiles(id) on delete restrict,
  state text not null default 'awaiting_human_review' check(state='awaiting_human_review'),
  is_test boolean not null default true check(is_test),
  external_send_allowed boolean not null default false check(not external_send_allowed),
  expenses_authorized boolean not null default false check(not expenses_authorized),
  mapping_snapshot jsonb not null check(jsonb_typeof(mapping_snapshot)='object'),
  packet jsonb not null check(jsonb_typeof(packet)='object'),
  packet_hash text not null check(packet_hash ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default clock_timestamp()
);
create index commerce_hypersku_preparations_order on public.commerce_hypersku_preparations(order_id);
create index commerce_hypersku_preparations_mapping on public.commerce_hypersku_preparations(mapping_id);
create trigger commerce_hypersku_preparations_history before update or delete on public.commerce_hypersku_preparations
for each row execute function private.guard_commerce_test_history();
create trigger commerce_hypersku_preparations_no_truncate before truncate on public.commerce_hypersku_preparations
for each statement execute function private.guard_commerce_test_history();

create function public.commerce_save_hypersku_mapping(p_actor uuid,p_data jsonb,p_expected timestamptz default null)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare d public.commerce_hypersku_mappings; r public.commerce_hypersku_mappings;
  o public.supplier_offers; sr public.shipping_rates; key text;
begin
  perform private.assert_admin(p_actor);
  if jsonb_typeof(p_data) is distinct from 'object' then raise exception 'Mapping object required'; end if;
  for key in select jsonb_object_keys(p_data) loop
    if key not in ('offer_id','shipping_rate_id','is_test','state','hypersku_product_ref','hypersku_variant_ref',
      'equivalence_evidence_ref','provider_quote_ref','valid_until') then raise exception 'Unknown mapping field'; end if;
  end loop;
  d:=jsonb_populate_record(null::public.commerce_hypersku_mappings,'{"is_test":false,"state":"pending"}'::jsonb||p_data);
  perform private.lock_commerce_quote_sources();
  perform private.assert_admin(p_actor);
  select * into o from public.supplier_offers where id=d.offer_id;
  select * into sr from public.shipping_rates where id=d.shipping_rate_id;
  if o.id is null or sr.id is null or sr.offer_id<>o.id then raise exception 'Exact offer/rate association required'; end if;
  if d.state='verified' and (d.valid_until is null or d.valid_until<=clock_timestamp()
    or o.verification_state<>'verified' or sr.verification_state<>'verified' or sr.country<>'FR'
    or o.valid_until is null or o.valid_until<d.valid_until or sr.valid_until is null or sr.valid_until<d.valid_until)
    then raise exception 'Confirmed unexpired France offer and provider quote required'; end if;
  select * into r from public.commerce_hypersku_mappings where offer_id=o.id and shipping_rate_id=sr.id and is_test=d.is_test for update;
  if found then
    if p_expected is null or r.updated_at<>p_expected then raise exception 'Mapping changed; reload'; end if;
    update public.commerce_hypersku_mappings set state=d.state,hypersku_product_ref=d.hypersku_product_ref,
      hypersku_variant_ref=d.hypersku_variant_ref,equivalence_evidence_ref=d.equivalence_evidence_ref,
      provider_quote_ref=d.provider_quote_ref,valid_until=d.valid_until,offer_snapshot=to_jsonb(o),rate_snapshot=to_jsonb(sr),
      verified_by=case when d.state='verified' then p_actor end,verified_at=case when d.state='verified' then clock_timestamp() end
      where id=r.id returning * into r;
  else
    if p_expected is not null then raise exception 'Mapping does not exist'; end if;
    insert into public.commerce_hypersku_mappings(offer_id,shipping_rate_id,is_test,state,hypersku_product_ref,hypersku_variant_ref,
      equivalence_evidence_ref,provider_quote_ref,valid_until,offer_snapshot,rate_snapshot,verified_by,verified_at)
    values(o.id,sr.id,d.is_test,d.state,d.hypersku_product_ref,d.hypersku_variant_ref,d.equivalence_evidence_ref,d.provider_quote_ref,
      d.valid_until,to_jsonb(o),to_jsonb(sr),case when d.state='verified' then p_actor end,
      case when d.state='verified' then clock_timestamp() end) returning * into r;
  end if;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.hypersku.mapping',r.id::text,
    jsonb_build_object('state',r.state,'is_test',r.is_test,'offer_id',r.offer_id));
  return to_jsonb(r);
end $$;

create function public.commerce_prepare_hypersku_task(p_actor uuid,p_task_id uuid,p_mapping_id uuid)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare t public.commerce_test_tasks; ord public.orders; m public.commerce_hypersku_mappings;
  existing public.commerce_hypersku_preparations; offer_row public.supplier_offers; rate_row public.shipping_rates;
  product uuid; source jsonb; packet jsonb;
begin
  perform private.assert_admin(p_actor);
  select * into t from public.commerce_test_tasks where id=p_task_id;
  if not found then raise exception 'Unknown test task'; end if;
  select * into ord from public.orders where id=t.order_id for update;
  select * into strict t from public.commerce_test_tasks where id=p_task_id for update;
  if not ord.is_test or not t.is_test or ord.payment_status<>'paid' or ord.status in ('cancelled','refunded')
    or ord.refunded_amount_cents>0 then raise exception 'Paid non-cancelled test order required'; end if;
  select * into existing from public.commerce_hypersku_preparations where task_id=t.id;
  if found then
    if existing.mapping_id<>p_mapping_id then raise exception 'Prepared mapping cannot be replaced'; end if;
    return to_jsonb(existing);
  end if;
  if t.state<>'prepared' then raise exception 'Task already in simulated processing'; end if;
  perform private.lock_commerce_quote_sources();
  perform private.assert_admin(p_actor);
  select * into m from public.commerce_hypersku_mappings where id=p_mapping_id for share;
  if not found or not m.is_test or m.state<>'verified' or m.valid_until<=clock_timestamp()
    or m.offer_id<>t.offer_id or m.shipping_rate_id<>t.shipping_rate_id
    or m.offer_snapshot is distinct from t.snapshot->'offer' or m.rate_snapshot is distinct from t.snapshot->'rate'
    then raise exception 'Exact verified unexpired test HyperSKU mapping required'; end if;
  select * into offer_row from public.supplier_offers where id=m.offer_id;
  select * into rate_row from public.shipping_rates where id=m.shipping_rate_id;
  if offer_row.id is null or rate_row.id is null or to_jsonb(offer_row) is distinct from m.offer_snapshot
    or to_jsonb(rate_row) is distinct from m.rate_snapshot or rate_row.country<>'FR'
    then raise exception 'Provider/source terms changed; human review required'; end if;
  select product_id into product from public.product_variants where id=t.variant_id;
  source:=jsonb_build_object('country',rate_row.country,'cart_items',jsonb_build_array(jsonb_build_object('product_id',product)),
    'product_images',coalesce((select jsonb_agg(to_jsonb(i)) from public.product_images i where product_id=product),'[]'::jsonb),
    'image_permissions',coalesce((select jsonb_agg(to_jsonb(i)) from public.commerce_image_permissions i where product_id=product),'[]'::jsonb));
  perform private.check_commerce_image_permissions(source,clock_timestamp());
  if not exists(select 1 from public.commerce_agents where id=t.agent_id and is_active and role in ('orders','supervisor')
      and profile_id is not distinct from (t.snapshot->'agent'->>'profile_id')::uuid)
    then raise exception 'Responsible orders agent is inactive, reassigned or no longer authorized'; end if;
  packet:=jsonb_build_object('format','TYMOTORS_INTERNAL_HYPERSKU_REVIEW_V1','is_test',true,'external_send_allowed',false,
    'expenses_authorized',false,'certified_provider_import',false,'order_id',ord.id,'task_id',t.id,
    'origin_supplier_id',t.supplier_id,'origin_supplier_sku',t.supplier_sku,'tymotors_variant_id',t.variant_id,
    'hypersku_product_ref',m.hypersku_product_ref,'hypersku_variant_ref',m.hypersku_variant_ref,'quantity',t.quantity,
    'responsible_agent_id',t.agent_id,'provider_quote_ref',m.provider_quote_ref,'destination_country',rate_row.country,
    'mode',rate_row.mode,'terms_snapshot',t.snapshot,'mapping_snapshot',to_jsonb(m),
    'missing_provider_requirements',jsonb_build_array('account_template_and_operation_effects_not_verified','customer_data_transfer_not_authorized'));
  insert into public.commerce_hypersku_preparations(task_id,order_id,mapping_id,responsible_agent_id,prepared_by,mapping_snapshot,packet,packet_hash)
  values(t.id,ord.id,m.id,t.agent_id,p_actor,to_jsonb(m),packet,encode(sha256(convert_to(packet::text,'UTF8')),'hex')) returning * into existing;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.hypersku.prepared',existing.id::text,
    jsonb_build_object('is_test',true,'external_send_allowed',false,'expenses_authorized',false));
  return to_jsonb(existing);
end $$;

alter table public.commerce_hypersku_mappings enable row level security;
alter table public.commerce_hypersku_preparations enable row level security;
revoke all on public.commerce_hypersku_mappings,public.commerce_hypersku_preparations from public,anon,authenticated,service_role;
grant select,insert,update on public.commerce_hypersku_mappings to service_role;
grant select,insert on public.commerce_hypersku_preparations to service_role;
revoke all on function public.commerce_save_hypersku_mapping(uuid,jsonb,timestamptz),public.commerce_prepare_hypersku_task(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.commerce_save_hypersku_mapping(uuid,jsonb,timestamptz),public.commerce_prepare_hypersku_task(uuid,uuid,uuid) to service_role;
commit;
