-- Preserve compatibility identities, evidence metadata and variant associations.
-- No data backfill and no changes to image, payment or inventory semantics.
begin;

create function private.fitment_rule_content(p_value jsonb) returns jsonb
language sql immutable security invoker set search_path='' as $$
  select to_jsonb(jsonb_populate_record(null::public.product_compatibilities,
    '{"body_types":[],"facelift":"unknown","required_trims":[],"excluded_trims":[],"verification_state":"unverified"}'::jsonb || p_value))
    - array['id','product_id','created_at','updated_at','verified_at','verified_by'];
$$;

-- Replaces the latest implementation from 20260911071309_admin_backoffice.sql.
create or replace function public.admin_save_product(p_actor uuid,p_id uuid,p_expected timestamptz,p_base jsonb,p_images jsonb,p_rules jsonb,p_supplier jsonb)
returns uuid language plpgsql security invoker set search_path = '' as $$
declare
  old_p public.products%rowtype; p public.products%rowtype; rule jsonb; img jsonb; final_status public.product_status;
  current_rule public.product_compatibilities%rowtype; next_rule public.product_compatibilities%rowtype;
  rule_id uuid; matches uuid[]; resolved jsonb:='[]'; kept uuid[]:='{}'; added uuid[]:='{}'; changed uuid[]:='{}'; removed uuid[]:='{}';
  defaults jsonb:='{"body_types":[],"facelift":"unknown","required_trims":[],"excluded_trims":[],"verification_state":"unverified"}';
begin
  perform private.assert_admin(p_actor);
  if p_rules is null or jsonb_typeof(p_rules)<>'array' then raise exception 'Compatibility rules must be an array'; end if;
  if p_id is not null then
    select * into strict old_p from public.products where id=p_id for update;
    if p_expected is null or p_expected<>old_p.updated_at then raise exception 'Product changed. Reload before saving.' using errcode='40001'; end if;
    if (p_base->>'stock')::integer<>old_p.stock then raise exception 'Use inventory adjustment to change existing stock'; end if;
    perform 1 from public.product_compatibilities where product_id=p_id order by id for update;
  end if;
  p := jsonb_populate_record(null::public.products,p_base);
  p.id := coalesce(p_id,gen_random_uuid());
  final_status := p.status;

  -- Resolve every identity before changing any rule. Legacy no-ID input matches
  -- exact semantic content only; it is never assigned by list order or chassis.
  for rule in select value from jsonb_array_elements(p_rules) loop
    if jsonb_typeof(rule)<>'object' then raise exception 'Every compatibility rule must be an object'; end if;
    rule_id:=nullif(rule->>'id','')::uuid;
    if rule_id is not null then
      if p_id is null or not exists(select 1 from public.product_compatibilities where id=rule_id and product_id=p.id) then
        raise exception 'Compatibility ID does not belong to this product';
      end if;
    else
      select array_agg(c.id order by c.id) into matches from public.product_compatibilities c
        where c.product_id=p.id and private.fitment_rule_content(to_jsonb(c))=private.fitment_rule_content(rule);
      if cardinality(matches)>1 then raise exception 'Ambiguous legacy compatibility; send explicit IDs'; end if;
      rule_id:=matches[1];
    end if;
    if rule_id=any(kept) then raise exception 'Duplicate compatibility ID'; end if;
    if rule_id is null then
      if exists(select 1 from jsonb_array_elements(resolved) r where private.fitment_rule_content(r.value)=private.fitment_rule_content(rule)) then
        raise exception 'Duplicate new compatibility content';
      end if;
      rule_id:=gen_random_uuid(); added:=array_append(added,rule_id);
    end if;
    kept:=array_append(kept,rule_id);
    resolved:=resolved || jsonb_build_array(rule || jsonb_build_object('id',rule_id));
  end loop;

  perform set_config('tymotors.reason','initial_stock',true);
  insert into public.products(id,slug,sku,name,subtitle,description,category_id,subcategory,price_cents,compare_at_price_cents,
    currency,stock,status,is_verified,featured,badges,rating,review_count,specs,package_contents,installation_difficulty,
    installation_minutes,tools_required,warranty_months,delivery_estimate,legacy_compatible_brands,low_stock_threshold,tags)
  values(p.id,p.slug,p.sku,p.name,p.subtitle,p.description,p.category_id,p.subcategory,p.price_cents,p.compare_at_price_cents,
    p.currency,p.stock,'draft',p.is_verified,p.featured,p.badges,p.rating,p.review_count,p.specs,p.package_contents,p.installation_difficulty,
    p.installation_minutes,p.tools_required,p.warranty_months,p.delivery_estimate,p.legacy_compatible_brands,p.low_stock_threshold,p.tags)
  on conflict(id) do update set slug=excluded.slug,sku=excluded.sku,name=excluded.name,subtitle=excluded.subtitle,
    description=excluded.description,category_id=excluded.category_id,subcategory=excluded.subcategory,
    price_cents=excluded.price_cents,compare_at_price_cents=excluded.compare_at_price_cents,currency=excluded.currency,
    status='draft',is_verified=excluded.is_verified,featured=excluded.featured,badges=excluded.badges,
    rating=excluded.rating,review_count=excluded.review_count,specs=excluded.specs,package_contents=excluded.package_contents,
    installation_difficulty=excluded.installation_difficulty,installation_minutes=excluded.installation_minutes,
    tools_required=excluded.tools_required,warranty_months=excluded.warranty_months,delivery_estimate=excluded.delivery_estimate,
    legacy_compatible_brands=excluded.legacy_compatible_brands,low_stock_threshold=excluded.low_stock_threshold,tags=excluded.tags;
  -- Original gallery upsert behavior is intentionally unchanged.
  delete from public.product_images where product_id=p.id and url not in(select value->>'url' from jsonb_array_elements(p_images));
  for img in select value from jsonb_array_elements(p_images) loop
    insert into public.product_images(product_id,url,display_order,image_type,is_verified)
    values(p.id,img->>'url',(img->>'display_order')::integer,img->>'image_type',p.is_verified)
    on conflict(product_id,url) do update set display_order=excluded.display_order,is_verified=excluded.is_verified;
  end loop;

  select coalesce(array_agg(id order by id),'{}') into removed from public.product_compatibilities
    where product_id=p.id and not (id=any(kept));
  -- Referenced removals deliberately fail FK RESTRICT and roll back the whole save.
  delete from public.product_compatibilities where product_id=p.id and not (id=any(kept));
  for rule in select value from jsonb_array_elements(resolved) loop
    rule_id:=(rule->>'id')::uuid;
    select * into current_rule from public.product_compatibilities where id=rule_id and product_id=p.id;
    if found and private.fitment_rule_content(to_jsonb(current_rule))=private.fitment_rule_content(rule) then
      continue; -- Preserve created_at, verification evidence/actor/date and updated_at.
    end if;
    next_rule:=jsonb_populate_record(null::public.product_compatibilities,defaults || rule ||
      jsonb_build_object('id',rule_id,'product_id',p.id,'created_at',coalesce(current_rule.created_at,clock_timestamp()),
        'updated_at',clock_timestamp()));
    next_rule.verified_by:=case when next_rule.verification_state='verified' then p_actor else null end;
    next_rule.verified_at:=case when next_rule.verification_state='verified' then clock_timestamp() else null end;
    if current_rule.id is null then
      insert into public.product_compatibilities select next_rule.*;
    else
      update public.product_compatibilities set brand_id=next_rule.brand_id,vehicle_model_id=next_rule.vehicle_model_id,
        generation_id=next_rule.generation_id,model_name=next_rule.model_name,chassis=next_rule.chassis,
        generation_name=next_rule.generation_name,year_from=next_rule.year_from,year_to=next_rule.year_to,
        body_types=next_rule.body_types,facelift=next_rule.facelift,required_trims=next_rule.required_trims,
        excluded_trims=next_rule.excluded_trims,camera_compatible=next_rule.camera_compatible,
        parking_sensor_compatible=next_rule.parking_sensor_compatible,notes=next_rule.notes,
        verification_state=next_rule.verification_state,verified_by=next_rule.verified_by,verified_at=next_rule.verified_at
        where id=rule_id and product_id=p.id;
      changed:=array_append(changed,rule_id);
    end if;
  end loop;
  -- Retain supplier verification dates not edited by this form (original behavior).
  p_supplier := coalesce((select to_jsonb(s) from public.product_supplier_data s where product_id=p.id),'{}') || p_supplier;
  delete from public.product_supplier_data where product_id=p.id;
  insert into public.product_supplier_data select
    (jsonb_populate_record(null::public.product_supplier_data,
      p_supplier || jsonb_build_object('product_id',p.id,'updated_at',now()))).*;
  update public.products set status=final_status where id=p.id;
  insert into public.admin_audit(admin_user_id,action,resource,metadata)
  values(p_actor,case when p_id is null then 'product.create' else 'product.update' end,p.id::text,
    jsonb_build_object('before',jsonb_build_object('price_cents',old_p.price_cents,'status',old_p.status),
      'after',jsonb_build_object('price_cents',p.price_cents,'status',final_status),
      'compatibilities',jsonb_build_object('kept_ids',kept,'inserted_ids',added,'updated_ids',changed,'removed_ids',removed)));
  return p.id;
end $$;

revoke all on function private.fitment_rule_content(jsonb),public.admin_save_product(uuid,uuid,timestamptz,jsonb,jsonb,jsonb,jsonb) from public,anon,authenticated;
grant execute on function private.fitment_rule_content(jsonb),public.admin_save_product(uuid,uuid,timestamptz,jsonb,jsonb,jsonb,jsonb) to service_role;
commit;
