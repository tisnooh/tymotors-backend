-- Exact Golf VII GTI side view, self-published by Overlaet under CC BY-SA 3.0.

update public.vehicle_generations vg
set stage_image_url = 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto,c_fill,g_auto,w_1600,h_900/vw-golf-7-gti-side-white_nrenlg',
    stage_image_alt = 'Volkswagen Golf VII GTI blanche — vue latérale',
    image_source_url = 'https://commons.wikimedia.org/wiki/File:Volkswagen_Golf_VII_GTI_(side)_white.JPG',
    image_rights_basis = 'cc-by-sa',
    image_attribution = 'Photo : Overlaet — CC BY-SA 3.0',
    image_verified = true,
    image_verified_at = now(),
    updated_at = now()
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where vg.vehicle_model_id = vm.id
  and b.slug = 'volkswagen'
  and vm.slug = 'golf-7'
  and vg.slug = 'gti';

