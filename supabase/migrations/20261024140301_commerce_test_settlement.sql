-- Private sandbox settlement and simulated fulfillment. No real stock or sending.
begin;
create table public.commerce_test_sessions (
  attempt_id uuid primary key references public.commerce_checkout_attempts(id) on delete restrict,
  session_id text not null unique check(session_id ~ '^cs_test_[A-Za-z0-9_]+$'),
  created_at timestamptz not null default clock_timestamp()
);
create table public.commerce_test_payment_events (
  event_id text primary key check(event_id ~ '^evt_[A-Za-z0-9_]+$'),
  attempt_id uuid not null references public.commerce_checkout_attempts(id) on delete restrict,
  event_type text not null check(event_type in ('checkout.session.completed','checkout.session.async_payment_succeeded')),
  session_id text not null,
  payment_intent_id text not null check(payment_intent_id ~ '^pi_[A-Za-z0-9_]+$'),
  amount_cents integer not null check(amount_cents>=50),
  destination_matches boolean not null,
  created_at timestamptz not null default clock_timestamp()
);
-- Several distinct Stripe event types may report the SAME payment. Identity is
-- serialized by the advisory lock; uniqueness belongs to the session binding,
-- not to event history (which must retain every authenticated event ID).
create index commerce_test_intent_owner on public.commerce_test_payment_events(payment_intent_id,attempt_id);
create table public.commerce_test_tasks (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete restrict,
  attempt_id uuid not null references public.commerce_checkout_attempts(id) on delete restrict,
  group_key text not null,
  -- Historical identities, NOT FKs to mutable catalogue/agent/rate rows. Removing
  -- a current rate or replacing an offer's operator must not erase paid truth.
  -- Exact relationships and terms live in the immutable snapshots below.
  supplier_id uuid not null,
  agent_id uuid not null,
  offer_id uuid not null,
  shipping_rate_id uuid not null,
  variant_id uuid not null,
  supplier_sku text not null check(length(btrim(supplier_sku))>0),
  quantity integer not null check(quantity between 1 and 2000),
  snapshot jsonb not null check(jsonb_typeof(snapshot)='object'),
  state text not null default 'prepared' check(state in ('prepared','received_by_agent','quality_checked','shipped','delivered')),
  tracking_number text check(tracking_number ~ '^SIM-[A-Za-z0-9_-]{1,100}$'),
  is_test boolean not null default true check(is_test),
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(order_id,group_key)
);
create index commerce_test_tasks_attempt on public.commerce_test_tasks(attempt_id);
create table public.commerce_test_task_events (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.commerce_test_tasks(id) on delete restrict,
  state text not null,
  actor_id uuid references public.profiles(id) on delete restrict,
  created_at timestamptz not null default clock_timestamp(),
  unique(task_id,state)
);

create function private.guard_commerce_test_history() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if tg_table_name<>'commerce_test_tasks' or tg_op<>'UPDATE' then raise exception 'Test commerce history is immutable'; end if;
  if (to_jsonb(new)-array['state','tracking_number','updated_at']) is distinct from
     (to_jsonb(old)-array['state','tracking_number','updated_at'])
    or not ((old.state='prepared' and new.state='received_by_agent')
      or (old.state='received_by_agent' and new.state='quality_checked')
      or (old.state='quality_checked' and new.state='shipped' and new.tracking_number is not null)
      or (old.state='shipped' and new.state='delivered'))
    or (old.tracking_number is not null and new.tracking_number is distinct from old.tracking_number)
    then raise exception 'Invalid simulated task transition'; end if;
  new.updated_at:=clock_timestamp(); return new;
end $$;
create trigger commerce_test_tasks_history before update or delete on public.commerce_test_tasks for each row execute function private.guard_commerce_test_history();
create trigger commerce_test_tasks_no_truncate before truncate on public.commerce_test_tasks for each statement execute function private.guard_commerce_test_history();
create trigger commerce_test_sessions_history before update or delete on public.commerce_test_sessions for each row execute function private.guard_commerce_test_history();
create trigger commerce_test_sessions_no_truncate before truncate on public.commerce_test_sessions for each statement execute function private.guard_commerce_test_history();
create trigger commerce_test_payments_history before update or delete on public.commerce_test_payment_events for each row execute function private.guard_commerce_test_history();
create trigger commerce_test_payments_no_truncate before truncate on public.commerce_test_payment_events for each statement execute function private.guard_commerce_test_history();
create trigger commerce_test_events_history before update or delete on public.commerce_test_task_events for each row execute function private.guard_commerce_test_history();
create trigger commerce_test_events_no_truncate before truncate on public.commerce_test_task_events for each statement execute function private.guard_commerce_test_history();

create function public.commerce_bind_test_session(p_attempt_id uuid,p_session_id text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts; s public.commerce_test_sessions;
begin
  select * into a from public.commerce_checkout_attempts where id=p_attempt_id;
  if not found or not a.is_test or a.state not in ('creating','unknown') or a.params is null
    or a.first_requested_at is null or p_session_id is null or p_session_id !~ '^cs_test_[A-Za-z0-9_]+$'
    then raise exception 'Claimed test checkout required'; end if;
  -- No cart/catalogue dependency: a provider response can arrive after deletion/change.
  select * into s from public.commerce_test_sessions where attempt_id=a.id;
  if found then
    if s.session_id<>p_session_id then raise exception 'Checkout session already bound'; end if;
    return to_jsonb(s);
  end if;
  insert into public.commerce_test_sessions(attempt_id,session_id) values(a.id,p_session_id)
    on conflict(attempt_id) do nothing;
  select * into strict s from public.commerce_test_sessions where attempt_id=a.id;
  if s.session_id<>p_session_id then raise exception 'Checkout session already bound'; end if;
  return to_jsonb(s);
end $$;

-- Caller MUST authenticate Stripe signature and run the pure session validator.
-- This RPC independently binds identity/mode/money and deduplicates financial work.
create function public.commerce_settle_test_checkout(p_event_id text,p_event_type text,p_session jsonb,p_destination_matches boolean)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare a public.commerce_checkout_attempts; o public.orders; oldevent public.commerce_test_payment_events;
  s public.commerce_test_sessions; cl public.commerce_order_lines; q public.commerce_quotes; n integer; seen boolean;
begin
  if p_event_id is null or p_event_id !~ '^evt_[A-Za-z0-9_]+$' or p_event_type is null
    or p_event_type not in ('checkout.session.completed','checkout.session.async_payment_succeeded')
    or p_destination_matches is null or jsonb_typeof(p_session) is distinct from 'object'
    then raise exception 'Invalid test payment event'; end if;
  -- Same order serializes webhook replay and competing event types.
  select * into a from public.commerce_checkout_attempts where id=(p_session->'metadata'->>'attempt_id')::uuid;
  if not found then raise exception 'Unknown checkout attempt'; end if;
  select * into o from public.orders where id=a.order_id for update;
  if not found or not a.is_test or not o.is_test or o.commerce_quote_id is distinct from a.commerce_quote_id
    or a.state not in ('creating','unknown') or a.first_requested_at is null
    or p_session->>'object' is distinct from 'checkout.session' or p_session->>'mode' is distinct from 'payment'
    or p_session->'livemode' is distinct from 'false'::jsonb or p_session->>'status' is distinct from 'complete'
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
    or p_session->>'payment_intent' is null or p_session->>'payment_intent' !~ '^pi_[A-Za-z0-9_]+$'
    then raise exception 'Invalid test payment snapshot'; end if;
  perform public.commerce_bind_test_session(a.id,p_session->>'id');
  if not pg_try_advisory_xact_lock(hashtextextended(p_session->>'payment_intent',0))
    then raise exception 'Payment identity busy; retry event'; end if;
  select * into oldevent from public.commerce_test_payment_events where event_id=p_event_id;
  if found then
    if oldevent.attempt_id<>a.id or oldevent.session_id<>p_session->>'id'
      or oldevent.payment_intent_id<>p_session->>'payment_intent' or oldevent.event_type<>p_event_type
      or oldevent.destination_matches<>p_destination_matches then raise exception 'Event identity conflict'; end if;
    return jsonb_build_object('order_id',o.id,'duplicate',true,'is_test',true);
  end if;
  if exists(select 1 from public.commerce_test_payment_events where
      (attempt_id=a.id and payment_intent_id<>p_session->>'payment_intent')
      or (attempt_id<>a.id and payment_intent_id=p_session->>'payment_intent'))
    then raise exception 'Payment intent already bound'; end if;
  seen:=exists(select 1 from public.commerce_test_payment_events where attempt_id=a.id);
  insert into public.commerce_test_payment_events(event_id,attempt_id,event_type,session_id,payment_intent_id,amount_cents,destination_matches)
    values(p_event_id,a.id,p_event_type,p_session->>'id',p_session->>'payment_intent',o.total_cents,p_destination_matches);
  if seen then return jsonb_build_object('order_id',o.id,'duplicate',true,'is_test',true); end if;
  if o.payment_status not in ('unpaid','failed') then raise exception 'Unexpected order financial state'; end if;
  select * into strict q from public.commerce_quotes where id=a.commerce_quote_id;
  select count(*) into n from public.commerce_order_lines where order_id=o.id;
  if n<1 or n<>(select count(*) from public.order_items where order_id=o.id)
    or exists(select 1 from public.commerce_order_lines where order_id=o.id and quote_id<>q.id)
    then raise exception 'Incomplete immutable order lines'; end if;
  update public.orders set payment_status='paid',status=case when status='cancelled' then status else 'paid'::public.order_status end,
    fulfillment_status='requires_review',stripe_session_id=p_session->>'id',stripe_payment_intent_id=p_session->>'payment_intent',
    customer_email=coalesce(customer_email,case when length(p_session->'customer_details'->>'email')<=254
      and p_session->'customer_details'->>'email' ~ '^[^[:space:]@]+@[^[:space:]@]+[.][^[:space:]@]+$'
      then p_session->'customer_details'->>'email' end),
    paid_at=clock_timestamp() where id=o.id;
  -- Never ship a paid but redirected/cancelled order. Financial truth is preserved.
  if p_destination_matches and o.status<>'cancelled' then
    for cl in select distinct on (group_key) * from public.commerce_order_lines where order_id=o.id order by group_key,id loop
      insert into public.commerce_test_tasks(order_id,attempt_id,group_key,supplier_id,agent_id,offer_id,shipping_rate_id,variant_id,supplier_sku,quantity,snapshot)
      values(o.id,a.id,cl.group_key,(cl.supplier_snapshot->>'id')::uuid,(cl.agent_snapshot->>'id')::uuid,
        (cl.offer_snapshot->>'id')::uuid,(cl.rate_snapshot->>'id')::uuid,(cl.group_snapshot->>'variant_id')::uuid,
        cl.offer_snapshot->>'supplier_sku',
        (select sum((x->>'quantity')::integer) from jsonb_array_elements(cl.group_snapshot->'lines') x),
        jsonb_build_object('group',cl.group_snapshot,'offer',cl.offer_snapshot,'rate',cl.rate_snapshot,
          'agent',cl.agent_snapshot,'supplier',cl.supplier_snapshot,'is_test',true,'external_send_allowed',false));
    end loop;
    insert into public.commerce_test_task_events(task_id,state) select id,'prepared' from public.commerce_test_tasks where order_id=o.id;
  end if;
  -- Do NOT erase the cart: its lines might have changed while payment was pending.
  -- Conservative holds remain held until a dedicated reviewed release/consume path.
  insert into public.admin_audit(action,resource,metadata) values('commerce.test.payment',o.id::text,
    jsonb_build_object('is_test',true,'event_id',p_event_id,'destination_matches',p_destination_matches));
  return jsonb_build_object('order_id',o.id,'duplicate',false,'is_test',true,'fulfillment_held',not p_destination_matches or o.status='cancelled');
end $$;

create function public.commerce_advance_test_task(p_actor uuid,p_task_id uuid,p_expected text,p_next text,p_tracking_number text default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare t public.commerce_test_tasks; o public.orders;
begin
  perform private.assert_admin(p_actor);
  select * into t from public.commerce_test_tasks where id=p_task_id;
  if not found then raise exception 'Unknown test task'; end if;
  -- Same order-first lock order as settlement. A cancellation wins before any
  -- further simulated processing, even if tasks were prepared earlier.
  select * into o from public.orders where id=t.order_id for update;
  if not found or not o.is_test or o.status in ('cancelled','refunded') or o.payment_status<>'paid' or o.refunded_amount_cents>0
    then raise exception 'Paid non-cancelled test order required'; end if;
  select * into t from public.commerce_test_tasks where id=p_task_id for update;
  if not found then raise exception 'Unknown test task'; end if;
  if t.state=p_next and t.tracking_number is not distinct from p_tracking_number then return to_jsonb(t); end if;
  if t.state is distinct from p_expected then raise exception 'Task changed; reload'; end if;
  if p_next<>'shipped' and p_tracking_number is distinct from t.tracking_number then raise exception 'Tracking may only be attached at simulated shipment'; end if;
  update public.commerce_test_tasks set state=p_next,tracking_number=p_tracking_number where id=t.id returning * into t;
  insert into public.commerce_test_task_events(task_id,state,actor_id) values(t.id,t.state,p_actor);
  insert into public.order_tracking_events(order_id,event_key,title,description,source,is_customer_visible,metadata)
    values(t.order_id,'simulation_'||t.id::text||'_'||t.state,'Simulation : '||t.state,
      'Essai isolé : aucune expédition réelle.','system',true,
      jsonb_build_object('is_test',true,'task_id',t.id,'tracking_number',t.tracking_number));
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.test.task',t.id::text,jsonb_build_object('state',t.state,'is_test',true));
  return to_jsonb(t);
end $$;

alter table public.commerce_test_sessions enable row level security;
alter table public.commerce_test_payment_events enable row level security;
alter table public.commerce_test_tasks enable row level security;
alter table public.commerce_test_task_events enable row level security;
revoke all on public.commerce_test_sessions,public.commerce_test_payment_events,public.commerce_test_tasks,public.commerce_test_task_events from public,anon,authenticated,service_role;
grant select,insert on public.commerce_test_sessions,public.commerce_test_payment_events,public.commerce_test_task_events to service_role;
grant select,insert,update on public.commerce_test_tasks to service_role;
revoke all on function private.guard_commerce_test_history(),public.commerce_bind_test_session(uuid,text),public.commerce_settle_test_checkout(text,text,jsonb,boolean),public.commerce_advance_test_task(uuid,uuid,text,text,text) from public,anon,authenticated;
grant execute on function private.guard_commerce_test_history(),public.commerce_bind_test_session(uuid,text),public.commerce_settle_test_checkout(text,text,jsonb,boolean),public.commerce_advance_test_task(uuid,uuid,text,text,text) to service_role;
commit;
