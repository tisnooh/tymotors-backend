-- Signed sandbox receipts only. No refund creation, mail, stock or provider send.
begin;
alter table public.orders add column financial_review_required boolean not null default false;

create table public.commerce_test_refund_events (
  event_id text primary key check(event_id ~ '^evt_[A-Za-z0-9_]{1,240}$'),
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
  check((event_type='charge.refunded' and refund_id is null and amount_cents is null
    and refund_status is null and charge_id is not null and charge_refunded_cents is not null)
    or (event_type<>'charge.refunded' and refund_id is not null and amount_cents is not null
      and charge_refunded_cents is null))
);
create index commerce_test_refunds_intent on public.commerce_test_refund_events(payment_intent_id);
create index commerce_test_refunds_identity on public.commerce_test_refund_events(refund_id);
create trigger commerce_test_refunds_history before update or delete on public.commerce_test_refund_events
  for each row execute function private.guard_commerce_test_history();
create trigger commerce_test_refunds_no_truncate before truncate on public.commerce_test_refund_events
  for each statement execute function private.guard_commerce_test_history();
alter table public.commerce_test_refund_events enable row level security;
revoke all on public.commerce_test_refund_events from public,anon,authenticated,service_role;
grant select,insert on public.commerce_test_refund_events to service_role;

-- Sticky review: a failed/pending refund is NOT money returned, but still needs
-- human reconciliation. No automatic release or deletion of historical tasks.
create function private.commerce_test_refund_hold(p_order_id uuid) returns boolean
language sql stable security invoker set search_path='' as $$
  select coalesce((select o.financial_review_required or exists(
    select 1 from public.commerce_test_refund_events r
    where r.payment_intent_id=o.stripe_payment_intent_id)
    from public.orders o where o.id=p_order_id),true)
$$;

create function private.commerce_project_test_refunds(p_order_id uuid) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare o public.orders; refunded bigint; conflict boolean;
begin
  select * into o from public.orders where id=p_order_id for update;
  if not found or not o.is_test or o.commerce_quote_id is null then
    return jsonb_build_object('requires_reconciliation',true,'reason','not_quoted_test_order');
  end if;
  if not exists(select 1 from public.commerce_test_refund_events
    where payment_intent_id=o.stripe_payment_intent_id) then
    return jsonb_build_object('requires_reconciliation',o.financial_review_required);
  end if;
  update public.orders set financial_review_required=true where id=o.id;
  -- An order PI or metadata alone is not settlement proof. Corroborate with the
  -- immutable signed payment history, attempt, session and amount/quote identity.
  if not exists(select 1 from public.commerce_test_payment_events e
    join public.commerce_checkout_attempts a on a.id=e.attempt_id
    join public.commerce_test_sessions s on s.attempt_id=a.id and s.session_id=e.session_id
    where a.order_id=o.id and a.is_test and a.commerce_quote_id=o.commerce_quote_id
      and e.payment_intent_id=o.stripe_payment_intent_id
      and e.amount_cents=o.total_cents and a.total_cents=o.total_cents and a.currency=o.currency
      and e.session_id=o.stripe_session_id)
    or o.payment_status not in ('paid','refunded') then
    return jsonb_build_object('requires_reconciliation',true,'reason','payment_binding_unconfirmed');
  end if;
  -- One refund ID is one financial identity, irrespective of event count/order.
  -- A contradictory terminal status/amount/currency/PI cannot overwrite truth.
  with identities as (
    select r.refund_id, max(r.amount_cents) amount,
      bool_or(r.refund_status='succeeded') succeeded,
      (count(distinct r.amount_cents)<>1 or count(distinct r.currency)<>1
        or min(r.currency)<>lower(o.currency)
        or count(distinct coalesce(r.payment_intent_id,''))<>1
        or min(r.payment_intent_id) is distinct from o.stripe_payment_intent_id
        or count(distinct r.charge_id)>1
        or (bool_or(r.refund_status='succeeded') and
          (bool_or(r.refund_status in ('failed','canceled')) or bool_or(r.event_type='refund.failed')))) bad
    from public.commerce_test_refund_events r
    where r.refund_id in (select refund_id from public.commerce_test_refund_events
      where payment_intent_id=o.stripe_payment_intent_id and refund_id is not null)
    group by r.refund_id
  ) select coalesce(sum(amount) filter(where succeeded and not bad),0),coalesce(bool_or(bad),false)
    into refunded,conflict from identities;
  if conflict or refunded>o.total_cents or refunded<o.refunded_amount_cents then
    return jsonb_build_object('requires_reconciliation',true,'reason','refund_identity_or_total_conflict');
  end if;
  if refunded>o.refunded_amount_cents then
    update public.orders set refunded_amount_cents=refunded::integer,
      payment_status=case when refunded=total_cents then 'refunded' else payment_status end,
      status=case when refunded=total_cents and status<>'cancelled' then 'refunded'::public.order_status else status end
      where id=o.id;
  end if;
  return jsonb_build_object('requires_reconciliation',true,'refunded_amount_cents',refunded,
    'reason','signed_refund_recorded_review_held');
end $$;

-- Backend only: the raw HTTP signature/mode must already be checked. Independent
-- shape validation here prevents an internal caller weakening financial checks.
create function public.commerce_record_test_refund(p_event jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r public.commerce_test_refund_events; previous public.commerce_test_refund_events;
  o public.orders; known uuid; duplicate boolean:=false; result jsonb;
begin
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
    then raise exception 'Invalid normalized test refund'; end if;
  r:=jsonb_populate_record(null::public.commerce_test_refund_events,p_event);
  -- Validate all table constraints before locks or financial effects; no insert
  -- is trusted merely because it was passed by the application service.
  if r.event_id is null or r.event_id !~ '^evt_[A-Za-z0-9_]{1,240}$'
    or r.event_type is null or r.event_type not in ('refund.created','refund.updated','refund.failed','charge.refunded')
    or r.currency is null or r.currency !~ '^[a-z]{3}$'
    or (r.payment_intent_id is not null and r.payment_intent_id !~ '^pi_[A-Za-z0-9_]{1,240}$')
    or (r.charge_id is not null and r.charge_id !~ '^ch_[A-Za-z0-9_]{1,240}$')
    or (r.refund_id is not null and r.refund_id !~ '^re_[A-Za-z0-9_]{1,240}$')
    or (r.refund_status is not null and r.refund_status not in ('pending','requires_action','succeeded','failed','canceled'))
    then raise exception 'Invalid normalized test refund'; end if;
  if r.payment_intent_id is not null then
    select id into known from public.orders where stripe_payment_intent_id=r.payment_intent_id;
    if known is not null then select * into o from public.orders where id=known for update; end if;
    if not pg_try_advisory_xact_lock(hashtextextended(r.payment_intent_id,0))
      then raise exception 'Payment identity busy; retry event'; end if;
    -- Unknown-to-known race: retry rather than reverse the order-first locking.
    if known is distinct from (select id from public.orders where stripe_payment_intent_id=r.payment_intent_id)
      then raise exception 'Payment binding changed; retry event'; end if;
  end if;
  if r.refund_id is not null and not pg_try_advisory_xact_lock(hashtextextended(r.refund_id,1))
    then raise exception 'Refund identity busy; retry event'; end if;
  select * into previous from public.commerce_test_refund_events where event_id=r.event_id;
  if found then
    if (to_jsonb(previous)-'received_at') is distinct from p_event
      then raise exception 'Refund event identity conflict'; end if;
    duplicate:=true;
  else
    insert into public.commerce_test_refund_events(event_id,event_type,event_created,refund_id,
      payment_intent_id,charge_id,amount_cents,currency,refund_status,charge_refunded_cents)
      values(r.event_id,r.event_type,r.event_created,r.refund_id,r.payment_intent_id,r.charge_id,
        r.amount_cents,r.currency,r.refund_status,r.charge_refunded_cents);
  end if;
  -- Business conflicts/unbound evidence are retained, NOT rolled back or guessed.
  if o.id is not null and o.is_test and o.commerce_quote_id is not null then
    result:=private.commerce_project_test_refunds(o.id);
  else result:=jsonb_build_object('requires_reconciliation',true,'reason','unbound_test_refund_receipt'); end if;
  return result||jsonb_build_object('received',true,'duplicate',duplicate,'is_test',true);
end $$;

-- Amend reviewed definitions with strict anchors; fail closed on schema drift.
do $amend$
declare definition text; anchor text;
begin
  select pg_get_functiondef('public.commerce_settle_test_checkout(text,text,jsonb,boolean)'::regprocedure) into definition;
  anchor:='    paid_at=clock_timestamp() where id=o.id;';
  if strpos(definition,anchor)=0 or strpos(definition,'if p_destination_matches and o.status<>''cancelled'' then')=0
    or strpos(definition,'''fulfillment_held'',not p_destination_matches or o.status=''cancelled''')=0 then
    raise exception 'Review settlement before refund amendment'; end if;
  definition:=replace(definition,anchor,anchor||E'\n  perform private.commerce_project_test_refunds(o.id);');
  definition:=replace(definition,'if p_destination_matches and o.status<>''cancelled'' then',
    'if p_destination_matches and o.status<>''cancelled'' and not private.commerce_test_refund_hold(o.id) then');
  definition:=replace(definition,'''fulfillment_held'',not p_destination_matches or o.status=''cancelled''',
    '''fulfillment_held'',not p_destination_matches or o.status=''cancelled'' or private.commerce_test_refund_hold(o.id)');
  execute definition;
  select pg_get_functiondef('public.commerce_advance_test_task(uuid,uuid,text,text,text)'::regprocedure) into definition;
  anchor:='or o.refunded_amount_cents>0';
  if strpos(definition,anchor)=0 then raise exception 'Review task guard before refund amendment'; end if;
  execute replace(definition,anchor,anchor||' or private.commerce_test_refund_hold(o.id)');
  select pg_get_functiondef('public.commerce_prepare_hypersku_task(uuid,uuid,uuid)'::regprocedure) into definition;
  anchor:='or ord.refunded_amount_cents>0';
  if strpos(definition,anchor)=0 then raise exception 'Review preparation guard before refund amendment'; end if;
  execute replace(definition,anchor,anchor||' or private.commerce_test_refund_hold(ord.id)');
end $amend$;

revoke all on function private.commerce_test_refund_hold(uuid),private.commerce_project_test_refunds(uuid),
  public.commerce_record_test_refund(jsonb) from public,anon,authenticated;
grant execute on function private.commerce_test_refund_hold(uuid),private.commerce_project_test_refunds(uuid),
  public.commerce_record_test_refund(jsonb) to service_role;
commit;
