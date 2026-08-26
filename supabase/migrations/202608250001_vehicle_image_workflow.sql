-- Track source and final configurator assets without losing provenance.
-- Rights review is independent from visual verification so staging can use a
-- candidate while production release remains an explicit human decision.

alter table public.vehicle_generations
  add column if not exists image_rights_status text not null default 'REQUIRES_MANUAL_REVIEW',
  add column if not exists image_cloudinary_public_id text,
  add column if not exists image_original_filename text;

alter table public.vehicle_generations
  drop constraint if exists vehicle_generation_verified_image_has_provenance;

alter table public.vehicle_generations
  add constraint vehicle_generation_image_rights_status_valid
  check (image_rights_status in ('APPROVED', 'REQUIRES_MANUAL_REVIEW'));

alter table public.vehicle_generations
  add constraint vehicle_generation_verified_image_has_provenance
  check (
    not image_verified
    or (
      stage_image_url is not null
      and image_source_url is not null
      and image_rights_status in ('APPROVED', 'REQUIRES_MANUAL_REVIEW')
      and image_verified_at is not null
    )
  );

create table if not exists public.vehicle_images (
  id uuid primary key default gen_random_uuid(),
  generation_id uuid not null references public.vehicle_generations(id) on delete cascade,
  asset_role text not null check (asset_role in ('source', 'final')),
  view_type text not null default 'front_three_quarter',
  cloudinary_url text,
  cloudinary_public_id text,
  source_url text,
  source_name text,
  original_filename text not null,
  rights_status text not null default 'REQUIRES_MANUAL_REVIEW'
    check (rights_status in ('APPROVED', 'REQUIRES_MANUAL_REVIEW')),
  rights_basis text,
  verification_status text not null default 'candidate'
    check (verification_status in ('candidate', 'approved', 'rejected')),
  is_current boolean not null default false,
  transformation_ai boolean not null default false,
  width integer check (width is null or width > 0),
  height integer check (height is null or height > 0),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists vehicle_images_current_final_idx
  on public.vehicle_images(generation_id)
  where asset_role = 'final' and is_current;
create index if not exists vehicle_images_generation_idx
  on public.vehicle_images(generation_id, asset_role);
create index if not exists vehicle_images_rights_review_idx
  on public.vehicle_images(rights_status, verification_status);

alter table public.vehicle_images enable row level security;

drop policy if exists admin_select_vehicle_images on public.vehicle_images;
drop policy if exists admin_insert_vehicle_images on public.vehicle_images;
drop policy if exists admin_update_vehicle_images on public.vehicle_images;
drop policy if exists admin_delete_vehicle_images on public.vehicle_images;

create policy admin_select_vehicle_images on public.vehicle_images
  for select to authenticated using ((select private.is_admin()));
create policy admin_insert_vehicle_images on public.vehicle_images
  for insert to authenticated with check ((select private.is_admin()));
create policy admin_update_vehicle_images on public.vehicle_images
  for update to authenticated
  using ((select private.is_admin())) with check ((select private.is_admin()));
create policy admin_delete_vehicle_images on public.vehicle_images
  for delete to authenticated using ((select private.is_admin()));

revoke all on public.vehicle_images from anon;
grant select, insert, update, delete on public.vehicle_images to authenticated;
grant all on public.vehicle_images to service_role;

comment on table public.vehicle_images is
  'Private provenance and transformation registry for configurator source and final assets.';
comment on column public.vehicle_generations.image_rights_status is
  'APPROVED for cleared production use; REQUIRES_MANUAL_REVIEW is allowed in staging only.';

