-- Positive per-file permission, not a photo edit or a commercial approval.
begin;
create table public.commerce_image_permissions (
  id uuid primary key default gen_random_uuid(),
  product_id uuid not null references public.products(id) on delete restrict,
  image_url text not null check(length(image_url) between 9 and 2000 and image_url ~ '^https://'),
  state text not null default 'pending' check(state in ('pending','verified','refused','revoked')),
  evidence_ref text check(length(btrim(evidence_ref)) between 1 and 2000),
  commercial_use boolean not null default false,
  derivatives_use boolean not null default false,
  product_match_confirmed boolean not null default false,
  marks_clearance text not null default 'unknown' check(marks_clearance in ('unknown','not_present','verified')),
  countries text[] not null default '{}',
  valid_until timestamptz,
  verified_by uuid references public.profiles(id) on delete restrict,
  verified_at timestamptz,
  created_at timestamptz not null default clock_timestamp(),
  updated_at timestamptz not null default clock_timestamp(),
  unique(product_id,image_url),
  check(cardinality(countries)<=250 and array_position(countries,null) is null),
  check(state<>'verified' or (evidence_ref is not null and commercial_use and derivatives_use and product_match_confirmed
    and marks_clearance in ('not_present','verified') and cardinality(countries)>0
    and valid_until is not null and verified_by is not null and verified_at is not null))
);
create index commerce_image_permissions_product on public.commerce_image_permissions(product_id);
create trigger commerce_image_permissions_updated before update on public.commerce_image_permissions
for each row execute function public.set_updated_at();

create function public.commerce_save_image_permission(p_actor uuid,p_data jsonb,p_expected timestamptz default null)
returns jsonb language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare r public.commerce_image_permissions; d public.commerce_image_permissions; key text;
begin
  perform private.assert_admin(p_actor);
  if jsonb_typeof(p_data) is distinct from 'object' then raise exception 'Image permission object required'; end if;
  for key in select jsonb_object_keys(p_data) loop
    if key not in ('product_id','image_url','state','evidence_ref','commercial_use','derivatives_use','product_match_confirmed','marks_clearance','countries','valid_until')
      then raise exception 'Unknown image permission field'; end if;
  end loop;
  d:=jsonb_populate_record(null::public.commerce_image_permissions,
    '{"state":"pending","commercial_use":false,"derivatives_use":false,"product_match_confirmed":false,"marks_clearance":"unknown","countries":[]}'::jsonb||p_data);
  if not exists(select 1 from public.product_images where product_id=d.product_id and url=d.image_url)
    then raise exception 'Permission must identify an existing exact image'; end if;
  if exists(select 1 from unnest(d.countries) c where c !~ '^[A-Z]{2}$') then raise exception 'Explicit country codes required'; end if;
  if d.state='verified' and (d.valid_until is null or d.valid_until<=clock_timestamp()) then raise exception 'Unexpired image grant required'; end if;
  -- Same source barrier as quote/claim; no remote request under these locks.
  perform private.lock_commerce_quote_sources();
  perform private.assert_admin(p_actor);
  if not exists(select 1 from public.product_images where product_id=d.product_id and url=d.image_url)
    then raise exception 'Permission must identify an existing exact image'; end if;
  select * into r from public.commerce_image_permissions where product_id=d.product_id and image_url=d.image_url for update;
  if found then
    if p_expected is null or r.updated_at<>p_expected then raise exception 'Image permission changed; reload'; end if;
    update public.commerce_image_permissions set state=d.state,evidence_ref=d.evidence_ref,commercial_use=d.commercial_use,
      derivatives_use=d.derivatives_use,product_match_confirmed=d.product_match_confirmed,marks_clearance=d.marks_clearance,
      countries=d.countries,valid_until=d.valid_until,verified_by=case when d.state='verified' then p_actor end,
      verified_at=case when d.state='verified' then clock_timestamp() end where id=r.id returning * into r;
  else
    if p_expected is not null then raise exception 'Image permission does not exist'; end if;
    insert into public.commerce_image_permissions(product_id,image_url,state,evidence_ref,commercial_use,derivatives_use,
      product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
    values(d.product_id,d.image_url,d.state,d.evidence_ref,d.commercial_use,d.derivatives_use,d.product_match_confirmed,
      d.marks_clearance,d.countries,d.valid_until,case when d.state='verified' then p_actor end,
      case when d.state='verified' then clock_timestamp() end) returning * into r;
  end if;
  insert into public.admin_audit(admin_user_id,action,resource,metadata) values(p_actor,'commerce.image.permission',r.id::text,
    jsonb_build_object('state',r.state,'product_id',r.product_id,'evidence_ref',r.evidence_ref));
  return to_jsonb(r);
end $$;

-- Add rights to the existing context and lock barrier. Do not duplicate the
-- cart owner checks or change return contracts silently if upstream drifts.
do $amend$ declare definition text; begin
  select pg_get_functiondef('public.commerce_cart_context(uuid,uuid,text,text,text,text)'::regprocedure) into definition;
  if strpos(definition,'return result;')=0 or strpos(definition,'''image_permissions''')>0 then raise exception 'Review context rights amendment'; end if;
  definition:=replace(definition,'return result;',
    'result:=result||jsonb_build_object(''image_permissions'',coalesce((select jsonb_agg(to_jsonb(t) order by id) from public.commerce_image_permissions t where product_id in(select product_id from public.cart_items where cart_id=p_cart_id)),''[]''::jsonb)); return result;');
  execute definition;
  select pg_get_functiondef('private.lock_commerce_quote_sources()'::regprocedure) into definition;
  if strpos(definition,'public.vehicle_models,public.vehicle_generations in exclusive mode nowait')=0 then raise exception 'Review source lock rights amendment'; end if;
  execute replace(definition,'public.vehicle_models,public.vehicle_generations in exclusive mode nowait',
    'public.vehicle_models,public.vehicle_generations,public.commerce_image_permissions in exclusive mode nowait');
end $amend$;

create function private.check_commerce_image_permissions(p_source jsonb,p_deadline timestamptz) returns void
language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare product uuid; image jsonb; grant_row jsonb;
begin
  if jsonb_typeof(p_source->'image_permissions') is distinct from 'array' or jsonb_typeof(p_source->'product_images') is distinct from 'array'
    then raise exception 'Positive image permissions required'; end if;
  for product in select distinct (x->>'product_id')::uuid from jsonb_array_elements(p_source->'cart_items') x loop
    if not exists(select 1 from jsonb_array_elements(p_source->'product_images') x where (x->>'product_id')::uuid=product)
      then raise exception 'An authorized product image is required'; end if;
    for image in select value from jsonb_array_elements(p_source->'product_images') where (value->>'product_id')::uuid=product loop
      if coalesce(image->>'url','')='' or image->>'url' ~* '^https://(www[.])?scpautomotive[.]co[.]uk/'
        or image->>'url' ~* '(hvtqoa2mfv40mn2gy1ww|ckvfckn89wcdd9fzaegj|o5ylil1cryn4uertnc89|BMW-LED-Door-Projector-_Pair_-BMW-Logo-SCP-Automotive-90141840)'
        then raise exception 'Known refused image source cannot be authorized'; end if;
      select x into grant_row from jsonb_array_elements(p_source->'image_permissions') x
        where (x->>'product_id')::uuid=product and x->>'image_url'=image->>'url';
      if grant_row is null or grant_row->>'state' is distinct from 'verified'
        or grant_row->'commercial_use' is distinct from 'true'::jsonb or grant_row->'derivatives_use' is distinct from 'true'::jsonb
        or grant_row->'product_match_confirmed' is distinct from 'true'::jsonb
        or coalesce(grant_row->>'marks_clearance','unknown') not in ('verified','not_present')
        or coalesce(btrim(grant_row->>'evidence_ref'),'')='' or grant_row->>'verified_by' is null or grant_row->>'verified_at' is null
        or (grant_row->>'verified_at')::timestamptz>clock_timestamp()
        or grant_row->>'valid_until' is null or (grant_row->>'valid_until')::timestamptz<p_deadline
        or not coalesce((grant_row->'countries') ? (p_source->>'country'),false)
        then raise exception 'Image commercial rights not confirmed for destination and duration'; end if;
    end loop;
  end loop;
end $$;

alter function private.check_commerce_quote_payload(jsonb,jsonb,timestamptz) rename to check_commerce_quote_payload_before_rights;
create function private.check_commerce_quote_payload(p_source jsonb,p_payload jsonb,p_deadline timestamptz)
returns timestamptz language plpgsql security invoker set search_path='' set timezone='UTC' as $$
declare valid timestamptz; expiry timestamptz;
begin
  valid:=private.check_commerce_quote_payload_before_rights(p_source,p_payload,p_deadline);
  perform private.check_commerce_image_permissions(p_source,p_deadline);
  select min((x->>'valid_until')::timestamptz) into expiry
    from jsonb_array_elements(p_source->'image_permissions') x
    where exists(select 1 from jsonb_array_elements(p_source->'product_images') i
      where i->>'product_id'=x->>'product_id' and i->>'url'=x->>'image_url');
  -- Saving clamps the quote to this grant expiry (and the existing 45m cap).
  -- Claim later rechecks every grant through that frozen expiry, not a new TTL.
  return least(valid,expiry);
end $$;

alter table public.commerce_image_permissions enable row level security;
revoke all on public.commerce_image_permissions from public,anon,authenticated,service_role;
grant select,insert,update on public.commerce_image_permissions to service_role;
revoke all on function public.commerce_save_image_permission(uuid,jsonb,timestamptz),
  private.check_commerce_image_permissions(jsonb,timestamptz),private.check_commerce_quote_payload(jsonb,jsonb,timestamptz),
  private.check_commerce_quote_payload_before_rights(jsonb,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function public.commerce_save_image_permission(uuid,jsonb,timestamptz),
  private.check_commerce_image_permissions(jsonb,timestamptz),private.check_commerce_quote_payload(jsonb,jsonb,timestamptz),
  private.check_commerce_quote_payload_before_rights(jsonb,jsonb,timestamptz) to service_role;
commit;
