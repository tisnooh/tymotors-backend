-- Account/mode-bound checkout execution. No activation or historical backfill.
-- Every new production request requires a persisted, expiring server approval.
-- Recorded payment truth remains receivable after the new-request gate closes.
begin;
alter table public.orders add column stripe_profile_ref text
  check(stripe_profile_ref is null or stripe_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$');
alter table public.commerce_checkout_attempts add column stripe_profile_ref text
  check(stripe_profile_ref is null or stripe_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$');
alter table public.orders drop constraint orders_stripe_account_context;
alter table public.orders add constraint orders_stripe_account_context check(
  (stripe_account_id is null and stripe_profile_ref is null) or
  (stripe_account_id is not null and stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$' and commerce_quote_id is not null
    and (is_test or stripe_profile_ref is not null)));
alter table public.commerce_checkout_attempts drop constraint commerce_attempt_account_context;
alter table public.commerce_checkout_attempts add constraint commerce_attempt_account_context check(
  (stripe_account_id is null and stripe_profile_ref is null) or
  (stripe_account_id is not null and stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$' and (is_test or stripe_profile_ref is not null)));
-- Replace only the two original constant sandbox checks with mode-bound checks.
do $checks$ declare c record; n integer:=0; begin
  for c in select conrelid::regclass tbl,conname from pg_constraint
    where conrelid in('public.commerce_checkout_attempts'::regclass,'public.commerce_variant_reservations'::regclass)
      and pg_get_constraintdef(oid)='CHECK (is_test)'
  loop n:=n+1; execute format('alter table %s drop constraint %I',c.tbl,c.conname); end loop;
  if n<>2 then raise exception 'Review original sandbox mode CHECK drift'; end if;
end $checks$;
alter table public.commerce_checkout_attempts add constraint commerce_attempt_execution_mode check(
  is_test or (stripe_account_id is not null and stripe_profile_ref is not null));
-- The existing legacy optional session_url contract remains unchanged; the new
-- durable binding does not persist bearer redirect URLs.
do $session_check$ declare c record; n integer:=0; begin
  for c in select conname from pg_constraint where conrelid='public.commerce_checkout_attempts'::regclass
    and contype='c' and pg_get_constraintdef(oid) like '%session_url%' and pg_get_constraintdef(oid) like '%cs_test_%'
  loop n:=n+1; execute format('alter table public.commerce_checkout_attempts drop constraint %I',c.conname); end loop;
  if n<>1 then raise exception 'Review original optional session URL CHECK drift'; end if;
end $session_check$;
alter table public.commerce_checkout_attempts add constraint commerce_attempt_session_binding check(
  (session_id is null and session_url is null) or
  (stripe_profile_ref is null and state='session_created' and session_id is not null and session_url is not null and session_id ~ '^cs_test_[A-Za-z0-9]+$'
    and session_url ~ '^https://checkout[.]stripe[.]com/') or
  (stripe_profile_ref is not null and state in('creating','unknown') and session_id is not null and session_url is null and
    ((is_test and session_id ~ '^cs_test_[A-Za-z0-9_]+$') or
      (not is_test and session_id ~ '^cs_live_[A-Za-z0-9_]+$'))));

create function private.assert_commerce_context(p_is_test boolean,p_stripe_account_id text,p_profile_ref text)
returns void language plpgsql security invoker set search_path='' as $$
begin
  if p_is_test is null or p_stripe_account_id is null or p_stripe_account_id !~ '^acct_[A-Za-z0-9]{1,240}$'
    or p_profile_ref is null or p_profile_ref !~ '^[A-Za-z0-9_-]{1,100}$'
    then raise exception 'Explicit server execution context required'; end if;
end $$;
create function private.assert_commerce_new_execution(p_is_test boolean,p_stripe_account_id text,p_profile_ref text)
returns void language plpgsql security invoker set search_path='' as $$
declare s public.shop_settings; checked_at timestamptz;
begin
  perform private.assert_commerce_context(p_is_test,p_stripe_account_id,p_profile_ref);
  if p_is_test then return; end if;
  select * into s from public.shop_settings where id for share;
  checked_at:=clock_timestamp();
  if not found or s.commerce_live_enabled is distinct from true
    or s.commerce_launch_approval_ref is null or s.commerce_launch_approved_at is null
    or s.commerce_launch_approval_expires_at is null
    or s.commerce_launch_approved_at>checked_at or s.commerce_launch_approval_expires_at<=checked_at
    or s.commerce_launch_stripe_account_id is distinct from p_stripe_account_id
    or s.commerce_launch_profile_ref is distinct from p_profile_ref
    then raise exception 'Production checkout not enabled for this server context'; end if;
end $$;

-- New context receipt journal: historical sandbox journals remain immutable and
-- NULL-context legacy sessions cannot be attributed to the current account.
create table public.commerce_payment_sessions(
  attempt_id uuid primary key references public.commerce_checkout_attempts(id) on delete restrict,
  stripe_account_id text not null check(stripe_account_id is not null and stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$'),
  stripe_profile_ref text not null check(stripe_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$'),
  is_test boolean not null,
  session_id text not null,
  created_at timestamptz not null default clock_timestamp(),
  unique(stripe_account_id,is_test,session_id),
  check((is_test and session_id ~ '^cs_test_[A-Za-z0-9_]+$') or
    (not is_test and session_id ~ '^cs_live_[A-Za-z0-9_]+$'))
);
create table public.commerce_payment_events(
  stripe_account_id text not null check(stripe_account_id is not null and stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$'),
  is_test boolean not null,
  event_id text not null check(event_id ~ '^evt_[A-Za-z0-9_]{1,240}$'),
  stripe_profile_ref text not null check(stripe_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$'),
  event_type text not null,
  object_id text not null,
  attempt_id uuid references public.commerce_checkout_attempts(id) on delete restrict,
  payment_intent_id text check(payment_intent_id is null or payment_intent_id ~ '^pi_[A-Za-z0-9_]{1,240}$'),
  amount_cents integer,
  destination_matches boolean,
  requires_reconciliation boolean not null default true,
  created_at timestamptz not null default clock_timestamp(),
  primary key(stripe_account_id,is_test,event_id)
);
create index commerce_payment_events_intent on public.commerce_payment_events(stripe_account_id,is_test,payment_intent_id)
  where payment_intent_id is not null;
-- Production tasks use the exact paid group snapshots, never mutable product-
-- level supplier guesses. They remain held for explicit operational approval.
create table public.commerce_fulfillment_tasks(
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete restrict,
  attempt_id uuid not null references public.commerce_checkout_attempts(id) on delete restrict,
  group_key text not null,
  supplier_id uuid not null,agent_id uuid not null,offer_id uuid not null,shipping_rate_id uuid not null,variant_id uuid not null,
  supplier_sku text not null check(length(btrim(supplier_sku))>0),
  quantity integer not null check(quantity between 1 and 2000),
  snapshot jsonb not null check(jsonb_typeof(snapshot)='object'),
  state text not null default 'requires_review' check(state='requires_review'),
  review_reasons text[] not null default array['fulfillment_approval_required']
    check(cardinality(review_reasons)>0 and array_position(review_reasons,null) is null),
  is_test boolean not null,
  external_send_allowed boolean not null default false check(not external_send_allowed),
  created_at timestamptz not null default clock_timestamp(),
  unique(order_id,group_key)
);

create function private.guard_commerce_context_history() returns trigger
language plpgsql security invoker set search_path='' as $$
begin raise exception 'Execution receipt and fulfillment snapshots are immutable'; end $$;
do $hist$ declare tbl text; begin
  foreach tbl in array array['commerce_payment_sessions','commerce_payment_events','commerce_fulfillment_tasks'] loop
    execute format('create trigger %I before update or delete on public.%I for each row execute function private.guard_commerce_context_history()',tbl||'_immutable',tbl);
    execute format('create trigger %I before truncate on public.%I for each statement execute function private.guard_commerce_context_history()',tbl||'_no_truncate',tbl);
    execute format('alter table public.%I enable row level security',tbl);
    execute format('revoke all on public.%I from public,anon,authenticated,service_role',tbl);
    execute format('grant select,insert on public.%I to service_role',tbl);
  end loop;
end $hist$;

create or replace function private.guard_commerce_account_context() returns trigger
language plpgsql security invoker set search_path='' as $$
declare o public.orders;
begin
  if tg_op='UPDATE' then
    if new.stripe_account_id is distinct from old.stripe_account_id
      or new.stripe_profile_ref is distinct from old.stripe_profile_ref
      or (old.stripe_account_id is not null and new.is_test is distinct from old.is_test)
      then raise exception 'Checkout account, profile and mode are immutable'; end if;
  elsif tg_table_name='commerce_checkout_attempts' then
    select * into o from public.orders where id=new.order_id;
    if not found or new.is_test is distinct from o.is_test then raise exception 'Checkout account requires matching order mode'; end if;
    if new.stripe_account_id is null then new.stripe_account_id:=o.stripe_account_id;
    elsif new.stripe_account_id is distinct from o.stripe_account_id then raise exception 'Checkout account does not match immutable order'; end if;
    if new.stripe_profile_ref is null then new.stripe_profile_ref:=o.stripe_profile_ref;
    elsif new.stripe_profile_ref is distinct from o.stripe_profile_ref then raise exception 'Checkout profile does not match immutable order'; end if;
  end if;
  if tg_table_name='commerce_checkout_attempts' then
    if new.stripe_account_id is not null and new.stripe_profile_ref is null
      and (new.first_requested_at is not null or new.state in('creating','unknown','session_created'))
      then raise exception 'Legacy account-bound provider creation is not approved'; end if;
    if new.stripe_profile_ref is not null then
      perform private.assert_commerce_context(new.is_test,new.stripe_account_id,new.stripe_profile_ref);
      if tg_op='INSERT' or (new.first_requested_at is not null and old.first_requested_at is null) then
        perform private.assert_commerce_new_execution(new.is_test,new.stripe_account_id,new.stripe_profile_ref);
      end if;
    end if;
  elsif tg_op='INSERT' and new.stripe_profile_ref is not null then
    perform private.assert_commerce_new_execution(new.is_test,new.stripe_account_id,new.stripe_profile_ref);
  end if;
  return new;
end $$;

-- Preserve exact legacy implementations and their sandbox-only wrappers. The
-- new entry points reuse the installed validated cores (including later image,
-- owner and source-barrier amendments), with counted mode-specific changes.
do $cart_modes$ declare d text; a text:='where oldq.cart_id=q.cart_id and ('; begin
  select pg_get_functiondef('private.assert_commerce_cart_purchase(uuid,uuid)'::regprocedure) into d;
  if strpos(d,a)=0 or strpos(d,'p_order_id uuid DEFAULT NULL::uuid)')=0 then raise exception 'Cart purchase mode factor drift'; end if;
  d:=replace(d,'private.assert_commerce_cart_purchase(','private.assert_commerce_context_cart_purchase(');
  d:=replace(d,'p_order_id uuid DEFAULT NULL::uuid)','p_order_id uuid, p_is_test boolean)');
  execute replace(d,a,'where oldq.cart_id=q.cart_id and o.is_test=p_is_test and (');
end $cart_modes$;

do $factor$
declare d text; r record; x record; n integer; old_anchor text; new_anchor text;
begin
  select pg_get_functiondef('private.assert_commerce_checkout_authority(text,uuid,uuid,text,uuid,uuid,uuid,uuid)'::regprocedure) into d;
  d:=replace(d,'private.assert_commerce_checkout_authority(','private.assert_commerce_context_authority(');
  if strpos(d,'not o.is_test or ')=0 then raise exception 'Context owner mode anchor drift'; end if;
  execute replace(d,'not o.is_test or ','');
  for r in select * from (values
    ('commerce_order_from_quote_core','uuid,uuid,uuid,text,boolean,uuid,text,uuid,text,text'),
    ('commerce_attempt_order_core','uuid,uuid,uuid,text,uuid,text'),
    ('commerce_prepare_checkout_attempt_core','uuid,uuid,text,uuid,text,uuid,text'),
    ('commerce_store_checkout_params_core','uuid,uuid,jsonb,uuid,text,uuid,text'),
    ('commerce_claim_checkout_attempt_core','uuid,uuid,uuid,text,uuid,text'),
    ('commerce_checkout_unknown_core','uuid,uuid,text,uuid,text,uuid,text'),
    ('commerce_cancel_checkout_draft_core','uuid,uuid,uuid,text,uuid,text')
  ) x(name,types) loop
    select pg_get_functiondef(('private.'||r.name||'('||r.types||')')::regprocedure) into d;
    d:=replace(d,'private.'||r.name||'(','private.'||replace(r.name,'_core','_context_core')||'(');
    d:=replace(d,'private.assert_commerce_checkout_authority(','private.assert_commerce_context_authority(');
    d:=replace(d,'private.commerce_attempt_order_core(','private.commerce_attempt_order_context_core(');
    d:=replace(d,'private.assert_commerce_cart_purchase(q.id,null)',
      'private.assert_commerce_context_cart_purchase(q.id,null,p_is_test)');
    d:=replace(d,'private.assert_commerce_cart_purchase(o.commerce_quote_id,o.id)',
      'private.assert_commerce_context_cart_purchase(o.commerce_quote_id,o.id,o.is_test)');
    if r.name='commerce_order_from_quote_core' then
      d:=replace(d,'commerce.quote.prepare_test_order','commerce.quote.prepare_context_order');
      for x in select * from (values
        ('p_stripe_account_id text)','p_stripe_account_id text, p_profile_ref text)'),
        ($a$if p_is_test is distinct from true then raise exception 'Only pending test orders are supported; live checkout is disabled'; end if;$a$,
         'perform private.assert_commerce_new_execution(p_is_test,p_stripe_account_id,p_profile_ref);'),
        ($a$if not o.is_test then raise exception 'Existing quote order is not a test order'; end if;$a$,
         $a$if o.is_test is distinct from p_is_test or o.stripe_profile_ref is distinct from p_profile_ref then raise exception 'Existing quote execution context mismatch'; end if;$a$),
        ('is_test,commerce_quote_id,stripe_account_id)','is_test,commerce_quote_id,stripe_account_id,stripe_profile_ref)'),
        ('true,true,q.id,p_stripe_account_id)','true,p_is_test,q.id,p_stripe_account_id,p_profile_ref)'),
        ($a$'is_test',true$a$,$a$'is_test',p_is_test$a$)
      ) changes(old,new) loop
        n:=(length(d)-length(replace(d,x.old,'')))/length(x.old);
        if n=0 then raise exception 'Order execution amendment drift: %',x.old; end if;
        d:=replace(d,x.old,x.new);
      end loop;
    elsif r.name='commerce_attempt_order_core' then
      if strpos(d,'o.is_test is distinct from true')=0 then raise exception 'Attempt mode anchor drift'; end if;
      d:=replace(d,'o.is_test is distinct from true','o.is_test is null');
    elsif r.name='commerce_prepare_checkout_attempt_core' then
      for x in select * from (values
        ('frontend_origin,integration_identifier,idempotency_key)','frontend_origin,integration_identifier,idempotency_key,is_test)'),
        ($a$p_frontend_origin,'tymotors_test_'||suffix,'tymotors-test-'||aid::text)$a$,
         $a$p_frontend_origin,case when (c->'order'->>'is_test')::boolean then 'tymotors_test_' else 'tymotors_live_' end||suffix,
          case when (c->'order'->>'is_test')::boolean then 'tymotors-test-' else 'tymotors-live-' end||aid::text,(c->'order'->>'is_test')::boolean)$a$),
        ('commerce_variant_reservations(attempt_id,variant_id,offer_id,quantity)','commerce_variant_reservations(attempt_id,variant_id,offer_id,quantity,is_test)'),
        ($a$(select sum((l->>'quantity')::integer) from jsonb_array_elements(g->'lines') l));$a$,
         $a$(select sum((l->>'quantity')::integer) from jsonb_array_elements(g->'lines') l),(c->'order'->>'is_test')::boolean);$a$),
        ($a$'is_test',true$a$,$a$'is_test',(c->'order'->>'is_test')::boolean$a$)
      ) changes(old,new) loop
        n:=(length(d)-length(replace(d,x.old,'')))/length(x.old);
        if n=0 then raise exception 'Attempt execution amendment drift: %',x.old; end if;
        d:=replace(d,x.old,x.new);
      end loop;
    elsif r.name in('commerce_claim_checkout_attempt_core','commerce_cancel_checkout_draft_core') then
      d:=replace(d,$a$'is_test',true$a$,$a$'is_test',a.is_test$a$);
    end if;
    execute d;
  end loop;
end $factor$;

-- Quote consumption still requires a pending immutable order; production must
-- carry the explicit server context instead of relying on a sandbox marker.
do $quote_history$ declare d text; a text:='where commerce_quote_id=old.id and is_test and status=''pending'''; begin
  select pg_get_functiondef('private.guard_commerce_history()'::regprocedure) into d;
  if (length(d)-length(replace(d,a,'')))/length(a)<>1 then raise exception 'Quote consumption execution drift'; end if;
  execute replace(d,a,'where commerce_quote_id=old.id and (is_test or (stripe_account_id is not null and stripe_profile_ref is not null)) and status=''pending''');
end $quote_history$;

-- Mode-isolate held test quantities from real inventory capacity. History and
-- exact source checks remain common; no reservation is released on local expiry.
do $source$ declare d text; begin
  select pg_get_functiondef('private.check_commerce_attempt_source(jsonb,uuid,timestamptz)'::regprocedure) into d;
  if (length(d)-length(replace(d,$a$and state='held' and (p_attempt_id$a$,'')))/length($a$and state='held' and (p_attempt_id$a$)<>2 then
    raise exception 'Reservation quantity mode amendment drift'; end if;
  d:=replace(d,$a$and state='held' and (p_attempt_id$a$,
    $a$and state='held' and is_test=(p_context->'order'->>'is_test')::boolean and (p_attempt_id$a$);
  if strpos(d,$a$and quantity=qty and state='held' and is_test)$a$)=0 then raise exception 'Reservation coverage mode anchor drift'; end if;
  execute replace(d,$a$and quantity=qty and state='held' and is_test)$a$,
    $a$and quantity=qty and state='held' and is_test=(p_context->'order'->>'is_test')::boolean)$a$);
end $source$;

-- Existing immutable attempt history gains one exact append-only binding
-- transition; profile/account/mode cannot be replaced or inferred on old rows.
do $attempt_history$ declare d text; begin
  select pg_get_functiondef('private.guard_commerce_attempt_history()'::regprocedure) into d;
  d:=replace(d,'and a.state=''drafting'' and a.first_requested_at is null',
    'and a.state=''drafting'' and a.first_requested_at is null and a.is_test=new.is_test');
  d:=replace(d,'or not o.is_test or o.currency<>new.currency','or new.is_test is distinct from o.is_test or o.currency<>new.currency');
  -- Session binds are allowed only after the immutable ledger INSERT exists.
  d:=replace(d,$a$if (to_jsonb(new)-array['state','params','params_hash','first_requested_at','updated_at'])$a$,
    $a$if new.session_id is distinct from old.session_id then
      if old.session_id is not null or new.session_id is null or new.stripe_profile_ref is null
        or not exists(select 1 from public.commerce_payment_sessions s where s.attempt_id=new.id
          and s.session_id=new.session_id and s.stripe_account_id=new.stripe_account_id
          and s.stripe_profile_ref=new.stripe_profile_ref and s.is_test=new.is_test)
        then raise exception 'Immutable authenticated session binding required'; end if;
    end if;
    if (to_jsonb(new)-array['state','params','params_hash','first_requested_at','updated_at','session_id'])$a$);
  d:=replace(d,$a$(to_jsonb(old)-array['state','params','params_hash','first_requested_at','updated_at'])$a$,
    $a$(to_jsonb(old)-array['state','params','params_hash','first_requested_at','updated_at','session_id'])$a$);
  d:=replace(d,$a$if not ((old.state='drafting'$a$,
    $a$if not ((old.state=new.state and new.state in('creating','unknown') and old.session_id is null and new.session_id is not null)
      or (old.state='drafting'$a$);
  execute d;
end $attempt_history$;

-- Every public context mutation verifies owner plus immutable account/profile.
create function private.commerce_owned_context_attempt(p_attempt_id uuid,p_stripe_account_id text,p_profile_ref text,
  p_user_id uuid,p_guest_session text,p_auth_session_id uuid) returns public.commerce_checkout_attempts
language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts;
begin
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id;
  if not found then raise exception 'Checkout context unavailable'; end if;
  perform private.assert_commerce_context(a.is_test,p_stripe_account_id,p_profile_ref);
  if a.stripe_account_id is distinct from p_stripe_account_id or a.stripe_profile_ref is distinct from p_profile_ref then
    raise exception 'Checkout execution context mismatch'; end if;
  perform private.assert_commerce_context_authority('customer',null,p_user_id,p_guest_session,p_auth_session_id,null,null,p_attempt_id);
  return a;
end $$;
create function public.commerce_prepare_context_checkout(p_quote_id uuid,p_frontend_origin text,p_is_test boolean,
  p_stripe_account_id text,p_profile_ref text,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare prepared jsonb; result jsonb;
begin
  perform private.assert_commerce_new_execution(p_is_test,p_stripe_account_id,p_profile_ref);
  if not p_is_test and (p_frontend_origin !~ '^https://' or p_frontend_origin ~* '(localhost|127[.]|[.]test($|:)|[.]invalid($|:))')
    then raise exception 'Production checkout requires a public HTTPS origin'; end if;
  prepared:=private.commerce_order_from_quote_context_core(null,p_quote_id,p_user_id,p_guest_session,p_is_test,
    p_user_id,p_guest_session,p_auth_session_id,'customer',p_stripe_account_id,p_profile_ref);
  result:=private.commerce_prepare_checkout_attempt_context_core(null,(prepared->>'order_id')::uuid,p_frontend_origin,
    p_user_id,p_guest_session,p_auth_session_id,'customer');
  return result;
end $$;
create function public.commerce_store_context_checkout_params(p_attempt_id uuid,p_params jsonb,p_stripe_account_id text,p_profile_ref text,
  p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts;
begin
  a:=private.commerce_owned_context_attempt(p_attempt_id,p_stripe_account_id,p_profile_ref,p_user_id,p_guest_session,p_auth_session_id);
  perform private.assert_commerce_new_execution(a.is_test,p_stripe_account_id,p_profile_ref);
  return private.commerce_store_checkout_params_context_core(null,p_attempt_id,p_params,p_user_id,p_guest_session,p_auth_session_id,'customer');
end $$;
create function public.commerce_claim_context_checkout(p_attempt_id uuid,p_stripe_account_id text,p_profile_ref text,
  p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts;
begin
  a:=private.commerce_owned_context_attempt(p_attempt_id,p_stripe_account_id,p_profile_ref,p_user_id,p_guest_session,p_auth_session_id);
  perform private.assert_commerce_new_execution(a.is_test,p_stripe_account_id,p_profile_ref);
  return private.commerce_claim_checkout_attempt_context_core(null,p_attempt_id,p_user_id,p_guest_session,p_auth_session_id,'customer');
end $$;
create function public.commerce_context_checkout_unknown(p_attempt_id uuid,p_error_code text,p_stripe_account_id text,p_profile_ref text,
  p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts;
begin
  a:=private.commerce_owned_context_attempt(p_attempt_id,p_stripe_account_id,p_profile_ref,p_user_id,p_guest_session,p_auth_session_id);
  return private.commerce_checkout_unknown_context_core(null,p_attempt_id,p_error_code,p_user_id,p_guest_session,p_auth_session_id,'customer');
end $$;

create function public.commerce_bind_context_session(p_attempt_id uuid,p_session_id text,p_stripe_account_id text,p_profile_ref text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts; o public.orders; s public.commerce_payment_sessions;
begin
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id;
  if not found then raise exception 'Unknown context checkout'; end if;
  select * into strict o from public.orders where id=a.order_id for update;
  select * into strict a from public.commerce_checkout_attempts where id=p_attempt_id for update;
  perform private.assert_commerce_context(a.is_test,p_stripe_account_id,p_profile_ref);
  if a.stripe_account_id is distinct from p_stripe_account_id or a.stripe_profile_ref is distinct from p_profile_ref
    or o.stripe_account_id is distinct from p_stripe_account_id or o.stripe_profile_ref is distinct from p_profile_ref
    or a.is_test is distinct from o.is_test or a.state not in('creating','unknown') or a.first_requested_at is null
    or p_session_id is null or not ((a.is_test and p_session_id ~ '^cs_test_[A-Za-z0-9_]{1,240}$')
      or (not a.is_test and p_session_id ~ '^cs_live_[A-Za-z0-9_]{1,240}$'))
    then raise exception 'Claimed matching context checkout required'; end if;
  select * into s from public.commerce_payment_sessions where attempt_id=a.id;
  if found then
    if s.session_id<>p_session_id or s.stripe_account_id<>p_stripe_account_id or s.stripe_profile_ref<>p_profile_ref
      or s.is_test is distinct from a.is_test then raise exception 'Session binding conflict'; end if;
    return to_jsonb(s);
  end if;
  insert into public.commerce_payment_sessions(attempt_id,stripe_account_id,stripe_profile_ref,is_test,session_id)
    values(a.id,p_stripe_account_id,p_profile_ref,a.is_test,p_session_id) returning * into s;
  update public.commerce_checkout_attempts set session_id=p_session_id where id=a.id;
  return to_jsonb(s);
end $$;

-- Existing product-level queue must not intercept the dedicated quoted path.
do $queue$ declare d text; a text:='begin'; begin
  select pg_get_functiondef('private.queue_supplier_order()'::regprocedure) into d;
  if (length(d)-length(replace(d,a,'')))/length(a)<>1 then raise exception 'Legacy supplier queue guard drift'; end if;
  execute replace(d,a,a||E'\n  '||'if new.commerce_quote_id is not null and not new.is_test then return new; end if;');
end $queue$;

create function public.commerce_record_context_event(p_event_id text,p_event_type text,p_object_id text,p_is_test boolean,
  p_stripe_account_id text,p_profile_ref text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare e public.commerce_payment_events;
begin
  perform private.assert_commerce_context(p_is_test,p_stripe_account_id,p_profile_ref);
  if p_event_id is null or p_event_id !~ '^evt_[A-Za-z0-9_]{1,240}$'
    or p_event_type is null or p_event_type !~ '^[a-z][a-z0-9_.]{1,119}$'
    or p_object_id is null or p_object_id !~ '^(cs_test_|cs_live_|pi_|ch_|re_)[A-Za-z0-9_]{1,240}$'
    or (p_object_id like 'cs_test_%' and not p_is_test) or (p_object_id like 'cs_live_%' and p_is_test)
    then raise exception 'Invalid context event receipt'; end if;
  -- Same immutable receipt identity is shared with successful settlement.
  if not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||p_is_test::text||':'||p_event_id,0))
    then raise exception 'Event receipt busy; retry event'; end if;
  select * into e from public.commerce_payment_events where stripe_account_id=p_stripe_account_id and is_test=p_is_test and event_id=p_event_id;
  if found then
    if e.event_type<>p_event_type or e.object_id<>p_object_id or e.stripe_profile_ref<>p_profile_ref
      then raise exception 'Event receipt identity conflict'; end if;
    return jsonb_build_object('received',true,'event_recorded',true,'duplicate',true,'requires_reconciliation',e.requires_reconciliation,'is_test',p_is_test);
  end if;
  insert into public.commerce_payment_events(stripe_account_id,is_test,event_id,stripe_profile_ref,event_type,object_id)
    values(p_stripe_account_id,p_is_test,p_event_id,p_profile_ref,p_event_type,p_object_id);
  return jsonb_build_object('received',true,'event_recorded',true,'duplicate',false,'requires_reconciliation',true,'is_test',p_is_test);
end $$;

create function public.commerce_settle_context_checkout(p_event_id text,p_event_type text,p_session jsonb,p_destination_matches boolean,
  p_stripe_account_id text,p_profile_ref text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts; o public.orders; oldevent public.commerce_payment_events;
  cl public.commerce_order_lines; q public.commerce_quotes; n integer; seen boolean;
  inventory_ready boolean:=true; inventory_available boolean:=true; reasons text[]; r record;
begin
  if p_event_id is null or p_event_id !~ '^evt_[A-Za-z0-9_]{1,240}$' or p_event_type is null
    or p_event_type not in('checkout.session.completed','checkout.session.async_payment_succeeded')
    or p_destination_matches is null or jsonb_typeof(p_session) is distinct from 'object'
    then raise exception 'Invalid context payment event'; end if;
  select * into a from public.commerce_checkout_attempts where id=(p_session->'metadata'->>'attempt_id')::uuid;
  if not found then raise exception 'Unknown context checkout attempt'; end if;
  select * into o from public.orders where id=a.order_id for update;
  perform private.assert_commerce_context(a.is_test,p_stripe_account_id,p_profile_ref);
  if not found or a.stripe_account_id is distinct from p_stripe_account_id or o.stripe_account_id is distinct from p_stripe_account_id
    or a.stripe_profile_ref is distinct from p_profile_ref or o.stripe_profile_ref is distinct from p_profile_ref
    or a.is_test is distinct from o.is_test or o.commerce_quote_id is distinct from a.commerce_quote_id
    or a.state not in('creating','unknown') or a.first_requested_at is null
    or p_session->>'object' is distinct from 'checkout.session' or p_session->>'mode' is distinct from 'payment'
    or p_session->'livemode' is distinct from to_jsonb(not a.is_test) or p_session->>'status' is distinct from 'complete'
    or p_session->>'payment_status' is distinct from 'paid'
    or p_session->>'currency' is distinct from 'eur' or o.currency<>'EUR'
    or p_session->>'client_reference_id' is distinct from o.id::text
    or p_session->'metadata'->>'order_id' is distinct from o.id::text
    or p_session->'metadata'->>'quote_id' is distinct from a.commerce_quote_id::text
    or p_session->'amount_total' is distinct from to_jsonb(o.total_cents)
    or a.total_cents<>o.total_cents or p_session->'amount_subtotal' is distinct from to_jsonb(o.subtotal_cents)
    or p_session->'expires_at' is distinct from to_jsonb(a.expires_at)
    or p_session->'total_details'->'amount_shipping' is distinct from to_jsonb(o.shipping_amount_cents)
    or p_session->'total_details'->'amount_discount' is distinct from '0'::jsonb
    or p_session->'total_details'->'amount_tax' is distinct from '0'::jsonb
    or p_session->'automatic_tax'->'enabled' is distinct from 'false'::jsonb
    or p_session->>'payment_intent' is null or p_session->>'payment_intent' !~ '^pi_[A-Za-z0-9_]{1,240}$'
    then raise exception 'Invalid context payment snapshot'; end if;
  -- Bind even when the SDK response was lost, or source rows/approval changed.
  perform public.commerce_bind_context_session(a.id,p_session->>'id',p_stripe_account_id,p_profile_ref);
  if not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||a.is_test::text||':'||p_event_id,0))
    or not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||a.is_test::text||':'||(p_session->>'payment_intent'),0))
    then raise exception 'Payment identity busy; retry event'; end if;
  select * into oldevent from public.commerce_payment_events where stripe_account_id=p_stripe_account_id and is_test=a.is_test and event_id=p_event_id;
  if found then
    if oldevent.attempt_id is distinct from a.id or oldevent.object_id<>p_session->>'id'
      or oldevent.payment_intent_id is distinct from p_session->>'payment_intent' or oldevent.event_type<>p_event_type
      or oldevent.stripe_profile_ref<>p_profile_ref or oldevent.destination_matches is distinct from p_destination_matches
      or oldevent.amount_cents is distinct from o.total_cents or oldevent.requires_reconciliation
      then raise exception 'Context event identity conflict'; end if;
    return jsonb_build_object('order_id',o.id,'duplicate',true,'is_test',a.is_test);
  end if;
  if exists(select 1 from public.commerce_payment_events where stripe_account_id=p_stripe_account_id and is_test=a.is_test and
      ((attempt_id=a.id and payment_intent_id<>p_session->>'payment_intent')
      or (attempt_id<>a.id and payment_intent_id=p_session->>'payment_intent')))
    then raise exception 'Payment intent already bound to another context order'; end if;
  seen:=exists(select 1 from public.commerce_payment_events where attempt_id=a.id and not requires_reconciliation);
  insert into public.commerce_payment_events(stripe_account_id,is_test,event_id,stripe_profile_ref,event_type,object_id,
    attempt_id,payment_intent_id,amount_cents,destination_matches,requires_reconciliation)
    values(p_stripe_account_id,a.is_test,p_event_id,p_profile_ref,p_event_type,p_session->>'id',a.id,
      p_session->>'payment_intent',o.total_cents,p_destination_matches,false);
  if seen then return jsonb_build_object('order_id',o.id,'duplicate',true,'is_test',a.is_test); end if;
  if o.payment_status not in('unpaid','failed') then raise exception 'Unexpected order financial state'; end if;
  select * into strict q from public.commerce_quotes where id=a.commerce_quote_id;
  select count(*) into n from public.commerce_order_lines where order_id=o.id;
  if n<1 or n<>(select count(*) from public.order_items where order_id=o.id)
    or exists(select 1 from public.commerce_order_lines where order_id=o.id and quote_id<>q.id)
    then raise exception 'Incomplete immutable order lines'; end if;
  -- Payment truth is never rejected because current stock changed after claim.
  -- Hold fulfillment for reconciliation instead. Sandbox never mutates stock.
  if not a.is_test then
    for r in select variant_id,sum(quantity)::integer qty from public.order_items where order_id=o.id group by variant_id order by variant_id loop
      perform 1 from public.product_variants where id=r.variant_id and stock>=r.qty for update;
      if not found then inventory_ready:=false; end if;
    end loop;
    inventory_available:=inventory_ready;
    if inventory_ready and p_destination_matches and o.status<>'cancelled' then
      for r in select variant_id,sum(quantity)::integer qty from public.order_items where order_id=o.id group by variant_id order by variant_id loop
        update public.product_variants set stock=stock-r.qty where id=r.variant_id;
      end loop;
    else inventory_ready:=false; end if;
  end if;
  update public.orders set payment_status='paid',status=case when status='cancelled' then status else 'paid'::public.order_status end,
    fulfillment_status='requires_review',stripe_session_id=p_session->>'id',stripe_payment_intent_id=p_session->>'payment_intent',
    customer_email=coalesce(customer_email,case when length(p_session->'customer_details'->>'email')<=254
      and p_session->'customer_details'->>'email' ~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$'
      then p_session->'customer_details'->>'email' end),
    stock_applied_at=case when not a.is_test and inventory_ready then clock_timestamp() else null end,
    paid_at=clock_timestamp() where id=o.id;
  if not a.is_test and inventory_ready then
    update public.commerce_variant_reservations set state='consumed' where attempt_id=a.id and state='held';
  end if;
  -- Every paid group gets its responsible agent, including incident dossiers.
  -- A held dossier never grants purchase, dispatch or inventory consumption.
  reasons:=array['fulfillment_approval_required'];
  if not p_destination_matches then reasons:=reasons||'destination_mismatch'::text; end if;
  if not inventory_available then reasons:=reasons||'inventory_unavailable'::text; end if;
  if o.status='cancelled' then reasons:=reasons||'order_cancelled'::text; end if;
    for cl in select distinct on(group_key) * from public.commerce_order_lines where order_id=o.id order by group_key,id loop
      insert into public.commerce_fulfillment_tasks(order_id,attempt_id,group_key,supplier_id,agent_id,offer_id,shipping_rate_id,variant_id,supplier_sku,quantity,snapshot,is_test,review_reasons)
      values(o.id,a.id,cl.group_key,(cl.supplier_snapshot->>'id')::uuid,(cl.agent_snapshot->>'id')::uuid,
        (cl.offer_snapshot->>'id')::uuid,(cl.rate_snapshot->>'id')::uuid,(cl.group_snapshot->>'variant_id')::uuid,
        cl.offer_snapshot->>'supplier_sku',
        (select sum((x->>'quantity')::integer) from jsonb_array_elements(cl.group_snapshot->'lines') x),
        jsonb_build_object('group',cl.group_snapshot,'offer',cl.offer_snapshot,'rate',cl.rate_snapshot,
          'agent',cl.agent_snapshot,'supplier',cl.supplier_snapshot,'is_test',a.is_test,'external_send_allowed',false),a.is_test,reasons);
    end loop;
  insert into public.admin_audit(action,resource,metadata) values('commerce.context.payment',o.id::text,
    jsonb_build_object('is_test',a.is_test,'event_id',p_event_id,'destination_matches',p_destination_matches,'inventory_ready',inventory_ready));
  return jsonb_build_object('order_id',o.id,'duplicate',false,'is_test',a.is_test,
    'fulfillment_held',not p_destination_matches or o.status='cancelled' or not inventory_ready);
end $$;

-- Only paid, stock-applied production reservations can be consumed. Test
-- reservations retain their original release-only transition contract.
do $consume$ declare d text; a text; b text; begin
  select replace(pg_get_functiondef('private.guard_commerce_attempt_history()'::regprocedure),chr(13),'') into d;
  a:=$a$or old.state<>'held' or new.state<>'released' or not exists(select 1 from public.commerce_checkout_attempts
          where id=old.attempt_id and state='cancelled' and first_requested_at is null)$a$;
  b:=$a$or old.state<>'held' or not (
      (new.state='released' and exists(select 1 from public.commerce_checkout_attempts
        where id=old.attempt_id and state='cancelled' and first_requested_at is null))
      or (new.state='consumed' and not new.is_test and exists(select 1 from public.commerce_checkout_attempts ca
        join public.orders co on co.id=ca.order_id where ca.id=new.attempt_id and not ca.is_test
          and co.payment_status='paid' and co.stock_applied_at is not null)))$a$;
  a:=replace(a,chr(13),'');
  if strpos(d,a)=0 then raise exception 'Production reservation consume anchor drift'; end if;
  execute replace(d,a,b);
end $consume$;

-- Old test-only RPCs must never process a newly explicit execution profile.
-- Their prior NULL-context and account-preparation behavior stays unchanged.
do $legacy_guard$ declare r record; d text; a text; begin
  for r in select * from(values
    ('commerce_claim_checkout_attempt_core','uuid,uuid,uuid,text,uuid,text',
      'select * into strict a from public.commerce_checkout_attempts where id=p_attempt_id for update;'),
    ('commerce_bind_test_session','uuid,text','select * into a from public.commerce_checkout_attempts where id=p_attempt_id;'),
    ('commerce_settle_test_checkout','text,text,jsonb,boolean','select * into a from public.commerce_checkout_attempts where id=(p_session->''metadata''->>''attempt_id'')::uuid;')
  ) x(name,types,anchor) loop
    select pg_get_functiondef(((case when r.name='commerce_claim_checkout_attempt_core' then 'private.' else 'public.' end)||r.name||'('||r.types||')')::regprocedure) into d;
    if strpos(d,r.anchor)=0 then raise exception 'Legacy profile isolation drift'; end if;
    execute replace(d,r.anchor,r.anchor||E'\n'||$a$  if a.stripe_profile_ref is not null then raise exception 'Explicit profile requires context checkout workflow'; end if;$a$);
  end loop;
end $legacy_guard$;

-- Namespace actual order identities consistently with the account-bound event
-- journal; legacy NULL-account uniqueness and lookup semantics remain intact.
alter table public.orders drop constraint orders_stripe_session_id_key;
alter table public.orders drop constraint orders_stripe_payment_intent_id_key;
create unique index orders_legacy_stripe_session_id_unique on public.orders(stripe_session_id) where stripe_account_id is null;
create unique index orders_legacy_stripe_payment_intent_id_unique on public.orders(stripe_payment_intent_id) where stripe_account_id is null;
create unique index orders_context_stripe_session_id_unique on public.orders(stripe_account_id,is_test,stripe_session_id) where stripe_account_id is not null;
create unique index orders_context_stripe_payment_intent_id_unique on public.orders(stripe_account_id,is_test,stripe_payment_intent_id) where stripe_account_id is not null;
do $refund_scope$ declare d text; a text:='where stripe_payment_intent_id=p_payment_intent for update;'; begin
  select pg_get_functiondef('public.record_order_refund(text,integer)'::regprocedure) into d;
  if (length(d)-length(replace(d,a,'')))/length(a)<>1 then raise exception 'Legacy refund account isolation drift'; end if;
  execute replace(d,a,'where stripe_payment_intent_id=p_payment_intent and stripe_account_id is null for update;');
end $refund_scope$;

-- Global legacy refund receipts may only observe NULL-account history. They
-- cannot project a matching opaque PI into another authenticated account.
do $legacy_refunds$ declare d text; a text; n integer; begin
  select pg_get_functiondef('public.commerce_record_test_refund(jsonb)'::regprocedure) into d;
  a:='where stripe_payment_intent_id=r.payment_intent_id';
  n:=(length(d)-length(replace(d,a,'')))/length(a);
  if n<>2 then raise exception 'Legacy test refund account lookup drift'; end if;
  execute replace(d,a,a||' and stripe_account_id is null');
  select pg_get_functiondef('private.commerce_project_test_refunds(uuid)'::regprocedure) into d;
  a:='if not found or not o.is_test or o.commerce_quote_id is null then';
  if strpos(d,a)=0 then raise exception 'Legacy test refund projection drift'; end if;
  execute replace(d,a,'if not found or not o.is_test or o.commerce_quote_id is null or o.stripe_account_id is not null then');
  select pg_get_functiondef('private.commerce_test_refund_hold(uuid)'::regprocedure) into d;
  a:='from public.orders o where o.id=p_order_id';
  if strpos(d,a)=0 then raise exception 'Legacy refund hold scope drift'; end if;
  execute replace(d,a,a||' and o.stripe_account_id is null');
end $legacy_refunds$;

create function public.commerce_context_checkout_enabled(p_is_test boolean,p_stripe_account_id text,p_profile_ref text)
returns boolean language plpgsql security invoker set search_path='' as $$
begin
  perform private.assert_commerce_new_execution(p_is_test,p_stripe_account_id,p_profile_ref);
  return true;
exception when others then return false;
end $$;

do $privileges$ declare fn regprocedure; begin
  for fn in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace where
    (n.nspname='private' and (p.proname like '%_context_core' or p.proname in('assert_commerce_context','assert_commerce_new_execution',
      'guard_commerce_context_history','commerce_owned_context_attempt','assert_commerce_context_authority','assert_commerce_context_cart_purchase')))
    or (n.nspname='public' and p.proname in('commerce_prepare_context_checkout','commerce_store_context_checkout_params',
      'commerce_claim_context_checkout','commerce_context_checkout_unknown','commerce_bind_context_session',
      'commerce_record_context_event','commerce_settle_context_checkout','commerce_context_checkout_enabled'))
  loop
    execute format('revoke all on function %s from public,anon,authenticated',fn);
    execute format('grant execute on function %s to service_role',fn);
  end loop;
end $privileges$;
commit;
