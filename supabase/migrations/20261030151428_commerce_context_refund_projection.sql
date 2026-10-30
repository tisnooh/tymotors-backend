-- Account/profile-bound signed observations; no refund creation or automatic review release.
begin;
create table public.commerce_context_refund_events (
  stripe_account_id text not null check(stripe_account_id ~ '^acct_[A-Za-z0-9]{1,240}$'),
  is_test boolean not null,
  stripe_profile_ref text not null check(stripe_profile_ref ~ '^[A-Za-z0-9_-]{1,100}$'),
  event_id text not null check(event_id ~ '^evt_[A-Za-z0-9_]{1,240}$'),
  event_type text not null check(event_type in ('refund.created','refund.updated','refund.failed','charge.refunded')),
  event_created bigint not null check(event_created>0),
  refund_id text check(refund_id ~ '^re_[A-Za-z0-9_]{1,240}$'),
  payment_intent_id text check(payment_intent_id ~ '^pi_[A-Za-z0-9_]{1,240}$'),
  charge_id text check(charge_id ~ '^ch_[A-Za-z0-9_]{1,240}$'),
  amount_cents integer check(amount_cents between 1 and 99999999),
  currency text not null check(currency ~ '^[a-z]{3}$'),
  refund_status text check(refund_status in ('pending','requires_action','succeeded','failed','canceled')),
  charge_refunded_cents integer check(charge_refunded_cents between 0 and 99999999),
  received_at timestamptz not null default clock_timestamp(),
  primary key(stripe_account_id,is_test,event_id),
  check((event_type='charge.refunded' and refund_id is null and amount_cents is null
    and refund_status is null and charge_id is not null and charge_refunded_cents is not null)
    or (event_type<>'charge.refunded' and refund_id is not null and amount_cents is not null
      and charge_refunded_cents is null))
);

create index commerce_context_refunds_intent on public.commerce_context_refund_events(stripe_account_id,is_test,payment_intent_id);
create trigger commerce_context_refunds_immutable before update or delete on public.commerce_context_refund_events
for each row execute function private.guard_commerce_context_history();
create trigger commerce_context_refunds_no_truncate before truncate on public.commerce_context_refund_events
for each statement execute function private.guard_commerce_context_history();
alter table public.commerce_context_refund_events enable row level security;
revoke all on public.commerce_context_refund_events from public,anon,authenticated,service_role;
grant select,insert on public.commerce_context_refund_events to service_role;

create function private.commerce_project_context_refunds(p_order_id uuid) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare o public.orders; refunded bigint; conflict boolean;
begin
  select * into o from public.orders where id=p_order_id for update;
  if not found or o.stripe_account_id is null or o.stripe_profile_ref is null or o.commerce_quote_id is null then
    return jsonb_build_object('requires_reconciliation',true,'reason','context_order_required'); end if;
  if not exists(select 1 from public.commerce_context_refund_events r where r.stripe_account_id=o.stripe_account_id
    and r.is_test=o.is_test and r.stripe_profile_ref=o.stripe_profile_ref and r.payment_intent_id=o.stripe_payment_intent_id)
    then return jsonb_build_object('requires_reconciliation',o.financial_review_required); end if;
  update public.orders set financial_review_required=true where id=o.id;
  if o.payment_status not in('paid','refunded') or not exists(
    select 1 from public.commerce_payment_events e
    join public.commerce_checkout_attempts a on a.id=e.attempt_id and a.order_id=o.id
    join public.commerce_payment_sessions s on s.attempt_id=a.id and s.session_id=e.object_id
    where e.stripe_account_id=o.stripe_account_id and e.is_test=o.is_test and e.stripe_profile_ref=o.stripe_profile_ref
      and not e.requires_reconciliation and e.event_type in('checkout.session.completed','checkout.session.async_payment_succeeded')
      and e.payment_intent_id=o.stripe_payment_intent_id and e.object_id=o.stripe_session_id
      and e.amount_cents=o.total_cents and a.total_cents=o.total_cents and a.currency=o.currency
      and a.commerce_quote_id=o.commerce_quote_id and a.stripe_account_id=o.stripe_account_id
      and a.is_test=o.is_test and a.stripe_profile_ref=o.stripe_profile_ref
      and s.stripe_account_id=o.stripe_account_id and s.is_test=o.is_test and s.stripe_profile_ref=o.stripe_profile_ref)
    then return jsonb_build_object('requires_reconciliation',true,'reason','payment_binding_unconfirmed'); end if;
  with identities as (
    select r.refund_id,max(r.amount_cents) amount,bool_or(r.refund_status='succeeded') succeeded,
      (count(distinct r.amount_cents)<>1 or count(distinct r.currency)<>1 or min(r.currency)<>lower(o.currency)
       or count(distinct coalesce(r.payment_intent_id,''))<>1 or min(r.payment_intent_id) is distinct from o.stripe_payment_intent_id
       or count(distinct r.stripe_profile_ref)<>1 or min(r.stripe_profile_ref)<>o.stripe_profile_ref
       or count(distinct r.charge_id)>1
       or (bool_or(r.refund_status='succeeded') and (bool_or(r.refund_status in('failed','canceled'))
         or bool_or(r.event_type='refund.failed')))) bad
    from public.commerce_context_refund_events r where r.stripe_account_id=o.stripe_account_id and r.is_test=o.is_test
      and r.refund_id in(select q.refund_id from public.commerce_context_refund_events q
        where q.stripe_account_id=o.stripe_account_id and q.is_test=o.is_test and q.stripe_profile_ref=o.stripe_profile_ref
          and q.payment_intent_id=o.stripe_payment_intent_id and q.refund_id is not null)
    group by r.refund_id
  ) select coalesce(sum(amount) filter(where succeeded and not bad),0),coalesce(bool_or(bad),false)
    into refunded,conflict from identities;
  if conflict or refunded>o.total_cents or refunded<o.refunded_amount_cents then
    return jsonb_build_object('requires_reconciliation',true,'reason','refund_identity_or_total_conflict'); end if;
  if refunded>o.refunded_amount_cents then
    update public.orders set refunded_amount_cents=refunded::integer,
      payment_status=case when refunded=total_cents then 'refunded' else payment_status end,
      status=case when refunded=total_cents and status<>'cancelled' then 'refunded'::public.order_status else status end where id=o.id;
    insert into public.admin_audit(action,resource,metadata) values('commerce.context.refund_projected',o.id::text,
      jsonb_build_object('refunded_amount_cents',refunded,'is_test',o.is_test,'review_retained',true));
  end if;
  return jsonb_build_object('requires_reconciliation',true,'refunded_amount_cents',refunded,
    'reason','signed_refund_recorded_review_held');
end $$;

create function public.commerce_record_context_refund(p_event jsonb,p_is_test boolean,p_stripe_account_id text,p_profile_ref text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare r public.commerce_context_refund_events; previous public.commerce_context_refund_events;
  o public.orders; known uuid; duplicate boolean:=false; result jsonb;
begin
  perform private.assert_commerce_context(p_is_test,p_stripe_account_id,p_profile_ref);
  if jsonb_typeof(p_event) is distinct from 'object'
    or not p_event ?& array['event_id','event_type','event_created','refund_id','payment_intent_id',
      'charge_id','amount_cents','currency','refund_status','charge_refunded_cents']
    or (select count(*) from jsonb_object_keys(p_event))<>10
    or jsonb_typeof(p_event->'event_created') is distinct from 'number'
    or (p_event->>'event_created') !~ '^[1-9][0-9]{0,18}$'
    or (p_event->>'event_created')::numeric>9223372036854775807
    or exists(select 1 from jsonb_each(p_event) x where x.key in
      ('event_id','event_type','refund_id','payment_intent_id','charge_id','currency','refund_status')
      and jsonb_typeof(x.value) not in ('string','null'))
    or exists(select 1 from jsonb_each(p_event) x where x.key in ('amount_cents','charge_refunded_cents')
      and x.value<>'null'::jsonb and (jsonb_typeof(x.value)<>'number' or x.value::text !~ '^[0-9]{1,8}$'))
    then raise exception 'Invalid normalized context refund'; end if;
  r:=jsonb_populate_record(null::public.commerce_context_refund_events,p_event);
  -- Validate all table constraints before locks or financial effects; no insert
  -- is trusted merely because it was passed by the application service.
  if r.event_id is null or r.event_id !~ '^evt_[A-Za-z0-9_]{1,240}$'
    or r.event_type is null or r.event_type not in ('refund.created','refund.updated','refund.failed','charge.refunded')
    or r.currency is null or r.currency !~ '^[a-z]{3}$'
    or (r.payment_intent_id is not null and r.payment_intent_id !~ '^pi_[A-Za-z0-9_]{1,240}$')
    or (r.charge_id is not null and r.charge_id !~ '^ch_[A-Za-z0-9_]{1,240}$')
    or (r.refund_id is not null and r.refund_id !~ '^re_[A-Za-z0-9_]{1,240}$')
    or (r.refund_status is not null and r.refund_status not in ('pending','requires_action','succeeded','failed','canceled'))
    then raise exception 'Invalid normalized context refund'; end if;
  if r.payment_intent_id is not null then
    select id into known from public.orders where stripe_account_id=p_stripe_account_id and is_test=p_is_test
      and stripe_profile_ref=p_profile_ref and stripe_payment_intent_id=r.payment_intent_id;
    if known is not null then select * into o from public.orders where id=known for update; end if;
    if not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||p_is_test::text||':'||r.payment_intent_id,0))
      then raise exception 'Payment identity busy; retry event'; end if;
    if known is distinct from(select id from public.orders where stripe_account_id=p_stripe_account_id and is_test=p_is_test
      and stripe_profile_ref=p_profile_ref and stripe_payment_intent_id=r.payment_intent_id)
      then raise exception 'Payment binding changed; retry event'; end if;
  end if;
  if r.refund_id is not null and not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||p_is_test::text||':'||r.refund_id,1))
    then raise exception 'Refund identity busy; retry event'; end if;
  select * into previous from public.commerce_context_refund_events where stripe_account_id=p_stripe_account_id and is_test=p_is_test and event_id=r.event_id;
  if found then
    if (to_jsonb(previous)-array['received_at','stripe_account_id','is_test','stripe_profile_ref']) is distinct from p_event
      or previous.stripe_profile_ref<>p_profile_ref then raise exception 'Refund event identity conflict'; end if;
    duplicate:=true;
  else
    insert into public.commerce_context_refund_events(stripe_account_id,is_test,stripe_profile_ref,event_id,event_type,event_created,
      refund_id,payment_intent_id,charge_id,amount_cents,currency,refund_status,charge_refunded_cents)
    values(p_stripe_account_id,p_is_test,p_profile_ref,r.event_id,r.event_type,r.event_created,r.refund_id,r.payment_intent_id,
      r.charge_id,r.amount_cents,r.currency,r.refund_status,r.charge_refunded_cents);
  end if;
  perform public.commerce_record_context_event(r.event_id,r.event_type,coalesce(r.refund_id,r.charge_id),p_is_test,
    p_stripe_account_id,p_profile_ref,r.payment_intent_id);
  if o.id is not null then result:=private.commerce_project_context_refunds(o.id);
  else result:=jsonb_build_object('requires_reconciliation',true,'reason','unbound_context_refund_receipt'); end if;
  return result||jsonb_build_object('received',true,'duplicate',duplicate,'is_test',p_is_test);
end $$;

create function private.project_context_refunds_after_payment() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if pg_trigger_depth()=1 and new.stripe_account_id is not null and new.stripe_profile_ref is not null
    and new.stripe_payment_intent_id is not null then perform private.commerce_project_context_refunds(new.id); end if;
  return new;
end $$;
create trigger commerce_context_refund_projection after update of payment_status,stripe_payment_intent_id on public.orders
for each row execute function private.project_context_refunds_after_payment();

create function public.commerce_reconcile_context_refunds(p_actor uuid,p_order_id uuid,p_expected_updated_at timestamptz,p_evidence_ref text)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare o public.orders; result jsonb;
begin
  perform private.assert_admin(p_actor);
  if p_evidence_ref is null or length(btrim(p_evidence_ref)) not between 3 and 1000 or p_evidence_ref ~ '[[:cntrl:]]'
    then raise exception 'Explicit review evidence required'; end if;
  select * into o from public.orders where id=p_order_id for update;
  if not found or o.stripe_profile_ref is null or o.updated_at is distinct from p_expected_updated_at
    then raise exception 'Order changed or unavailable; reload before review'; end if;
  result:=private.commerce_project_context_refunds(o.id);
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.context.refund_review',o.id::text,
    jsonb_build_object('evidence_ref',p_evidence_ref,'review_retained',true));
  return result||jsonb_build_object('order_id',o.id,'review_released',false);
end $$;
revoke all on function private.commerce_project_context_refunds(uuid),private.project_context_refunds_after_payment(),
  public.commerce_record_context_refund(jsonb,boolean,text,text),public.commerce_reconcile_context_refunds(uuid,uuid,timestamptz,text)
  from public,anon,authenticated;
grant execute on function private.commerce_project_context_refunds(uuid),private.project_context_refunds_after_payment(),
  public.commerce_record_context_refund(jsonb,boolean,text,text),public.commerce_reconcile_context_refunds(uuid,uuid,timestamptz,text)
  to service_role;
commit;
