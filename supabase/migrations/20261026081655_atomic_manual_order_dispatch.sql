-- Manual fulfillment is not a HyperSKU connection or a carrier webhook.
-- Keep all customer-visible shipment data in one versioned transaction.
begin;

create function public.admin_update_order_fulfillment(
  p_actor uuid,p_id uuid,p_status text,p_tracking text,p_carrier text,
  p_tracking_url text,p_expected timestamptz
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare o public.orders; saved public.orders; tracking text; carrier_name text; link text;
  changed boolean; event_title text; event_description text; email_kind text;
begin
  perform private.assert_admin(p_actor);
  select * into o from public.orders where id=p_id for update;
  if not found then raise exception 'Order not found'; end if;
  -- The administrator may have been revoked while waiting for the row lock.
  perform private.assert_admin(p_actor);
  if p_expected is null then raise exception 'Order changed. Reload before saving'; end if;
  if p_status is null or p_status not in ('unfulfilled','processing','shipped','delivered','cancelled','requires_review')
    then raise exception 'Invalid transition'; end if;
  tracking:=nullif(btrim(p_tracking),''); carrier_name:=nullif(btrim(p_carrier),'');
  link:=nullif(btrim(p_tracking_url),'');
  if length(tracking)>200 or length(carrier_name)>100 or length(link)>1000
    or coalesce(tracking,'') ~ '[[:cntrl:]]' or coalesce(carrier_name,'') ~ '[[:cntrl:]]'
    or (link is not null and (link !~ '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?([/?#][^[:space:]@]*)?$'
      or link ~ '[[:cntrl:]]')) then raise exception 'Invalid shipment details'; end if;

  if o.fulfillment_status in ('shipped','delivered') then
    -- Omitted values during delivery preserve the already published tracking.
    tracking:=coalesce(tracking,o.tracking_number);
    carrier_name:=coalesce(carrier_name,o.carrier); link:=coalesce(link,o.tracking_url);
    if tracking is distinct from o.tracking_number or carrier_name is distinct from o.carrier
      or link is distinct from o.tracking_url then raise exception 'Shipment tracking is locked after dispatch'; end if;
  end if;
  if p_status in ('processing','shipped','delivered') then
    if o.is_test then raise exception 'Test orders require simulation-only fulfillment'; end if;
    if o.payment_status<>'paid' or o.status in ('cancelled','refunded') or o.refunded_amount_cents<>0
      then raise exception 'Payment required; cancelled or refunded orders cannot be dispatched'; end if;
    if o.requires_compatibility_review then raise exception 'Compatibility review required before dispatch'; end if;
    if o.commerce_quote_id is not null then
      raise exception 'Quoted orders require verified multi-parcel fulfillment';
    end if;
  end if;
  if p_status in ('shipped','delivered') and (tracking is null or carrier_name is null)
    then raise exception 'Tracking number required with carrier'; end if;
  if p_status in ('shipped','delivered') and tracking ~* '^SIM-'
    then raise exception 'Simulated tracking cannot represent a real shipment'; end if;

  changed:=p_status<>o.fulfillment_status::text;
  if not changed and tracking is not distinct from o.tracking_number
    and carrier_name is not distinct from o.carrier and link is not distinct from o.tracking_url then
    return jsonb_build_object('updated',false,'status_changed',false,'notification_kind',null,'updated_at',o.updated_at);
  end if;
  if o.updated_at<>p_expected then raise exception 'Order changed. Reload before saving'; end if;
  if o.fulfillment_status in ('cancelled','delivered') then raise exception 'This order is closed'; end if;
  if changed then
    if o.fulfillment_status='shipped' and p_status<>'delivered' then raise exception 'Invalid transition'; end if;
    if p_status='delivered' and o.fulfillment_status<>'shipped' then raise exception 'Ship the order first'; end if;
    if p_status='shipped' and o.fulfillment_status not in ('unfulfilled','processing','requires_review')
      then raise exception 'Invalid transition'; end if;
  end if;
  update public.orders set fulfillment_status=p_status::public.fulfillment_status,
    tracking_number=tracking,carrier=carrier_name,tracking_url=link,
    status=case when p_status='cancelled' then 'cancelled'::public.order_status else status end,
    shipped_at=case when p_status='shipped' then coalesce(shipped_at,clock_timestamp()) else shipped_at end,
    delivered_at=case when p_status='delivered' then coalesce(delivered_at,clock_timestamp()) else delivered_at end
  where id=p_id returning * into saved;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'order.update',p_id::text,jsonb_build_object(
    'before',jsonb_build_object('status',o.fulfillment_status,'tracking',o.tracking_number,'carrier',o.carrier,'tracking_url',o.tracking_url),
    'after',jsonb_build_object('status',p_status,'tracking',tracking,'carrier',carrier_name,'tracking_url',link),
    'confirmation_source','manual_admin_not_provider_webhook'));
  if changed then
    event_title:=case p_status when 'shipped' then 'Commande expédiée' when 'delivered' then 'Commande livrée'
      when 'cancelled' then 'Commande annulée' end;
    event_description:=case p_status
      when 'shipped' then 'L’équipe TYMotors a enregistré l’expédition et les informations de suivi.'
      when 'delivered' then 'L’équipe TYMotors a confirmé manuellement la livraison.'
      when 'cancelled' then 'Cette commande a été annulée.' end;
    if event_title is not null then
      insert into public.order_tracking_events(order_id,event_key,title,description,source,metadata)
      values(p_id,'order_'||p_status,event_title,event_description,'admin',jsonb_build_object(
        'tracking_number',tracking,'carrier',carrier_name,'tracking_url',link,'manual_confirmation',true))
      on conflict(order_id,event_key) where event_key in ('payment_confirmed','supplier_approved','supplier_ordered',
        'received_by_agent','quality_control','ready_to_ship','order_shipped','order_delivered','order_cancelled') do nothing;
    end if;
    email_kind:=case p_status when 'processing' then 'order_processing' when 'shipped' then 'order_shipped'
      when 'delivered' then 'order_delivered' when 'cancelled' then 'order_cancelled' end;
  end if;
  return jsonb_build_object('updated',true,'status_changed',changed,'notification_kind',email_kind,'updated_at',saved.updated_at);
end $$;

-- Preserve the old signature, but never a second less-protected mutation path.
create or replace function public.admin_update_order(p_actor uuid,p_id uuid,p_status text,p_tracking text,p_expected timestamptz)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare o public.orders;
begin
  perform private.assert_admin(p_actor);
  select * into o from public.orders where id=p_id for update;
  if not found then raise exception 'Order not found'; end if;
  return public.admin_update_order_fulfillment(p_actor,p_id,p_status,p_tracking,o.carrier,o.tracking_url,p_expected);
end $$;
revoke all on function public.admin_update_order_fulfillment(uuid,uuid,text,text,text,text,timestamptz),
  public.admin_update_order(uuid,uuid,text,text,timestamptz) from public,anon,authenticated;
grant execute on function public.admin_update_order_fulfillment(uuid,uuid,text,text,text,text,timestamptz),
  public.admin_update_order(uuid,uuid,text,text,timestamptz) to service_role;
commit;
