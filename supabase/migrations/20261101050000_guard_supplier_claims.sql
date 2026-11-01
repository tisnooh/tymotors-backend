-- The admin form records a manual workflow. It cannot assert a live agent API
-- connection, and a supplier approval must be backed by complete order data.
create or replace function private.guard_supplier_claims()
returns trigger language plpgsql security invoker set search_path = '' as $$
declare v_order public.orders%rowtype;
begin
  if new.agent_connection_status = 'connected' then
    raise exception 'Agent API connection requires a verified integration mapping';
  end if;

  if new.status in ('approved','ordered','received_by_agent','quality_control','ready_to_ship') then
    select * into v_order from public.orders where id = new.order_id;
    if not found or v_order.is_test is distinct from false
      or v_order.payment_status is distinct from 'paid'
      or v_order.requires_compatibility_review is distinct from false then
      raise exception 'Paid non-test order with confirmed compatibility required before supplier approval';
    end if;

    if not exists (select 1 from public.supplier_order_items where supplier_order_id = new.id)
      or exists (
        select 1 from public.supplier_order_items i
        left join public.product_supplier_data s on s.product_id = i.product_id
        left join public.products p on p.id = i.product_id
        left join public.order_items oi on oi.id = i.order_item_id
        where i.supplier_order_id = new.id and (
          nullif(btrim(coalesce(i.supplier_name,'')),'') is null
          or nullif(btrim(coalesce(i.supplier_reference,'')),'') is null
          or nullif(btrim(coalesce(i.exact_source_url,'')),'') is null
          or i.exact_source_url !~* '^https://[^[:space:]]+$'
          or i.unit_cost_cents is null
          or s.supplier_verified is distinct from true
          or nullif(btrim(coalesce(s.supplier_reference,'')),'') is null
          or i.supplier_reference is distinct from s.supplier_reference
          or s.cost_price_cents is null or s.shipping_cost_cents is null
          or p.is_verified is distinct from true
          or oi.compatibility_result->>'status' is distinct from 'compatible'
          or not exists (
            select 1 from public.product_compatibilities c
            where c.product_id = i.product_id and c.verification_state = 'verified'
          )
        )
      ) then
      raise exception 'Supplier reference, price, shipping and fitment evidence required before approval';
    end if;
  end if;
  return new;
end $$;

create trigger guard_supplier_claims_before_write
before insert or update of status,agent_connection_status on public.supplier_orders
for each row execute function private.guard_supplier_claims();

revoke all on function private.guard_supplier_claims() from public,anon,authenticated;
grant execute on function private.guard_supplier_claims() to service_role;
