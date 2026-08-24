-- Record the provenance and commercial-use basis of every configurator image.
-- A vehicle image cannot be marked as verified without a source and an
-- explicit rights basis suitable for an ecommerce storefront.

alter table public.vehicle_generations
  add column image_source_url text,
  add column image_rights_basis text,
  add column image_attribution text,
  add column image_verified_at timestamptz;

alter table public.vehicle_generations
  add constraint vehicle_generation_verified_image_has_provenance
  check (
    not image_verified
    or (
      stage_image_url is not null
      and image_source_url is not null
      and image_rights_basis in (
        'owned',
        'supplier-authorization',
        'explicit-permission',
        'cc0',
        'cc-by',
        'cc-by-sa'
      )
      and image_verified_at is not null
    )
  );

comment on column public.vehicle_generations.image_source_url is
  'Public source or evidence URL used to audit the image provenance.';
comment on column public.vehicle_generations.image_rights_basis is
  'Commercial-use basis: owned, supplier authorization, explicit permission, or an accepted Creative Commons license.';
comment on column public.vehicle_generations.image_attribution is
  'Credit displayed with the image when its license requires attribution.';

