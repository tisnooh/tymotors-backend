-- Omitted tracking means retain the immutable SIM number, never erase it.
-- No real shipment/order status is changed by this additive amendment.
begin;
do $amend$
declare definition text; anchor text := '  if t.state=p_next and t.tracking_number is not distinct from p_tracking_number then';
begin
  select pg_get_functiondef('public.commerce_advance_test_task(uuid,uuid,text,text,text)'::regprocedure) into definition;
  if strpos(definition,anchor)=0 or strpos(definition,'coalesce(p_tracking_number,t.tracking_number)')>0 then
    raise exception 'Review simulated tracking retention amendment';
  end if;
  execute replace(definition,anchor,
    '  p_tracking_number:=coalesce(p_tracking_number,t.tracking_number);' || E'\n' || anchor);
end $amend$;
commit;
