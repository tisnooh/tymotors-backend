-- Durable TEST preparation only. No provider call, payment or real stock mutation.
begin;
create table public.commerce_checkout_attempts (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null unique references public.orders(id) on delete restrict,
  commerce_quote_id uuid not null references public.commerce_quotes(id) on delete restrict,
  is_test boolean not null default true check (is_test),
  currency text not null default 'EUR' check (currency='EUR'),
  total_cents integer not null check (total_cents between 50 and 99999999),
  expires_at bigint not null check (expires_at between 1 and 253402300799),
  quote_expires_at timestamptz not null,
  frontend_origin text not null check (length(frontend_origin) between 8 and 300),
  integration_identifier text not null unique check (integration_identifier ~ '^[A-Za-z0-9_-]+_[A-Za-z]{8}$' and length(integration_identifier)<=200),
  idempotency_key text not null unique check (length(idempotency_key) between 16 and 200),
  state text not null default 'drafting' check (state in ('drafting','ready','creating','unknown','session_created','cancelled')),
  params jsonb, params_hash text,
  first_requested_at timestamptz,
  session_id text, session_url text,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  check (expires_at<=extract(epoch from quote_expires_at)),
  check ((params is null and params_hash is null) or (params is not null and params_hash is not null
    and jsonb_typeof(params)='object' and params_hash ~ '^[a-f0-9]{64}$')),
  check ((state='drafting' and params is null and first_requested_at is null)
    or (state='ready' and params is not null and first_requested_at is null)
    or (state in ('creating','unknown','session_created') and params is not null and first_requested_at is not null)
    or (state='cancelled' and first_requested_at is null)),
  check ((session_id is null and session_url is null) or
    (state='session_created' and session_id is not null and session_url is not null
      and session_id ~ '^cs_test_[A-Za-z0-9]+$' and session_url ~ '^https://checkout[.]stripe[.]com/'))
);
create table public.commerce_variant_reservations (
  attempt_id uuid not null references public.commerce_checkout_attempts(id) on delete restrict,
  variant_id uuid not null references public.product_variants(id) on delete restrict,
  offer_id uuid not null references public.supplier_offers(id) on delete restrict,
  quantity integer not null check (quantity between 1 and 2000),
  is_test boolean not null default true check (is_test),
  state text not null default 'held' check (state in ('held','released','consumed')),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  primary key(attempt_id,variant_id,offer_id)
);
create index commerce_reservations_variant_held on public.commerce_variant_reservations(variant_id) where state='held';
create index commerce_reservations_offer_held on public.commerce_variant_reservations(offer_id) where state='held';
create index commerce_attempts_quote on public.commerce_checkout_attempts(commerce_quote_id);

create function private.lock_commerce_attempts() returns void
language plpgsql security invoker set search_path='' as $$
begin
  lock table public.profiles,public.order_items,
    public.commerce_checkout_attempts,public.commerce_variant_reservations in exclusive mode nowait;
exception when lock_not_available then raise exception 'Commerce attempt busy; retry safely';
end $$;

-- Lock cart -> quote -> order, never discover the cart while holding order.
-- Source barrier uses NOWAIT so an existing writer cannot create an upgrade cycle.
create function private.commerce_attempt_order(p_actor uuid,p_order_id uuid) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare o public.orders; q public.commerce_quotes; n integer;
begin
  perform private.assert_admin(p_actor);
  select * into o from public.orders where id=p_order_id;
  if not found or o.commerce_quote_id is null then raise exception 'Quoted test order required'; end if;
  select * into q from public.commerce_quotes where id=o.commerce_quote_id;
  if not found or q.cart_id is null then raise exception 'Quote cart is missing'; end if;
  perform 1 from public.carts where id=q.cart_id for update;
  perform private.assert_cart_owner(q.cart_id,q.owner_user_id,q.owner_guest_session);
  select * into strict q from public.commerce_quotes where id=o.commerce_quote_id for update;
  select * into strict o from public.orders where id=p_order_id for update;
  if q.cart_id is null or o.commerce_quote_id<>q.id or o.cart_id is distinct from q.cart_id
    or o.user_id is distinct from q.owner_user_id or o.guest_session_id is distinct from q.owner_guest_session
    or o.is_test is distinct from true or o.status<>'pending' or o.payment_status<>'unpaid'
    or q.state<>'consumed' or o.currency<>'EUR' or o.total_cents<>q.total_cents
    or o.subtotal_cents<>q.subtotal_cents or o.shipping_amount_cents<>q.shipping_cents
    or o.tax_amount_cents<>q.tax_cents or o.shipping_address is distinct from q.destination
    or o.promotion_id is not null or o.discount_amount_cents<>0 then raise exception 'Pending unpaid test order snapshot required'; end if;
  perform private.lock_commerce_quote_sources();
  perform private.lock_commerce_attempts();
  perform private.assert_admin(p_actor);
  select count(*) into n from public.order_items where order_id=o.id;
  if n not between 1 and 100 or n<>(select count(*) from jsonb_array_elements(q.payload->'groups') g,
      lateral jsonb_array_elements(g->'lines') l)
    or n<>(select count(*) from public.commerce_order_lines where order_id=o.id)
    or exists(select 1 from public.order_items i where i.order_id=o.id and not exists(
      select 1 from public.commerce_order_lines cl,
        jsonb_array_elements(q.payload->'groups') g,lateral jsonb_array_elements(g->'lines') l
      where cl.order_id=o.id and cl.quote_id=q.id and cl.order_item_id=i.id and cl.line_snapshot=l
        and cl.source_cart_item_id=i.source_cart_item_id and (l->>'cart_item_id')::uuid=i.source_cart_item_id
        and row(i.product_id,i.variant_id,i.product_name,i.product_slug,i.sku,i.quantity,i.unit_amount_cents,i.currency,
          i.image_url,i.selected_vehicle,i.compatibility_result,i.variant_name,i.variant_attributes)
        is not distinct from row((l->>'product_id')::uuid,(l->>'variant_id')::uuid,l->>'product_name',l->>'product_slug',l->>'sku',
          (l->>'quantity')::integer,(l->>'unit_amount_cents')::integer,'EUR'::text,l->>'image_url',l->'selected_vehicle',
          l->'compatibility_result',l->>'variant_name',l->'variant_attributes')))
    then raise exception 'Quoted order item snapshot mismatch'; end if;
  return jsonb_build_object('order',to_jsonb(o)||jsonb_build_object('quote_expires_at',q.expires_at),'quote',to_jsonb(q),
    'items',coalesce((select jsonb_agg(to_jsonb(i) order by i.id) from public.order_items i where order_id=o.id),'[]'::jsonb));
end $$;

create function private.check_commerce_attempt_source(p_context jsonb,p_attempt_id uuid,p_deadline timestamptz) returns void
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare q jsonb:=p_context->'quote'; actual jsonb; g jsonb; v jsonb; o jsonb; qty bigint; held bigint;
begin
  if (q->>'expires_at')::timestamptz<p_deadline then raise exception 'Quote expires too soon for checkout'; end if;
  actual:=public.commerce_cart_context((q->>'cart_id')::uuid,(q->>'owner_user_id')::uuid,q->>'owner_guest_session',
    q->>'country',q->'destination'->>'postal_code',q->>'mode');
  if actual is distinct from q->'source_context' then raise exception 'Commerce source changed; request a fresh quote'; end if;
  perform private.check_commerce_quote_payload(actual,q->'payload',p_deadline);
  for g in select value from jsonb_array_elements(q->'payload'->'groups') loop
    v:=private.commerce_context_row(actual,'variants',(g->>'variant_id')::uuid);
    o:=private.commerce_context_row(actual,'offers',(g->>'offer_id')::uuid);
    select sum((value->>'quantity')::integer) into qty from jsonb_array_elements(g->'lines');
    -- Expired, creating and unknown attempts ALL keep their held quantities.
    select coalesce(sum(quantity),0) into held from public.commerce_variant_reservations
      where variant_id=(g->>'variant_id')::uuid and state='held' and (p_attempt_id is null or attempt_id<>p_attempt_id);
    if held+qty>(v->>'stock')::bigint then raise exception 'Test variant reservation quantity unavailable'; end if;
    select coalesce(sum(quantity),0) into held from public.commerce_variant_reservations
      where offer_id=(g->>'offer_id')::uuid and state='held' and (p_attempt_id is null or attempt_id<>p_attempt_id);
    if held+qty>(o->>'available_quantity')::bigint then raise exception 'Test supplier reservation quantity unavailable'; end if;
    if p_attempt_id is not null and not exists(select 1 from public.commerce_variant_reservations
      where attempt_id=p_attempt_id and variant_id=(g->>'variant_id')::uuid and offer_id=(g->>'offer_id')::uuid
        and quantity=qty and state='held' and is_test) then raise exception 'Checkout reservation snapshot mismatch'; end if;
  end loop;
  if p_attempt_id is not null and (select count(*) from public.commerce_variant_reservations where attempt_id=p_attempt_id)
    <>jsonb_array_length(q->'payload'->'groups') then raise exception 'Checkout reservation coverage mismatch'; end if;
end $$;

create function private.guard_commerce_attempt_history() returns trigger
language plpgsql security invoker set search_path='' as $$
declare o public.orders; q public.commerce_quotes; c jsonb;
begin
  if tg_op in ('DELETE','TRUNCATE') then raise exception 'Commerce attempt history is immutable'; end if;
  if tg_table_name='commerce_variant_reservations' then
    if tg_op='INSERT' then
      if new.state<>'held' or not exists(select 1 from public.commerce_checkout_attempts a
        join public.commerce_quotes qr on qr.id=a.commerce_quote_id,
        lateral jsonb_array_elements(qr.payload->'groups') g
        where a.id=new.attempt_id and a.state='drafting' and a.first_requested_at is null
          and (g->>'variant_id')::uuid=new.variant_id and (g->>'offer_id')::uuid=new.offer_id
          and (select sum((l->>'quantity')::integer) from jsonb_array_elements(g->'lines') l)=new.quantity)
        then raise exception 'Invalid test reservation snapshot'; end if;
    else
      if (to_jsonb(new)-array['state','updated_at']) is distinct from (to_jsonb(old)-array['state','updated_at'])
        or old.state<>'held' or new.state<>'released' or not exists(select 1 from public.commerce_checkout_attempts
          where id=old.attempt_id and state='cancelled' and first_requested_at is null)
        then raise exception 'Reservation history or transition is immutable'; end if;
    end if;
    new.updated_at:=clock_timestamp(); return new;
  end if;
  if tg_op='INSERT' then
    select * into o from public.orders where id=new.order_id;
    select * into q from public.commerce_quotes where id=new.commerce_quote_id;
    if new.state<>'drafting' or new.params is not null or new.params_hash is not null or new.first_requested_at is not null
      or new.session_id is not null or new.session_url is not null or o.id is null or q.id is null
      or o.commerce_quote_id<>q.id or not o.is_test or o.currency<>new.currency or o.total_cents<>new.total_cents
      or q.expires_at<>new.quote_expires_at then raise exception 'Invalid test checkout attempt snapshot'; end if;
  else
    if (to_jsonb(new)-array['state','params','params_hash','first_requested_at','updated_at'])
      is distinct from (to_jsonb(old)-array['state','params','params_hash','first_requested_at','updated_at']) then
      raise exception 'Checkout attempt snapshot is immutable'; end if;
    if old.params is not null and row(new.params,new.params_hash) is distinct from row(old.params,old.params_hash)
      then raise exception 'Checkout parameters are immutable'; end if;
    if old.first_requested_at is not null and new.first_requested_at is distinct from old.first_requested_at
      then raise exception 'Checkout first request is immutable'; end if;
    if not ((old.state='drafting' and new.state='ready' and new.params is not null and new.first_requested_at is null)
      or (old.state='ready' and new.state='creating' and new.first_requested_at is not null)
      or (old.state='creating' and new.state='unknown')
      or (old.state in ('drafting','ready') and new.state='cancelled' and new.first_requested_at is null))
      then raise exception 'Invalid checkout attempt transition'; end if;
    if old.state='drafting' and new.state='ready' then
      select jsonb_build_object('order',to_jsonb(ord),'items',coalesce((select jsonb_agg(to_jsonb(i) order by i.id)
        from public.order_items i where i.order_id=ord.id),'[]'::jsonb)) into c from public.orders ord where ord.id=new.order_id;
      if new.params is distinct from private.commerce_expected_checkout_params(c,to_jsonb(new))
        then raise exception 'Checkout parameters do not match immutable order'; end if;
    end if;
    if new.params is not null and new.params_hash is distinct from encode(sha256(convert_to(new.params::text,'UTF8')),'hex')
      then raise exception 'Checkout parameter hash mismatch'; end if;
  end if;
  new.updated_at:=clock_timestamp(); return new;
end $$;
create trigger commerce_attempt_history before insert or update or delete on public.commerce_checkout_attempts for each row execute function private.guard_commerce_attempt_history();
create trigger commerce_attempt_no_truncate before truncate on public.commerce_checkout_attempts for each statement execute function private.guard_commerce_attempt_history();
create trigger commerce_reservation_history before insert or update or delete on public.commerce_variant_reservations for each row execute function private.guard_commerce_attempt_history();
create trigger commerce_reservation_no_truncate before truncate on public.commerce_variant_reservations for each statement execute function private.guard_commerce_attempt_history();

create function public.commerce_prepare_checkout_attempt(p_actor uuid,p_order_id uuid,p_frontend_origin text) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare c jsonb; a public.commerce_checkout_attempts; q jsonb; g jsonb; aid uuid; suffix text;
begin
  -- Canonical server origin; the service validates authority more strictly too.
  if p_frontend_origin is null or p_frontend_origin !~ '^(https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?([:][0-9]{1,5})?|http://(localhost|127[.]0[.]0[.]1|\[::1\])([:][0-9]{1,5})?)$'
    or length(p_frontend_origin)>300 then raise exception 'Invalid checkout frontend origin'; end if;
  c:=private.commerce_attempt_order(p_actor,p_order_id);
  select * into a from public.commerce_checkout_attempts where order_id=p_order_id for update;
  if found then
    if a.frontend_origin<>p_frontend_origin then raise exception 'Checkout origin mismatch'; end if;
    return jsonb_build_object('attempt',to_jsonb(a),'order',c->'order','items',c->'items');
  end if;
  q:=c->'quote';
  perform private.check_commerce_attempt_source(c,null,clock_timestamp()+interval '31 minutes');
  aid:=gen_random_uuid(); suffix:=translate(substr(replace(gen_random_uuid()::text,'-',''),1,8),'0123456789','ghijklmnop');
  insert into public.commerce_checkout_attempts(id,order_id,commerce_quote_id,total_cents,expires_at,quote_expires_at,
    frontend_origin,integration_identifier,idempotency_key)
  values(aid,p_order_id,(q->>'id')::uuid,(q->>'total_cents')::integer,floor(extract(epoch from (q->>'expires_at')::timestamptz))::bigint,
    (q->>'expires_at')::timestamptz,p_frontend_origin,'tymotors_test_'||suffix,'tymotors-test-'||aid::text) returning * into a;
  for g in select value from jsonb_array_elements(q->'payload'->'groups') loop
    insert into public.commerce_variant_reservations(attempt_id,variant_id,offer_id,quantity)
    values(a.id,(g->>'variant_id')::uuid,(g->>'offer_id')::uuid,
      (select sum((l->>'quantity')::integer) from jsonb_array_elements(g->'lines') l));
  end loop;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.checkout.prepared',a.id::text,
    jsonb_build_object('order_id',p_order_id,'is_test',true));
  return jsonb_build_object('attempt',to_jsonb(a),'order',c->'order','items',c->'items');
end $$;

-- Independent SQL reconstruction of the pure Python builder's exact output.
-- This deliberately rejects unknown/extra provider options, not a partial whitelist.
create function private.commerce_expected_checkout_params(p_context jsonb,p_attempt jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare o jsonb:=p_context->'order'; i jsonb; lines jsonb:='[]'; pd jsonb; meta jsonb; origin text:=p_attempt->>'frontend_origin';
begin
  if jsonb_array_length(p_context->'items') not between 1 and 100
    or (select sum((value->>'quantity')::bigint*(value->>'unit_amount_cents')::bigint) from jsonb_array_elements(p_context->'items'))
      is distinct from (o->>'subtotal_cents')::bigint
    or (o->>'subtotal_cents')::bigint+(o->>'shipping_amount_cents')::bigint<>(o->>'total_cents')::bigint
    or (o->>'tax_amount_cents')::bigint>(o->>'total_cents')::bigint
    then raise exception 'Checkout item amount snapshot mismatch'; end if;
  meta:=jsonb_build_object('order_id',o->>'id','quote_id',o->>'commerce_quote_id','attempt_id',p_attempt->>'id');
  for i in select value from jsonb_array_elements(p_context->'items') order by value->>'id' loop
    if i->>'currency'<>'EUR' or (i->>'quantity')::integer not between 1 and 20 then raise exception 'Invalid checkout item'; end if;
    pd:=jsonb_build_object('name',i->>'product_name','metadata',jsonb_build_object('product_id',i->>'product_id',
      'variant_id',i->>'variant_id','order_item_id',i->>'id'));
    if i->>'image_url' is not null then pd:=pd||jsonb_build_object('images',jsonb_build_array(i->>'image_url')); end if;
    lines:=lines||jsonb_build_array(jsonb_build_object('quantity',(i->>'quantity')::integer,'price_data',jsonb_build_object(
      'currency','eur','unit_amount',(i->>'unit_amount_cents')::integer,'tax_behavior','inclusive','product_data',pd)));
  end loop;
  return jsonb_build_object('mode','payment','client_reference_id',o->>'id','metadata',meta,'payment_intent_data',jsonb_build_object('metadata',meta),
    'line_items',lines,'shipping_options',jsonb_build_array(jsonb_build_object('shipping_rate_data',jsonb_build_object('type','fixed_amount',
      'fixed_amount',jsonb_build_object('amount',(o->>'shipping_amount_cents')::integer,'currency','eur'),'display_name','Livraison','tax_behavior','inclusive'))),
    'shipping_address_collection',jsonb_build_object('allowed_countries',jsonb_build_array(o->'shipping_address'->>'country')),
    'billing_address_collection','required','automatic_tax',jsonb_build_object('enabled',false),'adaptive_pricing',jsonb_build_object('enabled',false),
    'allow_promotion_codes',false,'integration_identifier',p_attempt->>'integration_identifier','expires_at',(p_attempt->>'expires_at')::bigint,
    'success_url',origin||'/order-success?session_id={CHECKOUT_SESSION_ID}','cancel_url',origin||'/cart?checkout=cancelled');
end $$;

create function public.commerce_store_checkout_params(p_actor uuid,p_attempt_id uuid,p_params jsonb) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare a public.commerce_checkout_attempts; c jsonb;
begin
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id;
  if not found then raise exception 'Checkout attempt not found'; end if;
  c:=private.commerce_attempt_order(p_actor,a.order_id);
  select * into strict a from public.commerce_checkout_attempts where id=p_attempt_id for update;
  if a.params is not null then
    if a.params is distinct from p_params then raise exception 'Checkout parameters are immutable'; end if;
    return to_jsonb(a);
  end if;
  if a.state<>'drafting' or a.expires_at<extract(epoch from clock_timestamp())+1800 then raise exception 'Checkout draft expired or unavailable'; end if;
  if p_params is distinct from private.commerce_expected_checkout_params(c,to_jsonb(a)) then raise exception 'Checkout parameters do not match immutable order'; end if;
  update public.commerce_checkout_attempts set params=p_params,params_hash=encode(sha256(convert_to(p_params::text,'UTF8')),'hex'),state='ready'
    where id=a.id returning * into a;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.checkout.params_stored',a.id::text,jsonb_build_object('params_hash',a.params_hash));
  return to_jsonb(a);
end $$;

create function public.commerce_claim_checkout_attempt(p_actor uuid,p_attempt_id uuid) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare a public.commerce_checkout_attempts; c jsonb;
begin
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id;
  if not found then raise exception 'Checkout attempt not found'; end if;
  c:=private.commerce_attempt_order(p_actor,a.order_id);
  select * into strict a from public.commerce_checkout_attempts where id=p_attempt_id for update;
  if a.state<>'ready' or a.first_requested_at is not null then raise exception 'Checkout attempt cannot be claimed twice'; end if;
  if a.expires_at<extract(epoch from clock_timestamp())+1800 then raise exception 'Checkout creation window expired'; end if;
  perform private.check_commerce_attempt_source(c,a.id,to_timestamp(a.expires_at));
  if a.params is distinct from private.commerce_expected_checkout_params(c,to_jsonb(a)) then raise exception 'Checkout parameters no longer match immutable order'; end if;
  update public.commerce_checkout_attempts set state='creating',first_requested_at=clock_timestamp() where id=a.id returning * into a;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.checkout.claimed',a.id::text,jsonb_build_object('is_test',true));
  return to_jsonb(a);
end $$;

create function public.commerce_checkout_unknown(p_actor uuid,p_attempt_id uuid,p_error_code text) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare a public.commerce_checkout_attempts;
begin
  perform private.assert_admin(p_actor);
  if p_error_code is null or p_error_code not in ('provider_timeout','provider_connection_error','provider_response_unknown',
    'worker_interrupted','idempotency_conflict','provider_unavailable','unclassified_provider_error') then raise exception 'Bounded technical error code required'; end if;
  perform private.lock_commerce_attempts();
  perform private.assert_admin(p_actor);
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id for update;
  if not found or a.state<>'creating' then raise exception 'Checkout attempt is not creating'; end if;
  update public.commerce_checkout_attempts set state='unknown' where id=a.id returning * into a;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.checkout.unknown',a.id::text,jsonb_build_object('code',p_error_code));
  return to_jsonb(a);
end $$;

create function public.commerce_cancel_checkout_draft(p_actor uuid,p_attempt_id uuid) returns jsonb
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare a public.commerce_checkout_attempts;
begin
  perform private.assert_admin(p_actor);
  perform private.lock_commerce_attempts();
  perform private.assert_admin(p_actor);
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id for update;
  if not found then raise exception 'Checkout attempt not found'; end if;
  if a.state='cancelled' then return to_jsonb(a); end if;
  if a.state not in ('drafting','ready') or a.first_requested_at is not null then raise exception 'Claimed checkout requires reconciliation, not cancellation'; end if;
  update public.commerce_checkout_attempts set state='cancelled' where id=a.id returning * into a;
  update public.commerce_variant_reservations set state='released' where attempt_id=a.id and state='held';
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.checkout.draft_cancelled',a.id::text,jsonb_build_object('is_test',true));
  return to_jsonb(a);
end $$;

alter table public.commerce_checkout_attempts enable row level security;
alter table public.commerce_variant_reservations enable row level security;
revoke all on public.commerce_checkout_attempts,public.commerce_variant_reservations from public,anon,authenticated,service_role;
grant select,insert,update on public.commerce_checkout_attempts,public.commerce_variant_reservations to service_role;
revoke all on function private.lock_commerce_attempts(),private.commerce_attempt_order(uuid,uuid),
  private.check_commerce_attempt_source(jsonb,uuid,timestamptz),private.guard_commerce_attempt_history(),private.commerce_expected_checkout_params(jsonb,jsonb),
  public.commerce_prepare_checkout_attempt(uuid,uuid,text),public.commerce_store_checkout_params(uuid,uuid,jsonb),
  public.commerce_claim_checkout_attempt(uuid,uuid),public.commerce_checkout_unknown(uuid,uuid,text),public.commerce_cancel_checkout_draft(uuid,uuid)
  from public,anon,authenticated;
grant execute on function private.lock_commerce_attempts(),private.commerce_attempt_order(uuid,uuid),
  private.check_commerce_attempt_source(jsonb,uuid,timestamptz),private.guard_commerce_attempt_history(),private.commerce_expected_checkout_params(jsonb,jsonb),
  public.commerce_prepare_checkout_attempt(uuid,uuid,text),public.commerce_store_checkout_params(uuid,uuid,jsonb),
  public.commerce_claim_checkout_attempt(uuid,uuid),public.commerce_checkout_unknown(uuid,uuid,text),public.commerce_cancel_checkout_draft(uuid,uuid)
  to service_role;
commit;
