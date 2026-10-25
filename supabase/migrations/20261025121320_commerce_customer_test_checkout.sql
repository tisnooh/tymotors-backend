-- Owner-scoped sandbox checkout. No public grants, real stock, or live payment.
-- Existing admin implementation is factored, not relaxed or duplicated.
begin;

create function private.assert_commerce_customer_identity(p_user_id uuid,p_guest_session text,p_auth_session_id uuid)
returns void language plpgsql security invoker set search_path='' as $$
begin
  if p_user_id is not null then
    if p_guest_session is not null or p_auth_session_id is null
      or p_user_id='00000000-0000-0000-0000-000000000000'::uuid
      or not exists(select 1 from public.profiles where id=p_user_id)
      or public.is_auth_session_active(p_auth_session_id,p_user_id) is distinct from true
      then raise exception 'Active authenticated checkout owner required'; end if;
  elsif p_auth_session_id is not null or p_guest_session is null
    or p_guest_session !~ '^[A-Za-z0-9_-]{16,128}$' then
    raise exception 'Unambiguous checkout guest owner required';
  end if;
end $$;

create function private.assert_commerce_checkout_authority(p_mode text,p_actor uuid,p_user_id uuid,p_guest_session text,
  p_auth_session_id uuid,p_quote_id uuid,p_order_id uuid,p_attempt_id uuid) returns void
language plpgsql security invoker set search_path='' as $$
declare q public.commerce_quotes; o public.orders; aid uuid;
begin
  if p_mode='admin' then perform private.assert_admin(p_actor); return; end if;
  if p_mode is distinct from 'customer' or p_actor is not null then raise exception 'Invalid checkout authority'; end if;
  perform private.assert_commerce_customer_identity(p_user_id,p_guest_session,p_auth_session_id);
  if p_attempt_id is not null then
    select order_id into aid from public.commerce_checkout_attempts where id=p_attempt_id;
    if not found or (p_order_id is not null and p_order_id<>aid) then raise exception 'Checkout owner mismatch'; end if;
    p_order_id:=aid;
  end if;
  if p_order_id is not null then
    select * into o from public.orders where id=p_order_id;
    if not found or not o.is_test or o.commerce_quote_id is null
      or (p_quote_id is not null and p_quote_id<>o.commerce_quote_id)
      or o.user_id is distinct from p_user_id or o.guest_session_id is distinct from p_guest_session
      then raise exception 'Checkout owner mismatch'; end if;
    p_quote_id:=o.commerce_quote_id;
  end if;
  select * into q from public.commerce_quotes where id=p_quote_id;
  if not found or q.owner_user_id is distinct from p_user_id or q.owner_guest_session is distinct from p_guest_session
    then raise exception 'Checkout owner mismatch'; end if;
end $$;

-- Call under the existing cart -> quote -> order lock sequence. All public
-- customer/admin preparation paths serialize on the SAME cart row. Never take
-- another order row lock here (settlement uses an order-first lock sequence).
create function private.assert_commerce_cart_purchase(p_quote_id uuid,p_order_id uuid default null) returns void
language plpgsql security invoker set search_path='' as $$
declare q public.commerce_quotes; prior record;
begin
  select * into q from public.commerce_quotes where id=p_quote_id;
  if not found or q.cart_id is null then raise exception 'Quote cart is missing'; end if;
  for prior in
    select o.id,o.status,o.payment_status,o.refunded_amount_cents,
      a.id attempt_id,a.state attempt_state,a.first_requested_at
    from public.orders o join public.commerce_quotes oldq on oldq.id=o.commerce_quote_id
    left join public.commerce_checkout_attempts a on a.order_id=o.id
    where oldq.cart_id=q.cart_id and (p_order_id is null or o.id<>p_order_id)
    order by o.created_at,o.id
  loop
    if prior.payment_status='paid' and prior.status<>'refunded' and prior.refunded_amount_cents=0 then
      if exists(select 1 from public.commerce_order_lines oldline,
        jsonb_array_elements(q.payload->'groups') g,lateral jsonb_array_elements(g->'lines') l
        where oldline.order_id=prior.id and oldline.source_cart_item_id=(l->>'cart_item_id')::uuid)
        then raise exception 'Cart lines already purchased; explicit cart review required'; end if;
      -- Paid truth must not be confused with the deliberately retained
      -- creating/unknown attempt or conservative TEST reservation lifecycle.
      continue;
    end if;
    if prior.status='refunded' or prior.payment_status='refunded' or prior.refunded_amount_cents<>0 then
      raise exception 'Checkout cart requires financial review';
    end if;
    if prior.first_requested_at is null and
      ((prior.attempt_state='cancelled') or (prior.attempt_id is null and prior.status='cancelled'))
      and prior.payment_status in ('unpaid','failed') then continue; end if;
    -- No timeout, local expiration, new request key or modified basket proves
    -- that a previously claimed provider request cannot still receive funds.
    raise exception 'Another checkout purchase is active for cart';
  end loop;
end $$;

create function private.commerce_checkout_audit_principal(p_mode text,p_user_id uuid) returns jsonb
language sql immutable security invoker set search_path='' as $$
  select jsonb_strip_nulls(jsonb_build_object('authority',case when p_mode='admin' then 'admin'
    when p_user_id is not null then 'customer_user' else 'customer_guest' end,
    'actor_user_id',case when p_mode='customer' then p_user_id else null end));
$$;

-- A detached FK may still become NULL on account/cart deletion. The immutable
-- quote owner remains authoritative; no owner can ever be reassigned to another
-- user/guest. Do not break the existing ON DELETE SET NULL account lifecycle.
create function private.guard_commerce_order_owner() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if old.commerce_quote_id is not null and (
    new.guest_session_id is distinct from old.guest_session_id
    or (new.user_id is distinct from old.user_id and new.user_id is not null)
    or (new.cart_id is distinct from old.cart_id and new.cart_id is not null))
    then raise exception 'Quoted order owner cannot be reassigned'; end if;
  return new;
end $$;
create trigger commerce_order_owner_immutable before update on public.orders
  for each row execute function private.guard_commerce_order_owner();
create index orders_commerce_cart_lookup on public.orders(cart_id) where commerce_quote_id is not null;

-- Preserve all original guards (including the additive image-rights amendments)
-- by cloning the ACTUAL installed implementation into reviewed private cores.
-- Exact signature/body anchors are counted. Unexpected migration drift aborts
-- the transaction rather than silently dropping an authorization/validation.
do $factor$
declare r record; definition text; auth_call text; expected integer; actual integer; audit_anchor text;
begin
  for r in select * from (values
    ('private','commerce_attempt_order','uuid,uuid','p_order_id uuid',2,null::text),
    ('public','commerce_order_from_quote','uuid,uuid,uuid,text,boolean','p_is_test boolean',2,$a$jsonb_build_object('quote_id',q.id,'is_test',true)$a$),
    ('public','commerce_prepare_checkout_attempt','uuid,uuid,text','p_frontend_origin text',0,$a$jsonb_build_object('order_id',p_order_id,'is_test',true)$a$),
    ('public','commerce_store_checkout_params','uuid,uuid,jsonb','p_params jsonb',0,$a$jsonb_build_object('params_hash',a.params_hash)$a$),
    ('public','commerce_claim_checkout_attempt','uuid,uuid','p_attempt_id uuid',0,$a$jsonb_build_object('is_test',true)$a$),
    ('public','commerce_checkout_unknown','uuid,uuid,text','p_error_code text',2,$a$jsonb_build_object('code',p_error_code)$a$),
    ('public','commerce_cancel_checkout_draft','uuid,uuid','p_attempt_id uuid',2,$a$jsonb_build_object('is_test',true)$a$)
  ) as x(source_schema,name,types,last_argument,auth_count,audit_anchor)
  loop
    select pg_get_functiondef((r.source_schema||'.'||r.name||'('||r.types||')')::regprocedure) into definition;
    if strpos(definition,r.source_schema||'.'||r.name||'(')=0
      or strpos(definition,r.last_argument||')')=0 then raise exception 'Checkout core signature drift'; end if;
    actual:=(length(definition)-length(replace(definition,'perform private.assert_admin(p_actor);','')))
      /length('perform private.assert_admin(p_actor);');
    if actual<>r.auth_count then raise exception 'Checkout authorization drift for %',r.name; end if;
    definition:=replace(definition,r.source_schema||'.'||r.name||'(','private.'||r.name||'_core(');
    definition:=replace(definition,r.last_argument||')',r.last_argument||', p_customer_user_id uuid, p_customer_guest_session text, p_auth_session_id uuid, p_principal_mode text)');
    if r.name='commerce_order_from_quote' then
      auth_call:='perform private.assert_commerce_checkout_authority(p_principal_mode,p_actor,p_customer_user_id,p_customer_guest_session,p_auth_session_id,p_quote_id,null,null);';
      if strpos(definition,$a$if q.state<>'ready' or q.expires_at<=clock_timestamp()$a$)=0 then raise exception 'Checkout quote creation anchor drift'; end if;
      definition:=replace(definition,$a$if q.state<>'ready' or q.expires_at<=clock_timestamp()$a$,
        'perform private.assert_commerce_cart_purchase(q.id,null);'||E'\n  '||$a$if q.state<>'ready' or q.expires_at<=clock_timestamp()$a$);
    elsif r.name='commerce_attempt_order' then
      auth_call:='perform private.assert_commerce_checkout_authority(p_principal_mode,p_actor,p_customer_user_id,p_customer_guest_session,p_auth_session_id,null,p_order_id,null);';
      if strpos(definition,'perform private.lock_commerce_attempts();')=0 then raise exception 'Checkout attempt barrier drift'; end if;
      definition:=replace(definition,'perform private.lock_commerce_attempts();',
        'perform private.lock_commerce_attempts();'||E'\n  '||'perform private.assert_commerce_cart_purchase(o.commerce_quote_id,o.id);');
    else
      auth_call:='perform private.assert_commerce_checkout_authority(p_principal_mode,p_actor,p_customer_user_id,p_customer_guest_session,p_auth_session_id,null,null,p_attempt_id);';
    end if;
    definition:=replace(definition,'perform private.assert_admin(p_actor);',auth_call);
    if r.name in ('commerce_prepare_checkout_attempt','commerce_store_checkout_params','commerce_claim_checkout_attempt') then
      expected:=1;
      actual:=(length(definition)-length(replace(definition,'private.commerce_attempt_order(p_actor,','')))/length('private.commerce_attempt_order(p_actor,');
      if actual<>expected then raise exception 'Checkout context core drift'; end if;
      definition:=replace(definition,'private.commerce_attempt_order(p_actor,p_order_id)',
        'private.commerce_attempt_order_core(p_actor,p_order_id,p_customer_user_id,p_customer_guest_session,p_auth_session_id,p_principal_mode)');
      definition:=replace(definition,'private.commerce_attempt_order(p_actor,a.order_id)',
        'private.commerce_attempt_order_core(p_actor,a.order_id,p_customer_user_id,p_customer_guest_session,p_auth_session_id,p_principal_mode)');
    end if;
    if r.audit_anchor is not null then
      actual:=(length(definition)-length(replace(definition,r.audit_anchor,'')))/length(r.audit_anchor);
      if actual<>1 then raise exception 'Checkout audit anchor drift for %',r.name; end if;
      definition:=replace(definition,r.audit_anchor,r.audit_anchor||'||private.commerce_checkout_audit_principal(p_principal_mode,p_customer_user_id)');
      -- The actor column is administrator-only in meaning, never a fictitious
      -- administrator or a guest bearer capability copied into logs.
      if strpos(definition,'values(p_actor,')=0 then raise exception 'Checkout audit actor drift'; end if;
      definition:=replace(definition,'values(p_actor,',$a$values(case when p_principal_mode='admin' then p_actor else null end,$a$);
    end if;
    if strpos(definition,'perform private.assert_admin(p_actor);')<>0
      or strpos(definition,'private.commerce_attempt_order(p_actor,')<>0 then raise exception 'Unfactored checkout authorization'; end if;
    execute definition;
  end loop;
end $factor$;

-- Historical administrator signatures and permissions stay unchanged.
create or replace function public.commerce_order_from_quote(p_actor uuid,p_quote_id uuid,p_user_id uuid,p_guest_session text,p_is_test boolean)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_order_from_quote_core(p_actor,p_quote_id,p_user_id,p_guest_session,p_is_test,null,null,null,'admin'); $$;
create or replace function private.commerce_attempt_order(p_actor uuid,p_order_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_attempt_order_core(p_actor,p_order_id,null,null,null,'admin'); $$;
create or replace function public.commerce_prepare_checkout_attempt(p_actor uuid,p_order_id uuid,p_frontend_origin text)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_prepare_checkout_attempt_core(p_actor,p_order_id,p_frontend_origin,null,null,null,'admin'); $$;
create or replace function public.commerce_store_checkout_params(p_actor uuid,p_attempt_id uuid,p_params jsonb)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_store_checkout_params_core(p_actor,p_attempt_id,p_params,null,null,null,'admin'); $$;
create or replace function public.commerce_claim_checkout_attempt(p_actor uuid,p_attempt_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_claim_checkout_attempt_core(p_actor,p_attempt_id,null,null,null,'admin'); $$;
create or replace function public.commerce_checkout_unknown(p_actor uuid,p_attempt_id uuid,p_error_code text)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_checkout_unknown_core(p_actor,p_attempt_id,p_error_code,null,null,null,'admin'); $$;
create or replace function public.commerce_cancel_checkout_draft(p_actor uuid,p_attempt_id uuid)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_cancel_checkout_draft_core(p_actor,p_attempt_id,null,null,null,'admin'); $$;

-- User/session identity MUST originate from the same JWT verified by Auth in
-- the backend. Guests supply only their existing high-entropy cart capability.
-- These functions are NEVER granted to a public/browser database role.
create function public.commerce_customer_order_from_quote(p_quote_id uuid,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_order_from_quote_core(null,p_quote_id,p_user_id,p_guest_session,true,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;
create function public.commerce_customer_prepare_checkout_attempt(p_order_id uuid,p_frontend_origin text,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_prepare_checkout_attempt_core(null,p_order_id,p_frontend_origin,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;
create function public.commerce_customer_store_checkout_params(p_attempt_id uuid,p_params jsonb,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_store_checkout_params_core(null,p_attempt_id,p_params,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;
create function public.commerce_customer_claim_checkout_attempt(p_attempt_id uuid,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_claim_checkout_attempt_core(null,p_attempt_id,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;
create function public.commerce_customer_checkout_unknown(p_attempt_id uuid,p_error_code text,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_checkout_unknown_core(null,p_attempt_id,p_error_code,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;
create function public.commerce_customer_cancel_checkout_draft(p_attempt_id uuid,p_user_id uuid default null,p_guest_session text default null,p_auth_session_id uuid default null)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_cancel_checkout_draft_core(null,p_attempt_id,p_user_id,p_guest_session,p_auth_session_id,'customer'); $$;

-- Revoke default PUBLIC execution for every new helper/wrapper in this lot.
do $privileges$ declare fn regprocedure;
begin
  for fn in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where (n.nspname='public' and p.proname in (
      'commerce_customer_order_from_quote','commerce_customer_prepare_checkout_attempt','commerce_customer_store_checkout_params',
      'commerce_customer_claim_checkout_attempt','commerce_customer_checkout_unknown','commerce_customer_cancel_checkout_draft'))
    or (n.nspname='private' and p.proname in (
      'assert_commerce_customer_identity','assert_commerce_checkout_authority','assert_commerce_cart_purchase',
      'commerce_checkout_audit_principal','guard_commerce_order_owner',
      'commerce_attempt_order_core','commerce_order_from_quote_core','commerce_prepare_checkout_attempt_core',
      'commerce_store_checkout_params_core','commerce_claim_checkout_attempt_core','commerce_checkout_unknown_core','commerce_cancel_checkout_draft_core'))
  loop
    execute format('revoke all on function %s from public,anon,authenticated',fn);
    execute format('grant execute on function %s to service_role',fn);
  end loop;
end $privileges$;
commit;
