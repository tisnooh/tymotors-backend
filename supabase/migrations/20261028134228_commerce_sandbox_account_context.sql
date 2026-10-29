-- Persistent SANDBOX preparation context only. No account authentication, live
-- checkout, provider request, financial settlement or historical backfill.
begin;

alter table public.orders add column stripe_account_id text;
alter table public.commerce_checkout_attempts add column stripe_account_id text;
alter table public.orders add constraint orders_stripe_account_context check (
  stripe_account_id is null or (stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$'
    and is_test and commerce_quote_id is not null)
);
alter table public.commerce_checkout_attempts add constraint commerce_attempt_account_context check (
  stripe_account_id is null or (stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$' and is_test)
);

create function private.guard_commerce_account_context() returns trigger
language plpgsql security invoker set search_path='' as $$
declare o public.orders;
begin
  if tg_op='UPDATE' then
    if new.stripe_account_id is distinct from old.stripe_account_id
      or (old.stripe_account_id is not null and new.is_test is distinct from old.is_test)
      then raise exception 'Checkout account and mode are immutable; historical context cannot be inferred'; end if;
  elsif tg_table_name='commerce_checkout_attempts' then
    select * into o from public.orders where id=new.order_id;
    if not found or new.is_test is distinct from o.is_test then
      raise exception 'Checkout account requires matching order mode'; end if;
    if new.stripe_account_id is null then new.stripe_account_id:=o.stripe_account_id;
    elsif new.stripe_account_id is distinct from o.stripe_account_id then
      raise exception 'Checkout account does not match immutable order'; end if;
  end if;
  -- A future account-aware gateway/receipt path needs its OWN reviewed contract.
  -- Old claim RPCs cannot accidentally create a provider session from this draft.
  if tg_table_name='commerce_checkout_attempts' then
    if new.stripe_account_id is not null
      and (new.first_requested_at is not null or new.state in ('creating','unknown','session_created'))
      then raise exception 'Account-bound provider creation is not approved'; end if;
  end if;
  return new;
end $$;
create trigger commerce_order_account_context before insert or update on public.orders
  for each row execute function private.guard_commerce_account_context();
-- Alphabetically before commerce_attempt_history: copy account before the
-- existing immutable snapshot guard runs. No existing trigger is disabled.
create trigger commerce_account_context_history before insert or update on public.commerce_checkout_attempts
  for each row execute function private.guard_commerce_account_context();

-- Keep ONE authoritative order-from-quote implementation. Add a trailing
-- account argument to the actual installed core, preserving every authorization,
-- cart/quote/source/image check and lock. The old signature becomes a NULL-account
-- compatibility wrapper. No historical params/hash/idempotency data is touched.
do $factor$
declare definition text; anchor text; replacement text; n integer;
begin
  select pg_get_functiondef('private.commerce_order_from_quote_core(uuid,uuid,uuid,text,boolean,uuid,text,uuid,text)'::regprocedure)
    into definition;
  anchor:='p_principal_mode text)';
  n:=(length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if n<>1 then raise exception 'Review account-context core signature drift'; end if;
  definition:=replace(definition,anchor,'p_principal_mode text, p_stripe_account_id text)');
  anchor:='is_test,commerce_quote_id)';
  n:=(length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if n<>1 then raise exception 'Review quoted-order account column drift'; end if;
  definition:=replace(definition,anchor,'is_test,commerce_quote_id,stripe_account_id)');
  anchor:='true,true,q.id)';
  n:=(length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if n<>1 then raise exception 'Review quoted-order account value drift'; end if;
  definition:=replace(definition,anchor,'true,true,q.id,p_stripe_account_id)');
  anchor:=$a$if not o.is_test then raise exception 'Existing quote order is not a test order'; end if;$a$;
  n:=(length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if n<>1 then raise exception 'Review quoted-order account replay drift'; end if;
  replacement:=anchor||E'\n    '||$a$if o.stripe_account_id is distinct from p_stripe_account_id then raise exception 'Existing quoted order account mismatch'; end if;$a$;
  execute replace(definition,anchor,replacement);
end $factor$;

create or replace function private.commerce_order_from_quote_core(
  p_actor uuid,p_quote_id uuid,p_user_id uuid,p_guest_session text,p_is_test boolean,
  p_customer_user_id uuid,p_customer_guest_session text,p_auth_session_id uuid,p_principal_mode text)
returns jsonb language sql security invoker set search_path='' as $$
  select private.commerce_order_from_quote_core(p_actor,p_quote_id,p_user_id,p_guest_session,p_is_test,
    p_customer_user_id,p_customer_guest_session,p_auth_session_id,p_principal_mode,null);
$$;

create function public.commerce_prepare_account_bound_test_checkout(
  p_actor uuid,p_quote_id uuid,p_stripe_account_id text,p_frontend_origin text,
  p_user_id uuid default null,p_guest_session text default null)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare prepared jsonb; context jsonb; a public.commerce_checkout_attempts;
begin
  perform private.assert_admin(p_actor);
  if p_stripe_account_id is null or p_stripe_account_id !~ '^acct_[A-Za-z0-9]{1,240}$'
    then raise exception 'Explicit sandbox account context required; not an authentication'; end if;
  prepared:=private.commerce_order_from_quote_core(p_actor,p_quote_id,p_user_id,p_guest_session,true,
    null,null,null,'admin',p_stripe_account_id);
  context:=private.commerce_prepare_checkout_attempt_core(p_actor,(prepared->>'order_id')::uuid,
    p_frontend_origin,null,null,null,'admin');
  a:=jsonb_populate_record(null::public.commerce_checkout_attempts,context->'attempt');
  if a.stripe_account_id is distinct from p_stripe_account_id or a.is_test is distinct from true
    or a.state not in ('drafting','ready') or a.first_requested_at is not null or a.session_id is not null then
    raise exception 'Unclaimed sandbox account preparation required'; end if;
  return context||jsonb_build_object('is_test',true,'account_authenticated',false,
    'provider_creation_authorized',false,'publication_authorized',false);
end $$;

revoke all on function private.guard_commerce_account_context(),
  private.commerce_order_from_quote_core(uuid,uuid,uuid,text,boolean,uuid,text,uuid,text,text),
  public.commerce_prepare_account_bound_test_checkout(uuid,uuid,text,text,uuid,text)
  from public,anon,authenticated;
grant execute on function private.guard_commerce_account_context(),
  private.commerce_order_from_quote_core(uuid,uuid,uuid,text,boolean,uuid,text,uuid,text,text),
  public.commerce_prepare_account_bound_test_checkout(uuid,uuid,text,text,uuid,text)
  to service_role;
commit;
