-- Manual recording of externally obtained evidence; no supplier purchase,
-- carrier request, payment, SMTP call or live activation is performed here.
begin;
alter table public.commerce_fulfillment_tasks
  drop constraint commerce_fulfillment_tasks_state_check,
  add constraint commerce_fulfillment_tasks_state_check check(state in('requires_review','supplier_confirmed','shipped','delivered')),
  add column supplier_order_ref text,
  add column supplier_evidence_ref text,
  add column shipment_evidence_ref text,
  add column delivery_evidence_ref text,
  add column tracking_number text,
  add column carrier text,
  add column tracking_url text,
  add column supplier_confirmed_at timestamptz,
  add column shipped_at timestamptz,
  add column delivered_at timestamptz,
  add column updated_by uuid,
  add column updated_at timestamptz not null default clock_timestamp();

-- A signed refund receipt is a review hold, not a guessed refund amount. The
-- historical six-argument entry point remains an exact compatibility wrapper.
create function public.commerce_record_context_event(p_event_id text,p_event_type text,p_object_id text,p_is_test boolean,
  p_stripe_account_id text,p_profile_ref text,p_payment_intent_id text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare e public.commerce_payment_events; o public.orders; refund_event boolean; duplicate boolean:=false;
begin
  perform private.assert_commerce_context(p_is_test,p_stripe_account_id,p_profile_ref);
  refund_event:=p_event_type in('refund.created','refund.updated','refund.failed','charge.refunded');
  if p_event_id is null or p_event_id !~ '^evt_[A-Za-z0-9_]{1,240}$'
    or p_event_type is null or p_event_type !~ '^[a-z][a-z0-9_.]{1,119}$'
    or p_object_id is null or p_object_id !~ '^(cs_test_|cs_live_|pi_|ch_|re_)[A-Za-z0-9_]{1,240}$'
    or (p_object_id like 'cs_test_%' and not p_is_test) or (p_object_id like 'cs_live_%' and p_is_test)
    or (p_payment_intent_id is not null and (not refund_event or p_payment_intent_id !~ '^pi_[A-Za-z0-9_]{1,240}$'))
    then raise exception 'Invalid context reconciliation receipt'; end if;
  -- Order-first lock matches settlement/dispatch; even a pending refund event
  -- can arrive after payment but before the first operational confirmation.
  if refund_event and p_payment_intent_id is not null then
    select * into o from public.orders where stripe_account_id=p_stripe_account_id and is_test=p_is_test
      and stripe_profile_ref=p_profile_ref and stripe_payment_intent_id=p_payment_intent_id for update;
  end if;
  if not pg_try_advisory_xact_lock(hashtextextended(p_stripe_account_id||':'||p_is_test::text||':'||p_event_id,0))
    then raise exception 'Event receipt busy; retry event'; end if;
  select * into e from public.commerce_payment_events where stripe_account_id=p_stripe_account_id and is_test=p_is_test and event_id=p_event_id;
  if found then
    if e.event_type<>p_event_type or e.object_id<>p_object_id or e.stripe_profile_ref<>p_profile_ref
      or (e.payment_intent_id is not null and e.payment_intent_id is distinct from p_payment_intent_id)
      then raise exception 'Event receipt identity conflict'; end if;
    -- An older incomplete receipt is not silently rewritten or certified.
    duplicate:=true;
  else
    insert into public.commerce_payment_events(stripe_account_id,is_test,event_id,stripe_profile_ref,event_type,object_id,
      payment_intent_id,attempt_id)
    values(p_stripe_account_id,p_is_test,p_event_id,p_profile_ref,p_event_type,p_object_id,p_payment_intent_id,
      (select id from public.commerce_checkout_attempts where order_id=o.id)) returning * into e;
  end if;
  if refund_event and o.id is not null and o.financial_review_required is distinct from true then
    update public.orders set financial_review_required=true where id=o.id;
    insert into public.admin_audit(action,resource,metadata) values('commerce.context.refund_review',o.id::text,
      jsonb_build_object('event_id',p_event_id,'source','signed_refund_receipt','amount_not_inferred',true));
  end if;
  return jsonb_build_object('received',true,'event_recorded',true,'duplicate',duplicate,
    'requires_reconciliation',e.requires_reconciliation,'is_test',p_is_test,
    'unbound_refund_requires_manual_review',refund_event and e.payment_intent_id is null);
end $$;
create or replace function public.commerce_record_context_event(p_event_id text,p_event_type text,p_object_id text,p_is_test boolean,
  p_stripe_account_id text,p_profile_ref text) returns jsonb
language sql security invoker set search_path='' as $$
  select public.commerce_record_context_event(p_event_id,p_event_type,p_object_id,p_is_test,p_stripe_account_id,p_profile_ref,null);
$$;

create function private.context_refund_review_required(p_order public.orders) returns boolean
language sql stable security invoker set search_path='' as $$
  select coalesce(p_order.financial_review_required,false) or exists(
    select 1 from public.commerce_payment_events e where e.stripe_account_id=p_order.stripe_account_id
      and e.stripe_profile_ref=p_order.stripe_profile_ref and e.is_test=p_order.is_test
      and e.requires_reconciliation and e.event_type in('refund.created','refund.updated','refund.failed','charge.refunded')
      and (e.payment_intent_id is null or e.payment_intent_id=p_order.stripe_payment_intent_id));
$$;
create function private.guard_context_refund_review() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.stripe_profile_ref is not null and private.context_refund_review_required(new) then
    new.financial_review_required:=true;
  end if;
  return new;
end $$;
create trigger commerce_context_refund_review before update of payment_status,stripe_payment_intent_id on public.orders
  for each row execute function private.guard_context_refund_review();

-- A pending fulfillment email must not bypass the financial review that now
-- blocks its parcel. Claims already accepted cannot recall an in-flight send.
do $notification_review$ declare d text; a text:='  if valid is distinct from true then'; begin
  select pg_get_functiondef('private.claim_order_notification_core(uuid,uuid,uuid,boolean,text)'::regprocedure) into d;
  if (length(d)-length(replace(d,a,'')))/length(a)<>1 then raise exception 'Context notification review guard drift'; end if;
  execute replace(d,a,'  if o.stripe_profile_ref is not null and private.context_refund_review_required(o) then valid:=false; end if;'||E'\n'||a);
end $notification_review$;

create function private.assert_context_dispatch_order(p_order public.orders,p_shipping boolean) returns void
language plpgsql security invoker set search_path='' as $$
begin
  if p_order.id is null or p_order.is_test or p_order.commerce_quote_id is null or p_order.stripe_profile_ref is null
    or p_order.payment_status<>'paid' or p_order.status in('cancelled','refunded')
    or p_order.fulfillment_status='cancelled' or p_order.refunded_amount_cents<>0
    or private.context_refund_review_required(p_order)
    then raise exception 'Paid production order without financial incident required'; end if;
  if p_shipping and (p_order.stock_applied_at is null or p_order.requires_compatibility_review)
    then raise exception 'Stock and compatibility review required before dispatch'; end if;
end $$;

-- Recording physical delivery of an already dispatched parcel must survive a
-- later cancellation/refund/review. It authorizes no new shipment or money move.
create function private.assert_context_delivery(p_order public.orders,p_task public.commerce_fulfillment_tasks) returns void
language plpgsql security invoker set search_path='' as $$
begin
  if p_order.id is null or p_order.is_test or p_order.commerce_quote_id is null
    or p_order.stripe_account_id is null or p_order.stripe_profile_ref is null
    or p_task.order_id is distinct from p_order.id or p_task.is_test
    or p_task.state not in('shipped','delivered') or p_task.shipped_at is null
    or p_task.tracking_number is null or p_task.carrier is null or p_task.tracking_url is null
    or p_task.shipment_evidence_ref is null or not exists(select 1 from public.commerce_checkout_attempts a
      where a.id=p_task.attempt_id and a.order_id=p_order.id and not a.is_test
        and a.stripe_account_id=p_order.stripe_account_id and a.stripe_profile_ref=p_order.stripe_profile_ref)
    then raise exception 'Already dispatched production parcel with immutable tracking required'; end if;
end $$;

create function private.guard_context_dispatch_task() returns trigger
language plpgsql security invoker set search_path='' as $$
declare o public.orders;
begin
  if tg_op in('DELETE','TRUNCATE') then raise exception 'Context fulfillment history is immutable'; end if;
  if (to_jsonb(new)-array['state','supplier_order_ref','supplier_evidence_ref','shipment_evidence_ref','delivery_evidence_ref',
    'tracking_number','carrier','tracking_url','supplier_confirmed_at','shipped_at','delivered_at','updated_by','updated_at'])
    is distinct from (to_jsonb(old)-array['state','supplier_order_ref','supplier_evidence_ref','shipment_evidence_ref','delivery_evidence_ref',
    'tracking_number','carrier','tracking_url','supplier_confirmed_at','shipped_at','delivered_at','updated_by','updated_at'])
    or new.updated_at<=old.updated_at or new.updated_by is null or new.is_test
    then raise exception 'Context task snapshot and execution mode are immutable'; end if;
  perform private.assert_admin(new.updated_by);
  select * into o from public.orders where id=new.order_id;
  if new.state='delivered' then perform private.assert_context_delivery(o,old);
  else perform private.assert_context_dispatch_order(o,new.state='shipped'); end if;
  if not ((old.state='requires_review' and new.state='supplier_confirmed')
    or (old.state='supplier_confirmed' and new.state='shipped')
    or (old.state='shipped' and new.state='delivered'))
    then raise exception 'Invalid manual context task transition'; end if;
  if new.supplier_order_ref is null or length(btrim(new.supplier_order_ref)) not between 1 and 200
    or new.supplier_evidence_ref is null or length(btrim(new.supplier_evidence_ref)) not between 1 and 1000
    or new.supplier_confirmed_at is null or new.supplier_order_ref ~ '[[:cntrl:]]' or new.supplier_evidence_ref ~ '[[:cntrl:]]'
    then raise exception 'Supplier reference and explicit technical review evidence required'; end if;
  if old.state<>'requires_review' and row(new.supplier_order_ref,new.supplier_evidence_ref,new.supplier_confirmed_at)
    is distinct from row(old.supplier_order_ref,old.supplier_evidence_ref,old.supplier_confirmed_at)
    then raise exception 'Supplier confirmation evidence is immutable'; end if;
  if new.state in('shipped','delivered') then
    if new.state='shipped' and (exists(select 1 from unnest(new.review_reasons) reason where reason<>'fulfillment_approval_required')
      or o.stock_applied_at is null) then raise exception 'Shipment remains held by operational incident'; end if;
    if new.tracking_number is null or length(btrim(new.tracking_number)) not between 1 and 200
      or new.tracking_number ~* '^SIM-' or new.tracking_number ~ '[[:cntrl:]]'
      or new.carrier is null or length(btrim(new.carrier)) not between 1 and 100 or new.carrier ~ '[[:cntrl:]]'
      or new.tracking_url is null or length(new.tracking_url)>1000
      or new.tracking_url !~ '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?([/?#][^[:space:]@]*)?$'
      or new.tracking_url ~ '[[:cntrl:]\\]'
      or new.shipment_evidence_ref is null or length(btrim(new.shipment_evidence_ref)) not between 1 and 1000
      or new.shipment_evidence_ref ~ '[[:cntrl:]]' or new.shipped_at is null
      then raise exception 'Real tracking and shipment proof required; incident remains held'; end if;
  elsif new.tracking_number is not null or new.carrier is not null or new.tracking_url is not null
    or new.shipment_evidence_ref is not null or new.shipped_at is not null then
    raise exception 'Shipment details cannot be recorded before dispatch';
  end if;
  if old.state='shipped' and row(new.tracking_number,new.carrier,new.tracking_url,new.shipment_evidence_ref,new.shipped_at)
    is distinct from row(old.tracking_number,old.carrier,old.tracking_url,old.shipment_evidence_ref,old.shipped_at)
    then raise exception 'Dispatched parcel identity is immutable'; end if;
  if new.state='delivered' then
    if new.delivery_evidence_ref is null or length(btrim(new.delivery_evidence_ref)) not between 1 and 1000
      or new.delivery_evidence_ref ~ '[[:cntrl:]]' or new.delivered_at is null then raise exception 'Delivery proof required'; end if;
  elsif new.delivery_evidence_ref is not null or new.delivered_at is not null then raise exception 'Delivery proof requires delivered transition'; end if;
  return new;
end $$;
drop trigger commerce_fulfillment_tasks_immutable on public.commerce_fulfillment_tasks;
create trigger commerce_fulfillment_tasks_dispatch before update or delete on public.commerce_fulfillment_tasks
  for each row execute function private.guard_context_dispatch_task();

create function public.commerce_advance_context_task(p_actor uuid,p_task_id uuid,p_expected_updated_at timestamptz,p_next text,
  p_supplier_order_ref text,p_tracking_number text,p_carrier text,p_tracking_url text,p_evidence_ref text) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare t public.commerce_fulfillment_tasks; saved public.commerce_fulfillment_tasks; o public.orders; q public.commerce_quotes;
  supplier_ref text; tracking text; carrier_name text; link text; proof text; previous_proof text;
  total_groups integer; task_count integer; next_global text; kind text; event_title text; before_status text; log_id uuid;
  global_changed boolean:=false; reviewed boolean:=false; parcel_count integer;
begin
  perform private.assert_admin(p_actor);
  select * into t from public.commerce_fulfillment_tasks where id=p_task_id;
  if not found then raise exception 'Unknown context task'; end if;
  -- Same order-first locking as settlement and notification claims.
  select * into o from public.orders where id=t.order_id for update;
  select * into strict t from public.commerce_fulfillment_tasks where id=p_task_id for update;
  perform private.assert_admin(p_actor);
  if p_next='delivered' then perform private.assert_context_delivery(o,t);
  else perform private.assert_context_dispatch_order(o,p_next='shipped'); end if;
  if p_expected_updated_at is null or not isfinite(p_expected_updated_at)
    or p_next is null or p_next not in('supplier_confirmed','shipped','delivered') then raise exception 'Version and manual target state required'; end if;
  supplier_ref:=coalesce(nullif(btrim(p_supplier_order_ref),''),t.supplier_order_ref);
  tracking:=coalesce(nullif(btrim(p_tracking_number),''),t.tracking_number);
  carrier_name:=coalesce(nullif(btrim(p_carrier),''),t.carrier);
  link:=coalesce(nullif(btrim(p_tracking_url),''),t.tracking_url);
  proof:=nullif(btrim(p_evidence_ref),'');
  if proof is null or length(proof)>1000 or proof ~ '[[:cntrl:]]' then raise exception 'Explicit manual evidence required'; end if;
  previous_proof:=case p_next when 'supplier_confirmed' then t.supplier_evidence_ref
    when 'shipped' then t.shipment_evidence_ref else t.delivery_evidence_ref end;
  if t.state=p_next then
    if row(supplier_ref,tracking,carrier_name,link,proof) is distinct from
      row(t.supplier_order_ref,t.tracking_number,t.carrier,t.tracking_url,previous_proof)
      then raise exception 'Previously recorded transition evidence cannot be replaced'; end if;
    return jsonb_build_object('task_id',t.id,'order_id',o.id,'updated',false,'status_changed',false,
      'task_state',t.state,'fulfillment_status',o.fulfillment_status,'updated_at',t.updated_at,
      'notification_kind',null,'notification_log_id',null);
  end if;
  if t.updated_at<>p_expected_updated_at then raise exception 'Task changed. Reload before saving'; end if;
  if not ((t.state='requires_review' and p_next='supplier_confirmed') or (t.state='supplier_confirmed' and p_next='shipped')
    or (t.state='shipped' and p_next='delivered')) then raise exception 'Invalid manual context task transition'; end if;
  -- One immutable dossier must cover every paid quoted group; no orphan or
  -- missing supplier/agent group can be hidden by advancing another parcel.
  select count(distinct group_key) into total_groups from public.commerce_order_lines where order_id=o.id;
  select count(*) into task_count from public.commerce_fulfillment_tasks where order_id=o.id;
  if total_groups<1 or task_count<>total_groups or exists(select 1 from public.commerce_fulfillment_tasks ft
    where ft.order_id=o.id and (ft.is_test or ft.attempt_id<>t.attempt_id or not exists(
      select 1 from public.commerce_order_lines cl where cl.order_id=o.id and cl.group_key=ft.group_key
        and cl.offer_snapshot->>'id'=ft.offer_id::text and cl.agent_snapshot->>'id'=ft.agent_id::text
        and cl.supplier_snapshot->>'id'=ft.supplier_id::text and cl.group_snapshot->>'variant_id'=ft.variant_id::text
        and cl.rate_snapshot->>'id'=ft.shipping_rate_id::text
        and cl.offer_snapshot->>'supplier_sku'=ft.supplier_sku
        and ft.quantity=(select sum((line->>'quantity')::integer) from jsonb_array_elements(cl.group_snapshot->'lines') line)
        and ft.snapshot=jsonb_build_object('group',cl.group_snapshot,'offer',cl.offer_snapshot,'rate',cl.rate_snapshot,
          'agent',cl.agent_snapshot,'supplier',cl.supplier_snapshot,'is_test',false,'external_send_allowed',false))))
    then raise exception 'Complete immutable supplier and agent coverage required'; end if;
  update public.commerce_fulfillment_tasks set state=p_next,supplier_order_ref=supplier_ref,
    supplier_evidence_ref=case when p_next='supplier_confirmed' then proof else supplier_evidence_ref end,
    shipment_evidence_ref=case when p_next='shipped' then proof else shipment_evidence_ref end,
    delivery_evidence_ref=case when p_next='delivered' then proof else delivery_evidence_ref end,
    tracking_number=tracking,carrier=carrier_name,tracking_url=link,
    supplier_confirmed_at=case when p_next='supplier_confirmed' then clock_timestamp() else supplier_confirmed_at end,
    shipped_at=case when p_next='shipped' then clock_timestamp() else shipped_at end,
    delivered_at=case when p_next='delivered' then clock_timestamp() else delivered_at end,
    updated_by=p_actor,updated_at=greatest(clock_timestamp(),t.updated_at+interval '1 microsecond') where id=t.id returning * into saved;
  next_global:=o.fulfillment_status::text;
  if p_next='delivered' then
    -- These are logistics facts only. Financial/cancellation/review flags are
    -- preserved, and no historical compatibility attestation is manufactured.
    if not exists(select 1 from public.commerce_fulfillment_tasks where order_id=o.id and state<>'delivered') then next_global:='delivered';
    elsif not exists(select 1 from public.commerce_fulfillment_tasks where order_id=o.id and state not in('shipped','delivered')) then next_global:='shipped'; end if;
  elsif not exists(select 1 from public.commerce_fulfillment_tasks ft where ft.order_id=o.id and
    (ft.state='requires_review' or ft.supplier_evidence_ref is null or exists(
      select 1 from unnest(ft.review_reasons) reason where reason<>'fulfillment_approval_required')))
    and o.stock_applied_at is not null then
    -- Technical attestation is explicit admin evidence for EVERY frozen group,
    -- not an inferred acceptance merely because a vendor sent a vague message.
    select * into strict q from public.commerce_quotes where id=o.commerce_quote_id;
    perform private.check_commerce_quote_payload(q.source_context,q.payload,q.created_at);
    reviewed:=o.requires_compatibility_review;
    next_global:=case when not exists(select 1 from public.commerce_fulfillment_tasks where order_id=o.id and state<>'delivered') then 'delivered'
      when not exists(select 1 from public.commerce_fulfillment_tasks where order_id=o.id and state not in('shipped','delivered')) then 'shipped'
      else 'processing' end;
  end if;
  before_status:=o.fulfillment_status::text;
  global_changed:=next_global<>before_status;
  if global_changed or reviewed then
    select count(*) into parcel_count from public.commerce_fulfillment_tasks where order_id=o.id;
    update public.orders set fulfillment_status=next_global::public.fulfillment_status,
      requires_compatibility_review=case when reviewed then false else requires_compatibility_review end,
      tracking_number=case when parcel_count=1 and next_global in('shipped','delivered') then saved.tracking_number else null end,
      carrier=case when parcel_count=1 and next_global in('shipped','delivered') then saved.carrier else null end,
      tracking_url=case when parcel_count=1 and next_global in('shipped','delivered') then saved.tracking_url else null end,
      shipped_at=case when next_global in('shipped','delivered') then coalesce(shipped_at,clock_timestamp()) else shipped_at end,
      delivered_at=case when next_global='delivered' then coalesce(delivered_at,clock_timestamp()) else delivered_at end
      where id=o.id returning * into o;
    if reviewed then
      insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.compatibility.reviewed',o.id::text,
        jsonb_build_object('source','manual_admin_per_group_evidence','all_groups',true,
          'task_evidence',(select jsonb_agg(jsonb_build_object('task_id',id,'evidence_ref',supplier_evidence_ref) order by id)
            from public.commerce_fulfillment_tasks where order_id=o.id)));
    end if;
  end if;
  event_title:=case p_next when 'supplier_confirmed' then 'Préparation du colis confirmée'
    when 'shipped' then 'Colis expédié' else 'Colis livré' end;
  insert into public.order_tracking_events(order_id,event_key,title,description,source,is_customer_visible,metadata)
    values(o.id,'commerce_parcel_'||t.id::text||'_'||p_next,event_title,
      case when p_next='supplier_confirmed' then 'Information enregistrée et vérifiée manuellement par l’équipe TYMotors.'
        when p_next='shipped' then 'Transporteur : '||saved.carrier||' · Numéro de suivi : '||saved.tracking_number
        else 'Livraison confirmée manuellement · Transporteur : '||saved.carrier||' · Numéro de suivi : '||saved.tracking_number end,'admin',true,
      jsonb_build_object('task_id',t.id,'tracking_number',saved.tracking_number,'carrier',saved.carrier,
        'tracking_url',saved.tracking_url,'manual_confirmation',true,'external_call_performed',false));
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.task.manual_transition',o.id::text,
    jsonb_build_object('task_id',t.id,'before',t.state,'after',p_next,'evidence_ref',proof,
      'supplier_order_ref',saved.supplier_order_ref,'reference_variant_fitment_attested',p_next='supplier_confirmed',
      'financial_commitment_performed',false,'external_call_performed',false));
  if global_changed then
    kind:=case next_global when 'processing' then 'order_processing' when 'shipped' then 'order_shipped' when 'delivered' then 'order_delivered' end;
    log_id:=private.enqueue_order_notification(o.id,kind);
  end if;
  return jsonb_build_object('task_id',saved.id,'order_id',o.id,'updated',true,'status_changed',global_changed,
    'task_state',saved.state,'fulfillment_status',o.fulfillment_status,'updated_at',saved.updated_at,
    'notification_kind',kind,'notification_log_id',log_id);
end $$;

grant update on public.commerce_fulfillment_tasks to service_role;
revoke all on function public.commerce_record_context_event(text,text,text,boolean,text,text,text),
  private.context_refund_review_required(public.orders),private.guard_context_refund_review(),
  private.assert_context_dispatch_order(public.orders,boolean),private.assert_context_delivery(public.orders,public.commerce_fulfillment_tasks),private.guard_context_dispatch_task(),
  public.commerce_advance_context_task(uuid,uuid,timestamptz,text,text,text,text,text,text)
  from public,anon,authenticated;
grant execute on function public.commerce_record_context_event(text,text,text,boolean,text,text,text),
  private.context_refund_review_required(public.orders),private.guard_context_refund_review(),
  private.assert_context_dispatch_order(public.orders,boolean),private.assert_context_delivery(public.orders,public.commerce_fulfillment_tasks),private.guard_context_dispatch_task(),
  public.commerce_advance_context_task(uuid,uuid,timestamptz,text,text,text,text,text,text) to service_role;
commit;
