-- Preserve promotion reservations until unpaid Stripe sessions actually expire.
-- Forbid regression from shipped to processing/cancelled.
create or replace function public.admin_update_order(p_actor uuid,p_id uuid,p_status text,p_tracking text,p_expected timestamptz)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype;
begin
  perform private.assert_admin(p_actor);
  select * into strict o from public.orders where id=p_id for update;
  if p_expected is null or o.updated_at<>p_expected then raise exception 'Order changed. Reload before saving.' using errcode='40001'; end if;
  if p_status<>o.fulfillment_status::text then
    if o.fulfillment_status in ('cancelled','delivered') then raise exception 'This order is closed'; end if;
    if o.fulfillment_status='shipped' and p_status<>'delivered' then raise exception 'Invalid transition'; end if;
    if p_status in ('processing','shipped','delivered') and o.payment_status<>'paid' then raise exception 'Payment required'; end if;
    if p_status='delivered' and o.fulfillment_status<>'shipped' then raise exception 'Ship the order first'; end if;
    if p_status='shipped' and (o.fulfillment_status not in ('unfulfilled','processing','requires_review') or nullif(trim(p_tracking),'') is null) then raise exception 'Tracking number required'; end if;
    if p_status='cancelled' and o.fulfillment_status='shipped' then raise exception 'Use a return for shipped orders'; end if;
    if p_status not in ('processing','shipped','delivered','cancelled','requires_review') then raise exception 'Invalid transition'; end if;
  end if;
  update public.orders set fulfillment_status=p_status::public.fulfillment_status,tracking_number=nullif(trim(p_tracking),''),
    status=case when p_status='cancelled' then 'cancelled'::public.order_status else status end,
    shipped_at=case when p_status='shipped' then coalesce(shipped_at,now()) else shipped_at end,
    delivered_at=case when p_status='delivered' then coalesce(delivered_at,now()) else delivered_at end
  where id=p_id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,'order.update',p_id::text,jsonb_build_object('before',jsonb_build_object('status',o.fulfillment_status,'tracking',o.tracking_number),
    'after',jsonb_build_object('status',p_status,'tracking',p_tracking)));
  return jsonb_build_object('updated',true);
end $$;

create or replace function public.apply_order_promotion(p_order_id uuid,p_code text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare o public.orders%rowtype; p public.promotions%rowtype; eligible bigint; discount integer; uses integer;
begin
  select * into strict o from public.orders where id=p_order_id for update;
  if o.status<>'pending' or o.stripe_session_id is not null or o.promotion_id is not null then raise exception 'Order cannot accept a promotion'; end if;
  select * into strict p from public.promotions where code=p_code for update;
  if not p.active or (p.starts_at is not null and p.starts_at>now()) or (p.ends_at is not null and p.ends_at<=now()) or o.subtotal_cents<p.minimum_amount_cents then
    raise exception 'Promotion unavailable for this order';
  end if;
  select count(*) into uses from public.orders where promotion_id=p.id and (stock_applied_at is not null or status='pending' or (payment_status='unpaid' and stripe_session_id is not null));
  if p.max_uses is not null and uses>=p.max_uses then raise exception 'Promotion usage limit reached'; end if;
  select coalesce(sum(i.quantity*i.unit_amount_cents),0) into eligible from public.order_items i join public.products product on product.id=i.product_id
  where i.order_id=o.id and ((cardinality(p.product_ids)=0 and cardinality(p.category_ids)=0) or product.id=any(p.product_ids) or product.category_id=any(p.category_ids));
  discount := least(eligible,case when p.discount_type='percent' then floor(eligible*p.value/100.0)::integer else p.value end);
  if discount<=0 then raise exception 'No eligible products'; end if;
  update public.orders set promotion_id=p.id,discount_amount_cents=discount,total_cents=total_cents-discount where id=o.id;
  return jsonb_build_object('discount_cents',discount,'promotion_id',p.id);
end $$;

notify pgrst, 'reload schema';
