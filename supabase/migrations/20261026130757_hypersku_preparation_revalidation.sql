-- A saved internal packet is history, never perpetual authority to fulfill.
-- Additive local-only change; no provider transport, upload, payment or live gate.
begin;
do $amend$
declare definition text;
  early_return text := $old$  if found then
    if existing.mapping_id<>p_mapping_id then raise exception 'Prepared mapping cannot be replaced'; end if;
    return to_jsonb(existing);
  end if;
  if t.state<>'prepared' then raise exception 'Task already in simulated processing'; end if;$old$;
  current_check text := $new$  if found and existing.mapping_id<>p_mapping_id then
    raise exception 'Prepared mapping cannot be replaced';
  end if;
  if existing.id is null and t.state<>'prepared' then
    raise exception 'Task already in simulated processing';
  end if;$new$;
  validation text := $checks$
  -- This also runs on replay, under the existing order/task/source locks.
  -- Preparing an internal review packet does NOT clear the order's review flag.
  -- Sandbox orders intentionally require human review until a later approved
  -- workflow; no supplier transmission or expense is enabled here.
  if offer_row.verification_state<>'verified' or offer_row.availability<>'available'
    or offer_row.valid_until is null or offer_row.valid_until<=clock_timestamp()
    or offer_row.available_quantity is null or offer_row.available_quantity<t.quantity
    or rate_row.verification_state<>'verified' or rate_row.valid_until is null
    or rate_row.valid_until<=clock_timestamp()
    or (offer_row.currency<>'EUR' and (offer_row.fx_valid_until is null
      or offer_row.fx_valid_until<=clock_timestamp())) then
    raise exception 'Provider availability or source terms expired; human review required';
  end if;
  if not exists(select 1 from public.products p join public.product_variants v on v.product_id=p.id
    where v.id=t.variant_id and p.status='active' and p.is_verified
      and v.status='active' and v.is_verified and v.evidence_ref is not null
      and exists(select 1 from public.commerce_quotes q
        where q.id=ord.commerce_quote_id and exists(
          select 1 from jsonb_array_elements(q.source_context->'variants') frozen
          where frozen->>'id'=v.id::text
            and (frozen-array['stock','price_cents','updated_at'])
              = (to_jsonb(v)-array['stock','price_cents','updated_at'])
        ))) then
    raise exception 'Variant identity or verification changed; human review required';
  end if;
  -- Reuse the fitment facts authenticated at quote time. Any change to these
  -- facts requires review, not a new inferred compatibility or repriced order.
  if exists(select 1 from public.product_variants v join public.commerce_quotes q on q.id=ord.commerce_quote_id
    where v.id=t.variant_id and v.requires_vehicle and (
      coalesce((select jsonb_agg(to_jsonb(vc) order by vc.compatibility_id)
        from public.variant_compatibilities vc where vc.variant_id=v.id),'[]'::jsonb)
        is distinct from coalesce((select jsonb_agg(frozen order by frozen->>'compatibility_id')
          from jsonb_array_elements(q.source_context->'links') frozen
          where frozen->>'variant_id'=v.id::text),'[]'::jsonb)
      or not exists(select 1 from public.variant_compatibilities vc where vc.variant_id=v.id)
      or exists(select 1 from public.variant_compatibilities vc
        join public.product_compatibilities c on c.id=vc.compatibility_id
        where vc.variant_id=v.id and (
          c.verification_state<>'verified' or not exists(
            select 1 from jsonb_array_elements(q.source_context->'compatibilities') frozen
            where frozen->>'id'=c.id::text and frozen=to_jsonb(c)
          )
          or not exists(select 1 from public.brands b where b.id=c.brand_id and exists(
            select 1 from jsonb_array_elements(q.source_context->'brands') frozen
            where frozen->>'id'=b.id::text and frozen=to_jsonb(b)
          ))
          or (c.vehicle_model_id is not null and not exists(
            select 1 from public.vehicle_models model where model.id=c.vehicle_model_id and exists(
              select 1 from jsonb_array_elements(q.source_context->'models') frozen
              where frozen->>'id'=model.id::text and frozen=to_jsonb(model)
            )
          ))
          or (c.generation_id is not null and not exists(
            select 1 from public.vehicle_generations gen where gen.id=c.generation_id and exists(
              select 1 from jsonb_array_elements(q.source_context->'generations') frozen
              where frozen->>'id'=gen.id::text and frozen=to_jsonb(gen)
            )
          ))
        ))
    )) then
    raise exception 'Vehicle compatibility changed; human review required';
  end if;
  if existing.id is not null then
    if existing.mapping_snapshot is distinct from to_jsonb(m) then
      raise exception 'Prepared provider mapping changed; human review required';
    end if;
    return to_jsonb(existing);
  end if;
$checks$;
begin
  select pg_get_functiondef('public.commerce_prepare_hypersku_task(uuid,uuid,uuid)'::regprocedure) into definition;
  if strpos(definition,early_return)=0
    or strpos(definition,'  packet:=jsonb_build_object(')=0 then
    raise exception 'Review HyperSKU preparation definition before revalidation amendment';
  end if;
  definition:=replace(definition,early_return,current_check);
  definition:=replace(definition,'  packet:=jsonb_build_object(',validation||'  packet:=jsonb_build_object(');
  execute definition;
end $amend$;
commit;
