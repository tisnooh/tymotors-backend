-- Exact Audi A3 8V Sportback side view. The original is self-published by
-- Overlaet under CC BY-SA 3.0; the storefront displays the attribution and
-- links back to the Commons description page.

update public.vehicle_generations vg
set stage_image_url = 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto,c_fill,g_auto,w_1600,h_900/audi-a3-8v-side_ng3d7a',
    stage_image_alt = 'Audi A3 Sportback 8V rouge — vue latérale',
    image_source_url = 'https://commons.wikimedia.org/wiki/File:Audi_A3_Sportback_8V_(side).JPG',
    image_rights_basis = 'cc-by-sa',
    image_attribution = 'Photo : Overlaet — CC BY-SA 3.0',
    image_verified = true,
    image_verified_at = now(),
    updated_at = now()
from public.vehicle_models vm
join public.brands b on b.id = vm.brand_id
where vg.vehicle_model_id = vm.id
  and b.slug = 'audi'
  and vm.slug = 'a3'
  and vg.slug = '8v';

