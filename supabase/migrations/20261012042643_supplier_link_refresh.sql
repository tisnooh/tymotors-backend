-- Explicit repair of missing procurement links only; no purchasing or approval.
begin;

create function public.admin_refresh_supplier_links(p_actor uuid,p_order_id uuid,p_expected timestamptz)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  current_row public.supplier_orders%rowtype;
  order_row public.orders%rowtype;
  refreshed integer;
begin
  perform private.assert_admin(p_actor);
  select * into strict current_row from public.supplier_orders where order_id=p_order_id for update;
  if p_expected is null or current_row.updated_at<>p_expected then
    raise exception 'Supplier order changed; reload before saving';
  end if;
  select * into strict order_row from public.orders where id=p_order_id for update;
  if current_row.status not in ('pending_validation','requires_attention')
     or current_row.approved_at is not null or current_row.ordered_at is not null
     or nullif(trim(current_row.alibaba_order_id),'') is not null
     or nullif(trim(current_row.agent_order_id),'') is not null
     or order_row.payment_status<>'paid'
     or order_row.status in ('cancelled','refunded')
     or order_row.fulfillment_status in ('shipped','delivered','cancelled') then
    raise exception 'Supplier links can only be refreshed before approval and purchase';
  end if;

  update public.supplier_order_items i set exact_source_url=trim(s.exact_source_url)
  from public.product_supplier_data s
  where i.supplier_order_id=current_row.id and i.product_id=s.product_id
    and nullif(trim(i.exact_source_url),'') is null
    and trim(s.exact_source_url) ~ '^https://[^/[:space:]@]+/[^[:space:]]+$';
  get diagnostics refreshed = row_count;

  if refreshed>0 then
    update public.supplier_orders set updated_at=now() where id=current_row.id;
    insert into public.admin_audit(admin_user_id,action,resource,metadata)
    values(p_actor,'supplier_order.refresh_links',p_order_id::text,
      jsonb_build_object('refreshed',refreshed,'supplier_order_id',current_row.id));
  end if;
  return jsonb_build_object('refreshed',refreshed);
end $$;

revoke all on function public.admin_refresh_supplier_links(uuid,uuid,timestamptz) from public,anon,authenticated;
grant execute on function public.admin_refresh_supplier_links(uuid,uuid,timestamptz) to service_role;

commit;
