-- A CJ create-order reservation is durable before the first external POST.
-- One reservation per TYMotors order; a crash or timeout never permits re-send.
-- This migration only stores state. It does not call CJ or charge any account.

create table public.cj_order_submissions (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null unique references public.orders(id) on delete cascade,
  supplier_order_id uuid not null references public.supplier_orders(id) on delete restrict,
  cj_shop_id text not null check (cj_shop_id ~ '^[A-Za-z0-9_-]{1,40}$'),
  fingerprint text not null check (fingerprint ~ '^[0-9a-f]{64}$'),
  payload jsonb not null check (jsonb_typeof(payload) = 'object' and length(payload::text) <= 32768),
  state text not null default 'reserved' check (state in ('reserved','submitted','uncertain')),
  cj_order_id text unique check (cj_order_id is null or (length(cj_order_id) between 1 and 200 and btrim(cj_order_id) = cj_order_id)),
  request_id text check (request_id is null or length(request_id) <= 200),
  actor_id uuid not null references public.profiles(id) on delete restrict,
  observation jsonb check (observation is null or jsonb_typeof(observation) = 'object'),
  reserved_at timestamptz not null default now(),
  finished_at timestamptz,
  observed_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint cj_submission_submitted_has_id check (state <> 'submitted' or cj_order_id is not null)
);

create index cj_order_submissions_supplier_idx on public.cj_order_submissions(supplier_order_id);
create trigger cj_order_submissions_updated_at before update on public.cj_order_submissions
for each row execute function public.set_updated_at();
alter table public.cj_order_submissions enable row level security;
revoke all on public.cj_order_submissions from public,anon,authenticated;
grant select,insert,update on public.cj_order_submissions to service_role;

create function public.admin_claim_cj_submission(
  p_actor uuid,p_order_id uuid,p_expected timestamptz,p_fingerprint text,p_payload jsonb,
  p_cj_shop_id text
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_order public.orders%rowtype;
  v_supplier public.supplier_orders%rowtype;
  v_existing public.cj_order_submissions%rowtype;
  v_submission public.cj_order_submissions%rowtype;
  v_count integer;
begin
  perform private.assert_admin(p_actor);
  select * into v_supplier from public.supplier_orders where order_id=p_order_id for update;
  if not found then raise exception 'Supplier dossier not found'; end if;
  select * into v_order from public.orders where id=p_order_id for update;
  if not found then raise exception 'Order not found'; end if;

  -- This check must precede dispatch eligibility: a retry after a network
  -- ambiguity or a later status change returns the original reservation.
  select * into v_existing from public.cj_order_submissions where order_id=p_order_id;
  if found then
    return jsonb_build_object('claimed',false,'submission',to_jsonb(v_existing));
  end if;

  if p_expected is null or v_supplier.updated_at is distinct from p_expected then
    raise exception 'Supplier dossier changed; reload before dispatch';
  end if;
  if v_order.is_test is distinct from false or v_order.sales_channel='diagnostic'
    or v_order.payment_status is distinct from 'paid' or v_order.status is distinct from 'paid'
    or v_order.requires_compatibility_review is distinct from false
    or v_order.fulfillment_status in ('cancelled','shipped','delivered')
    or v_order.stock_applied_at is null or v_order.stock_shortfall_at is not null then
    raise exception 'Paid non-test order with secured stock and confirmed fitment required';
  end if;
  if v_supplier.status <> 'approved' or v_supplier.approved_by is null
    or v_supplier.approved_at is null or v_supplier.agent_provider <> 'CJdropshipping'
    or nullif(btrim(coalesce(v_supplier.agent_order_id,'')),'') is not null then
    raise exception 'Approved CJ supplier dossier without an agent order required';
  end if;
  if p_fingerprint is null or p_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'Invalid CJ dossier fingerprint';
  end if;
  if p_cj_shop_id is null or p_cj_shop_id !~ '^[A-Za-z0-9_-]{1,40}$' then
    raise exception 'Invalid CJ shop ID';
  end if;
  if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
    raise exception 'Invalid CJ order payload';
  end if;
  if exists (
    select 1 from jsonb_object_keys(p_payload) as k(name)
    where k.name <> all(array[
      'orderNumber','payType','orderFlow','isSandbox','platform','shopLogisticsType',
      'storeName','shippingZip','shippingCountryCode','shippingCountry',
      'shippingProvince','shippingCity','shippingPhone','shippingCustomerName',
      'shippingAddress','shippingAddress2','email','logisticName',
      'fromCountryCode','products'
    ])
  ) then raise exception 'Unsupported CJ order payload field'; end if;
  if p_payload->'payType' is distinct from '3'::jsonb
    or p_payload->'orderFlow' is distinct from '1'::jsonb
    or p_payload->'isSandbox' is distinct from '0'::jsonb
    or p_payload->>'platform' is distinct from 'Api'
    or p_payload->'shopLogisticsType' is distinct from '2'::jsonb
    or p_payload->>'orderNumber' is distinct from v_order.order_number
    or p_payload->>'shippingCountryCode' is distinct from 'FR'
    or p_payload->>'shippingCountry' is distinct from 'France'
    or p_payload->>'shippingZip' is distinct from v_order.shipping_address->>'postal_code'
    or p_payload->>'shippingProvince' is distinct from v_order.shipping_address->>'state'
    or p_payload->>'shippingCity' is distinct from v_order.shipping_address->>'city'
    or p_payload->>'shippingCustomerName' is distinct from v_order.customer_name
    or p_payload->>'shippingAddress' is distinct from v_order.shipping_address->>'line1'
    or (p_payload ? 'shippingAddress2' and p_payload->>'shippingAddress2'
        is distinct from coalesce(v_order.shipping_address->>'line2',''))
    or (p_payload ? 'shippingPhone' and p_payload->>'shippingPhone'
        is distinct from v_order.customer_phone)
    or (p_payload ? 'email' and p_payload->>'email'
        is distinct from v_order.customer_email)
    or nullif(btrim(coalesce(p_payload->>'shippingZip','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'shippingProvince','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'shippingCity','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'shippingCustomerName','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'shippingAddress','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'storeName','')),'') is null
    or length(p_payload->>'storeName') > 50
    or nullif(btrim(coalesce(p_payload->>'logisticName','')),'') is null
    or nullif(btrim(coalesce(p_payload->>'fromCountryCode','')),'') is null
  then raise exception 'CJ payload must match the paid order and create-only contract'; end if;
  if jsonb_typeof(p_payload->'products') is distinct from 'array' then
    raise exception 'CJ products must be an array';
  end if;
  select count(*) into v_count from public.order_items where order_id=p_order_id;
  if v_count < 1 or v_count > 20 or jsonb_array_length(p_payload->'products') <> v_count then
    raise exception 'CJ products must match every order line';
  end if;
  if exists (select 1 from jsonb_array_elements(p_payload->'products') as l(value)
             where jsonb_typeof(l.value) <> 'object') then
    raise exception 'CJ line must be an object';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_payload->'products') as l(value)
    where exists (select 1 from jsonb_object_keys(l.value) as k(name)
                  where k.name <> all(array['vid','sku','storeProductId','storeSku','quantity','storeLineItemId']))
       or nullif(btrim(coalesce(l.value->>'vid','')),'') is null
       or nullif(btrim(coalesce(l.value->>'sku','')),'') is null
       or length(l.value->>'vid') > 50 or length(l.value->>'sku') > 50
  ) then raise exception 'CJ line contains an unsupported or missing variant identifier'; end if;
  if (select count(distinct l.value->>'storeLineItemId')
      from jsonb_array_elements(p_payload->'products') as l(value)) <> v_count
    or exists (
      select 1 from jsonb_array_elements(p_payload->'products') as l(value)
      left join public.order_items oi on oi.order_id=p_order_id
        and oi.id::text=l.value->>'storeLineItemId'
      where oi.id is null or l.value->>'storeProductId' is distinct from oi.product_id::text
        or l.value->>'storeSku' is distinct from oi.sku
        or l.value->'quantity' is distinct from to_jsonb(oi.quantity)
    ) then raise exception 'CJ line mapping differs from the paid order'; end if;
  if (select count(*) from public.supplier_order_items where supplier_order_id=v_supplier.id) <> v_count
    or exists (
      select 1 from public.order_items oi
      left join public.supplier_order_items si on si.order_item_id=oi.id
        and si.supplier_order_id=v_supplier.id
      left join public.product_supplier_data psd on psd.product_id=oi.product_id
      left join public.products p on p.id=oi.product_id
      where oi.order_id=p_order_id and (
        si.id is null or si.product_id is distinct from oi.product_id
        or si.sku is distinct from oi.sku or si.quantity is distinct from oi.quantity
        or nullif(btrim(coalesce(si.supplier_name,'')),'') is null
        or nullif(btrim(coalesce(si.supplier_reference,'')),'') is null
        or nullif(btrim(coalesce(si.exact_source_url,'')),'') is null
        or si.unit_cost_cents is null or psd.supplier_verified is distinct from true
        or psd.supplier_reference is distinct from si.supplier_reference
        or psd.cost_price_cents is null or psd.shipping_cost_cents is null
        or p.is_verified is distinct from true
        or oi.compatibility_result->>'status' is distinct from 'compatible'
        or not exists (select 1 from public.product_compatibilities c
                       where c.product_id=oi.product_id and c.verification_state='verified')
      )
    ) then raise exception 'Supplier, product and fitment evidence changed'; end if;

  insert into public.cj_order_submissions(
    order_id,supplier_order_id,cj_shop_id,fingerprint,payload,actor_id
  ) values(p_order_id,v_supplier.id,p_cj_shop_id,p_fingerprint,p_payload,p_actor)
  returning * into v_submission;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'cj_submission.claim',p_order_id::text,
         jsonb_build_object('submission_id',v_submission.id,'state','reserved'));
  return jsonb_build_object('claimed',true,'submission',to_jsonb(v_submission));
end $$;

create function public.admin_finish_cj_submission(
  p_actor uuid,p_submission_id uuid,p_state text,p_cj_order_id text,p_request_id text
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_submission public.cj_order_submissions%rowtype;
        v_supplier public.supplier_orders%rowtype;
begin
  perform private.assert_admin(p_actor);
  select * into v_submission from public.cj_order_submissions where id=p_submission_id for update;
  if not found then raise exception 'CJ submission not found'; end if;
  if v_submission.state <> 'reserved' or p_state not in ('submitted','uncertain') then
    raise exception 'CJ submission cannot be finished twice';
  end if;
  if p_cj_order_id is not null and (nullif(btrim(p_cj_order_id),'') is null
    or length(p_cj_order_id) > 200) then raise exception 'Invalid CJ order ID'; end if;
  if p_request_id is not null and length(p_request_id) > 200 then
    raise exception 'Invalid CJ request ID';
  end if;
  if p_state='submitted' and p_cj_order_id is null then
    raise exception 'Submitted CJ order requires its ID';
  end if;
  select * into v_supplier from public.supplier_orders where id=v_submission.supplier_order_id for update;
  if not found or v_supplier.order_id <> v_submission.order_id then
    raise exception 'CJ supplier dossier no longer matches';
  end if;
  if p_state='submitted' and nullif(btrim(coalesce(v_supplier.agent_order_id,'')),'') is not null
    and v_supplier.agent_order_id is distinct from p_cj_order_id then
    raise exception 'Supplier dossier already has a different CJ order ID';
  end if;
  if p_state='submitted' and exists (
    select 1 from public.supplier_orders s
    where s.id <> v_supplier.id and s.agent_order_id=p_cj_order_id
  ) then raise exception 'CJ order ID already belongs to another supplier dossier'; end if;
  update public.cj_order_submissions
    set state=p_state,cj_order_id=p_cj_order_id,request_id=p_request_id,finished_at=now()
    where id=p_submission_id returning * into v_submission;
  if p_state='submitted' then
    update public.supplier_orders set agent_order_id=p_cj_order_id where id=v_supplier.id;
  end if;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'cj_submission.finish',v_submission.order_id::text,
         jsonb_build_object('submission_id',v_submission.id,'state',p_state,
                            'cj_order_id',p_cj_order_id));
  return to_jsonb(v_submission);
end $$;

create function public.admin_observe_cj_submission(
  p_actor uuid,p_submission_id uuid,p_observation jsonb
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare v_submission public.cj_order_submissions%rowtype;
begin
  perform private.assert_admin(p_actor);
  if p_observation is null or jsonb_typeof(p_observation) <> 'object'
    or length(p_observation::text) > 8192 then raise exception 'Invalid CJ observation'; end if;
  if exists (select 1 from jsonb_object_keys(p_observation) as k(name)
             where k.name <> all(array[
               'shop_id','order_id','order_status','sub_status','tracking_number',
               'tracking_provider','logistic_name','order_number','products'
             ])) then raise exception 'CJ observation contains unsupported fields'; end if;
  if jsonb_typeof(p_observation->'products') is distinct from 'array' then
    raise exception 'Invalid CJ observation products';
  end if;
  if jsonb_typeof(p_observation->'products')='array'
    and jsonb_array_length(p_observation->'products') > 20 then
    raise exception 'Invalid CJ observation product count';
  end if;
  if exists (select 1 from jsonb_each(p_observation) as e(key,value)
             where e.key <> 'products' and jsonb_typeof(e.value) not in ('string','null'))
    or exists (select 1 from jsonb_each_text(p_observation) as e(key,value)
               where e.key <> 'products' and length(e.value) > 200) then
    raise exception 'Invalid CJ observation value';
  end if;
  select * into v_submission from public.cj_order_submissions where id=p_submission_id for update;
  if not found then raise exception 'CJ submission not found'; end if;
  if v_submission.state <> 'submitted'
    or p_observation->>'order_id' is distinct from v_submission.cj_order_id
    or p_observation->>'shop_id' is distinct from v_submission.cj_shop_id
    or nullif(btrim(coalesce(p_observation->>'order_status','')),'') is null then
    raise exception 'CJ observation requires the submitted order identity and status';
  end if;
  if jsonb_typeof(p_observation->'products')='array' then
    if exists (select 1 from jsonb_array_elements(p_observation->'products') as l(value)
               where jsonb_typeof(l.value) <> 'object') then
      raise exception 'Invalid CJ observation product line';
    end if;
    if jsonb_array_length(p_observation->'products') <> jsonb_array_length(v_submission.payload->'products')
      or (select count(distinct l.value->>'store_line_item_id')
          from jsonb_array_elements(p_observation->'products') as l(value))
        <> jsonb_array_length(v_submission.payload->'products')
      or exists (
        select 1 from jsonb_array_elements(p_observation->'products') as l(value)
        where exists (select 1 from jsonb_object_keys(l.value) as k(name)
                      where k.name <> all(array['vid','quantity','store_line_item_id']))
          or not exists (
            select 1 from jsonb_array_elements(v_submission.payload->'products') as p(value)
            where p.value->>'storeLineItemId' = l.value->>'store_line_item_id'
              and p.value->>'vid' = l.value->>'vid'
              and p.value->'quantity' = l.value->'quantity'
          )
      ) then raise exception 'CJ observation product lines differ from reserved payload'; end if;
  end if;
  update public.cj_order_submissions set observation=p_observation,observed_at=now()
  where id=p_submission_id returning * into v_submission;
  insert into public.order_tracking_events(order_id,event_key,title,description,source,
                                           is_customer_visible,metadata)
  values(v_submission.order_id,'cj_submission_observed','Observation CJ interne',
         'État CJ vérifié côté administration.','agent',false,
         jsonb_build_object('submission_id',v_submission.id,'state',v_submission.state,
                            'observation',p_observation));
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'cj_submission.observe',v_submission.order_id::text,
         jsonb_build_object('submission_id',v_submission.id,'state',v_submission.state));
  return to_jsonb(v_submission);
end $$;

revoke all on function public.admin_claim_cj_submission(uuid,uuid,timestamptz,text,jsonb,text),
  public.admin_finish_cj_submission(uuid,uuid,text,text,text),
  public.admin_observe_cj_submission(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.admin_claim_cj_submission(uuid,uuid,timestamptz,text,jsonb,text),
  public.admin_finish_cj_submission(uuid,uuid,text,text,text),
  public.admin_observe_cj_submission(uuid,uuid,jsonb) to service_role;
notify pgrst, 'reload schema';
