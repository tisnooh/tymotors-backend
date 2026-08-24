-- Cloudinary uses c_fill to present generation images in a consistent 16:9
-- frame. CC BY and CC BY-SA require modified versions to be identified.

update public.vehicle_generations
set image_attribution = image_attribution || ' — image recadrée pour l’affichage',
    updated_at = now()
where image_verified
  and image_rights_basis in ('cc-by', 'cc-by-sa')
  and image_attribution is not null
  and image_attribution not like '%image recadrée pour l’affichage%';
