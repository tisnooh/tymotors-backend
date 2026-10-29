-- Keep quoted variant orders out of the legacy product-level payment/fulfillment
-- path. No data rewrite, live enablement, ACL expansion or supplier transmission.
begin;
do $isolate$
declare definition text; anchor text; occurrences integer;
begin
  select pg_get_functiondef('public.complete_paid_order(uuid,text,text,text,jsonb,jsonb)'::regprocedure) into definition;
  anchor := 'if not found then return false; end if;';
  occurrences := (length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if occurrences <> 1 then raise exception 'Legacy payment definition drift; review quoted isolation'; end if;
  definition := replace(definition,anchor,anchor||E'\n  '||
    $guard$if o.commerce_quote_id is not null then
    raise exception 'Quoted orders require the dedicated commerce payment workflow';
  end if;$guard$);
  execute definition;

  select pg_get_functiondef('private.ensure_supplier_order(uuid)'::regprocedure) into definition;
  anchor := '  insert into public.supplier_orders(order_id)';
  occurrences := (length(definition)-length(replace(definition,anchor,'')))/length(anchor);
  if occurrences <> 1 then raise exception 'Legacy supplier definition drift; review quoted isolation'; end if;
  definition := replace(definition,anchor,
    $guard$  if exists(select 1 from public.orders where id=p_order_id and commerce_quote_id is not null) then
    raise exception 'Quoted orders require dedicated snapshot fulfillment';
  end if;
$guard$||anchor);
  execute definition;
end $isolate$;
-- CREATE OR REPLACE preserves the existing identities, security attributes,
-- search_path and ACLs obtained through pg_get_functiondef; no new function.
commit;
