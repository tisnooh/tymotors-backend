-- The legacy vehicle-stage assets were removed from Cloudinary and return 404.
-- Keep every generation unverified until a replacement image has been checked.
update public.vehicle_generations
set stage_image_url = null,
    image_verified = false,
    updated_at = now()
where image_verified = false
  and stage_image_url like 'https://res.cloudinary.com/dwsyixjux/image/upload/%';
