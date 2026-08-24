-- Complete the staging configurator with exact-generation vehicle photography.
-- Every source below explicitly permits commercial reuse (CC0, CC BY, or
-- CC BY-SA). Attribution and the original Commons description URL remain
-- visible in the storefront.

with licensed_images (
  brand_slug,
  model_slug,
  generation_slug,
  public_id,
  alt_text,
  source_url,
  rights_basis,
  attribution
) as (
  values
    (
      'bmw', 'serie-3', 'f30-f35', 'bmw-f30_ybbipw',
      'BMW Série 3 F30 — vue arrière trois-quarts',
      'https://commons.wikimedia.org/wiki/File:2016_BMW_320i_(F30_LCI_Indonesia)_looking_from_back_left_side.jpg',
      'cc-by', 'Photo : VulcanSphere — CC BY 4.0'
    ),
    (
      'bmw', 'serie-4', 'f32-f36', 'bmw-f32_vhoyye',
      'BMW Série 4 F32 — vue avant',
      'https://commons.wikimedia.org/wiki/File:BMW_435i_Coup%C3%A9_Sport_(F32)_front.JPG',
      'cc0', 'Photo : Tokumeigakarinoaoshima — CC0 1.0'
    ),
    (
      'bmw', 'serie-3', 'g20', 'bmw-g20_cr4ypq',
      'BMW Série 3 G20 noire — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:BMW_3_SERIES_SEDAN_(G20)_China.jpg',
      'cc-by-sa', 'Photo : Dinkun Chen — CC BY-SA 4.0'
    ),
    (
      'audi', 'a4', 'b9', 'audi-a4-b9_gn3di9',
      'Audi A4 B9 rouge — vue arrière trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Audi_A4_B9_sedans_(FL)_1X7A6817.jpg',
      'cc-by-sa', 'Photo : Alexander-93 — CC BY-SA 4.0'
    ),
    (
      'mercedes-benz', 'classe-c', 'w205', 'mercedes-w205_j7xc2r',
      'Mercedes-Benz Classe C W205 grise — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Mercedes-Benz_W205_C180_2021.jpg',
      'cc-by-sa', 'Photo : Ethan Llamas — CC BY-SA 4.0'
    ),
    (
      'mercedes-benz', 'classe-a', 'w177', 'mercedes-w177_b9owig',
      'Mercedes-Benz Classe A W177 grise — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Mercedes-Benz_W177_(2022)_1X7A6957.jpg',
      'cc-by-sa', 'Photo : Alexander-93 — CC BY-SA 4.0'
    ),
    (
      'volkswagen', 'golf-7', 'r', 'vw-golf-7-r_poh3yf',
      'Volkswagen Golf VII R jaune — vue arrière trois-quarts',
      'https://commons.wikimedia.org/wiki/File:2017_Volkswagen_Golf_R_TSi.jpg',
      'cc-by-sa', 'Photo : Calreyn88 — CC BY-SA 4.0'
    ),
    (
      'porsche', '911', '991', 'porsche-991_zj3hs8',
      'Porsche 911 type 991 grise — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:2013_Porsche_911_Carrera_4S_(991)_(9626546987).jpg',
      'cc-by-sa', 'Photo : David Villarreal Fernández — CC BY-SA 2.0'
    ),
    (
      'porsche', '911', '992', 'porsche-992_inmide',
      'Porsche 911 type 992 blanche — vue arrière trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Porsche_992_Turbo_S_1X7A0413.jpg',
      'cc-by-sa', 'Photo : Alexander Migl — CC BY-SA 4.0'
    ),
    (
      'porsche', 'cayenne', '9ya', 'porsche-cayenne-9ya_l7zuwo',
      'Porsche Cayenne 9YA noir — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Porsche_Cayenne_(9YA)_Miami_Metro_Area,_USA.jpg',
      'cc-by', 'Photo : OWS Photography — CC BY 4.0'
    ),
    (
      'toyota', 'gr-supra', 'a90', 'toyota-supra-a90_s2en18',
      'Toyota GR Supra A90 grise — vue avant',
      'https://commons.wikimedia.org/wiki/File:2019_Toyota_GR_Supra_A90.jpg',
      'cc-by-sa', 'Photo : Calreyn88 — CC BY-SA 4.0'
    ),
    (
      'toyota', 'gr-yaris', 'xp210', 'toyota-gr-yaris-xp210_w9zurf',
      'Toyota GR Yaris XP210 blanche — vue avant trois-quarts',
      'https://commons.wikimedia.org/wiki/File:Toyota_GR_Yaris_RZ_1X7A0252.jpg',
      'cc-by-sa', 'Photo : Alexander Migl — CC BY-SA 4.0'
    )
)
update public.vehicle_generations vg
set stage_image_url = 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto,c_fill,g_auto,w_1600,h_900/' || li.public_id,
    stage_image_alt = li.alt_text,
    image_source_url = li.source_url,
    image_rights_basis = li.rights_basis,
    image_attribution = li.attribution,
    image_verified = true,
    image_verified_at = now(),
    updated_at = now()
from licensed_images li
join public.brands b on b.slug = li.brand_slug
join public.vehicle_models vm on vm.brand_id = b.id and vm.slug = li.model_slug
where vg.vehicle_model_id = vm.id
  and vg.slug = li.generation_slug;

do $$
declare
  verified_count integer;
begin
  select count(*) into verified_count
  from public.vehicle_generations
  where image_verified;

  if verified_count <> 14 then
    raise exception 'Expected 14 verified generation images after migration, got %', verified_count;
  end if;
end;
$$;
