-- Install the 14 approved visual compositions after their Cloudinary upload.
-- Rights marked REQUIRES_MANUAL_REVIEW are intentionally staging-only.

with image_manifest(brand_slug, model_slug, generation_slug, source_url, source_name,
  rights_status, rights_basis, original_filename, public_id, grille_x, grille_y, cabin_x, cabin_y) as (
  values
    ('bmw','serie-3','f30-f35','https://s1.cdn.autoevolution.com/images/gallery/BMW-3-Series--F30--4412_69.jpg','autoevolution','REQUIRES_MANUAL_REVIEW','unverified','bmw-serie-3-f30-f35-configurator.png','tymotors/vehicles/bmw/serie-3/f30-f35/configurator-front-three-quarter',37.5,61.5,58.0,40.5),
    ('bmw','serie-4','f32-f36','https://s1.cdn.autoevolution.com/images/gallery/BMW-4-Series-4884_78.jpg','autoevolution','REQUIRES_MANUAL_REVIEW','unverified','bmw-serie-4-f32-f36-configurator.png','tymotors/vehicles/bmw/serie-4/f32-f36/configurator-front-three-quarter',38.0,61.0,59.0,40.0),
    ('bmw','serie-3','g20','https://commons.wikimedia.org/wiki/File:BMW_3_SERIES_SEDAN_(G20)_China.jpg','Wikimedia Commons','APPROVED','cc-by-sa','bmw-serie-3-g20-configurator.png','tymotors/vehicles/bmw/serie-3/g20/configurator-front-three-quarter',37.0,62.5,58.0,40.0),
    ('audi','a3','8v','https://www.carsinvasion.com/gallery/2014-audi-a3-sportback/2014-audi-a3-sportback-01.jpg','CarsInvasion','REQUIRES_MANUAL_REVIEW','unverified','audi-a3-8v-configurator.png','tymotors/vehicles/audi/a3/8v/configurator-front-three-quarter',38.5,61.0,58.5,41.0),
    ('audi','a4','b9','https://avtoskhemy.com/wp-content/uploads/2024/05/shema-bloku-zapobizhnikiv-audi-a4-b9-i-rele-z-priznachennyam-i-roztashuvannyam1.jpg','Avtoskhemy','REQUIRES_MANUAL_REVIEW','unverified','audi-a4-b9-configurator.png','tymotors/vehicles/audi/a4/b9/configurator-front-three-quarter',37.0,61.5,58.0,40.0),
    ('mercedes-benz','classe-a','w177','user-provided://tymotors/Image-Codex-25-aout-2026-22-34-21.png','Image TYMotors fournie par le propriétaire du projet','REQUIRES_MANUAL_REVIEW','user-provided-unverified','mercedes-classe-a-w177-configurator.png','tymotors/vehicles/mercedes-benz/classe-a/w177/configurator-front-three-quarter',38.0,62.0,57.5,41.0),
    ('mercedes-benz','classe-c','w205','https://commons.wikimedia.org/wiki/File:Mercedes-Benz_W205_C180_2021.jpg','Wikimedia Commons','APPROVED','cc-by-sa','mercedes-classe-c-w205-configurator.png','tymotors/vehicles/mercedes-benz/classe-c/w205/configurator-front-three-quarter',37.0,62.0,58.5,40.5),
    ('volkswagen','golf-7','gti','https://www.larevueautomobile.com/images/articles-md/Volkswagen/Golf-7-GTI/Exterieur/Volkswagen_Golf_7_GTI_001.jpg','La Revue Automobile','REQUIRES_MANUAL_REVIEW','unverified','volkswagen-golf-7-gti-configurator.png','tymotors/vehicles/volkswagen/golf-7/gti/configurator-front-three-quarter',38.5,63.0,58.5,42.0),
    ('volkswagen','golf-7','r','https://commons.wikimedia.org/wiki/File:2017_Volkswagen_Golf_R_TSi.jpg','Wikimedia Commons','APPROVED','cc-by-sa','volkswagen-golf-7-r-configurator.png','tymotors/vehicles/volkswagen/golf-7/r/configurator-front-three-quarter',38.0,62.0,58.0,41.0),
    ('porsche','911','991','https://commons.wikimedia.org/wiki/File:2013_Porsche_911_Carrera_4S_(991)_(9626546987).jpg','Wikimedia Commons','APPROVED','cc-by-sa','porsche-911-991-configurator.png','tymotors/vehicles/porsche/911/991/configurator-front-three-quarter',36.0,64.0,58.5,41.0),
    ('porsche','911','992','https://cdn11.bigcommerce.com/s-aw4qbuk/images/stencil/original/products/317/1482/Embargo_05_30_AM_CET_28_November_front_three_quarter-1__57654.1656700402.jpg','BigCommerce-hosted Porsche press image','REQUIRES_MANUAL_REVIEW','unverified','porsche-911-992-configurator.png','tymotors/vehicles/porsche/911/992/configurator-front-three-quarter',36.0,63.0,58.0,40.5),
    ('porsche','cayenne','9ya','https://commons.wikimedia.org/wiki/File:Porsche_Cayenne_(9YA)_Miami_Metro_Area,_USA.jpg','Wikimedia Commons','APPROVED','cc-by','porsche-cayenne-9ya-configurator.png','tymotors/vehicles/porsche/cayenne/9ya/configurator-front-three-quarter',35.5,64.0,59.0,40.0),
    ('toyota','gr-supra','a90','https://s1.paultan.org/image/2019/09/2019-A90-Toyota-GR-Supra-Malaysia-official-8.jpg','paultan.org / Toyota official image','REQUIRES_MANUAL_REVIEW','unverified','toyota-gr-supra-a90-configurator.png','tymotors/vehicles/toyota/gr-supra/a90/configurator-front-three-quarter',36.0,63.0,57.5,40.0),
    ('toyota','gr-yaris','xp210','https://commons.wikimedia.org/wiki/File:Toyota_GR_Yaris_RZ_1X7A0252.jpg','Wikimedia Commons','APPROVED','cc-by-sa','toyota-gr-yaris-xp210-configurator.png','tymotors/vehicles/toyota/gr-yaris/xp210/configurator-front-three-quarter',37.5,63.0,57.0,41.5)
), resolved as (
  select im.*, vg.id as generation_id
  from image_manifest im
  join public.brands b on b.slug = im.brand_slug
  join public.vehicle_models vm on vm.brand_id = b.id and vm.slug = im.model_slug
  join public.vehicle_generations vg on vg.vehicle_model_id = vm.id and vg.slug = im.generation_slug
)
update public.vehicle_generations vg
set stage_image_url = 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto,c_fill,g_auto,w_1600,h_900/' || r.public_id,
    stage_image_alt = r.source_name || ' — ' || r.brand_slug || ' ' || r.model_slug || ' ' || r.generation_slug || ', vue trois-quarts avant TYMotors',
    image_verified = true,
    image_source_url = r.source_url,
    image_rights_basis = r.rights_basis,
    image_rights_status = r.rights_status,
    image_cloudinary_public_id = r.public_id,
    image_original_filename = r.original_filename,
    image_attribution = case
      when r.source_name = 'Wikimedia Commons' then 'Source : Wikimedia Commons — composition TYMotors'
      else r.source_name || ' — droits à valider avant production'
    end,
    image_verified_at = now(),
    updated_at = now()
from resolved r
where vg.id = r.generation_id;

with image_manifest(brand_slug, model_slug, generation_slug, source_url, source_name,
  rights_status, rights_basis, original_filename, public_id) as (
  values
    ('bmw','serie-3','f30-f35','https://s1.cdn.autoevolution.com/images/gallery/BMW-3-Series--F30--4412_69.jpg','autoevolution','REQUIRES_MANUAL_REVIEW','unverified','bmw-serie-3-f30-f35-configurator.png','tymotors/vehicles/bmw/serie-3/f30-f35/configurator-front-three-quarter'),
    ('bmw','serie-4','f32-f36','https://s1.cdn.autoevolution.com/images/gallery/BMW-4-Series-4884_78.jpg','autoevolution','REQUIRES_MANUAL_REVIEW','unverified','bmw-serie-4-f32-f36-configurator.png','tymotors/vehicles/bmw/serie-4/f32-f36/configurator-front-three-quarter'),
    ('bmw','serie-3','g20','https://commons.wikimedia.org/wiki/File:BMW_3_SERIES_SEDAN_(G20)_China.jpg','Wikimedia Commons','APPROVED','cc-by-sa','bmw-serie-3-g20-configurator.png','tymotors/vehicles/bmw/serie-3/g20/configurator-front-three-quarter'),
    ('audi','a3','8v','https://www.carsinvasion.com/gallery/2014-audi-a3-sportback/2014-audi-a3-sportback-01.jpg','CarsInvasion','REQUIRES_MANUAL_REVIEW','unverified','audi-a3-8v-configurator.png','tymotors/vehicles/audi/a3/8v/configurator-front-three-quarter'),
    ('audi','a4','b9','https://avtoskhemy.com/wp-content/uploads/2024/05/shema-bloku-zapobizhnikiv-audi-a4-b9-i-rele-z-priznachennyam-i-roztashuvannyam1.jpg','Avtoskhemy','REQUIRES_MANUAL_REVIEW','unverified','audi-a4-b9-configurator.png','tymotors/vehicles/audi/a4/b9/configurator-front-three-quarter'),
    ('mercedes-benz','classe-a','w177','user-provided://tymotors/Image-Codex-25-aout-2026-22-34-21.png','Image TYMotors fournie par le propriétaire du projet','REQUIRES_MANUAL_REVIEW','user-provided-unverified','mercedes-classe-a-w177-configurator.png','tymotors/vehicles/mercedes-benz/classe-a/w177/configurator-front-three-quarter'),
    ('mercedes-benz','classe-c','w205','https://commons.wikimedia.org/wiki/File:Mercedes-Benz_W205_C180_2021.jpg','Wikimedia Commons','APPROVED','cc-by-sa','mercedes-classe-c-w205-configurator.png','tymotors/vehicles/mercedes-benz/classe-c/w205/configurator-front-three-quarter'),
    ('volkswagen','golf-7','gti','https://www.larevueautomobile.com/images/articles-md/Volkswagen/Golf-7-GTI/Exterieur/Volkswagen_Golf_7_GTI_001.jpg','La Revue Automobile','REQUIRES_MANUAL_REVIEW','unverified','volkswagen-golf-7-gti-configurator.png','tymotors/vehicles/volkswagen/golf-7/gti/configurator-front-three-quarter'),
    ('volkswagen','golf-7','r','https://commons.wikimedia.org/wiki/File:2017_Volkswagen_Golf_R_TSi.jpg','Wikimedia Commons','APPROVED','cc-by-sa','volkswagen-golf-7-r-configurator.png','tymotors/vehicles/volkswagen/golf-7/r/configurator-front-three-quarter'),
    ('porsche','911','991','https://commons.wikimedia.org/wiki/File:2013_Porsche_911_Carrera_4S_(991)_(9626546987).jpg','Wikimedia Commons','APPROVED','cc-by-sa','porsche-911-991-configurator.png','tymotors/vehicles/porsche/911/991/configurator-front-three-quarter'),
    ('porsche','911','992','https://cdn11.bigcommerce.com/s-aw4qbuk/images/stencil/original/products/317/1482/Embargo_05_30_AM_CET_28_November_front_three_quarter-1__57654.1656700402.jpg','BigCommerce-hosted Porsche press image','REQUIRES_MANUAL_REVIEW','unverified','porsche-911-992-configurator.png','tymotors/vehicles/porsche/911/992/configurator-front-three-quarter'),
    ('porsche','cayenne','9ya','https://commons.wikimedia.org/wiki/File:Porsche_Cayenne_(9YA)_Miami_Metro_Area,_USA.jpg','Wikimedia Commons','APPROVED','cc-by','porsche-cayenne-9ya-configurator.png','tymotors/vehicles/porsche/cayenne/9ya/configurator-front-three-quarter'),
    ('toyota','gr-supra','a90','https://s1.paultan.org/image/2019/09/2019-A90-Toyota-GR-Supra-Malaysia-official-8.jpg','paultan.org / Toyota official image','REQUIRES_MANUAL_REVIEW','unverified','toyota-gr-supra-a90-configurator.png','tymotors/vehicles/toyota/gr-supra/a90/configurator-front-three-quarter'),
    ('toyota','gr-yaris','xp210','https://commons.wikimedia.org/wiki/File:Toyota_GR_Yaris_RZ_1X7A0252.jpg','Wikimedia Commons','APPROVED','cc-by-sa','toyota-gr-yaris-xp210-configurator.png','tymotors/vehicles/toyota/gr-yaris/xp210/configurator-front-three-quarter')
), resolved as (
  select im.*, vg.id as generation_id
  from image_manifest im
  join public.brands b on b.slug = im.brand_slug
  join public.vehicle_models vm on vm.brand_id = b.id and vm.slug = im.model_slug
  join public.vehicle_generations vg on vg.vehicle_model_id = vm.id and vg.slug = im.generation_slug
)
insert into public.vehicle_images (
  generation_id, asset_role, view_type, cloudinary_url, cloudinary_public_id,
  source_url, source_name, original_filename, rights_status, rights_basis,
  verification_status, is_current, transformation_ai, width, height, metadata
)
select generation_id, 'final', 'front_three_quarter',
  'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto,c_fill,g_auto,w_1600,h_900/' || public_id,
  public_id, source_url, source_name, original_filename, rights_status, rights_basis,
  'approved', true,
  not (brand_slug = 'mercedes-benz' and generation_slug = 'w177'),
  1672, 941,
  jsonb_build_object('desktop', 'w_1600,h_900', 'tablet', 'w_1200,h_675', 'mobile', 'w_800,h_450')
from resolved
on conflict (generation_id) where asset_role = 'final' and is_current
do update set cloudinary_url = excluded.cloudinary_url,
  cloudinary_public_id = excluded.cloudinary_public_id,
  source_url = excluded.source_url,
  source_name = excluded.source_name,
  original_filename = excluded.original_filename,
  rights_status = excluded.rights_status,
  rights_basis = excluded.rights_basis,
  verification_status = excluded.verification_status,
  transformation_ai = excluded.transformation_ai,
  width = excluded.width,
  height = excluded.height,
  metadata = excluded.metadata,
  updated_at = now();

with source_manifest(brand_slug, model_slug, generation_slug, source_url, source_name,
  source_filename, rights_status, rights_basis, source_public_id) as (
  values
    ('bmw','serie-3','f30-f35','https://s1.cdn.autoevolution.com/images/gallery/BMW-3-Series--F30--4412_69.jpg','autoevolution','bmw-serie-3-f30-f35.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/bmw/serie-3/f30-f35/source-original'),
    ('bmw','serie-4','f32-f36','https://s1.cdn.autoevolution.com/images/gallery/BMW-4-Series-4884_78.jpg','autoevolution','bmw-serie-4-f32-f36.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/bmw/serie-4/f32-f36/source-original'),
    ('bmw','serie-3','g20','https://commons.wikimedia.org/wiki/File:BMW_3_SERIES_SEDAN_(G20)_China.jpg','Wikimedia Commons','bmw-serie-3-g20.jpg','APPROVED','cc-by-sa','tymotors/vehicles/bmw/serie-3/g20/source-original'),
    ('audi','a3','8v','https://www.carsinvasion.com/gallery/2014-audi-a3-sportback/2014-audi-a3-sportback-01.jpg','CarsInvasion','audi-a3-8v.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/audi/a3/8v/source-original'),
    ('audi','a4','b9','https://avtoskhemy.com/wp-content/uploads/2024/05/shema-bloku-zapobizhnikiv-audi-a4-b9-i-rele-z-priznachennyam-i-roztashuvannyam1.jpg','Avtoskhemy','audi-a4-b9.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/audi/a4/b9/source-original'),
    ('mercedes-benz','classe-a','w177','user-provided://tymotors/Image-Codex-25-aout-2026-22-34-21.png','Image TYMotors fournie par le propriétaire du projet','mercedes-classe-a-w177.jpg','REQUIRES_MANUAL_REVIEW','user-provided-unverified','tymotors/vehicles/mercedes-benz/classe-a/w177/source-original'),
    ('mercedes-benz','classe-c','w205','https://commons.wikimedia.org/wiki/File:Mercedes-Benz_W205_C180_2021.jpg','Wikimedia Commons','mercedes-classe-c-w205.jpg','APPROVED','cc-by-sa','tymotors/vehicles/mercedes-benz/classe-c/w205/source-original'),
    ('volkswagen','golf-7','gti','https://www.larevueautomobile.com/images/articles-md/Volkswagen/Golf-7-GTI/Exterieur/Volkswagen_Golf_7_GTI_001.jpg','La Revue Automobile','volkswagen-golf-7-gti.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/volkswagen/golf-7/gti/source-original'),
    ('volkswagen','golf-7','r','https://commons.wikimedia.org/wiki/File:2017_Volkswagen_Golf_R_TSi.jpg','Wikimedia Commons','volkswagen-golf-7-r.jpg','APPROVED','cc-by-sa','tymotors/vehicles/volkswagen/golf-7/r/source-original'),
    ('porsche','911','991','https://commons.wikimedia.org/wiki/File:2013_Porsche_911_Carrera_4S_(991)_(9626546987).jpg','Wikimedia Commons','porsche-911-991.jpg','APPROVED','cc-by-sa','tymotors/vehicles/porsche/911/991/source-original'),
    ('porsche','911','992','https://cdn11.bigcommerce.com/s-aw4qbuk/images/stencil/original/products/317/1482/Embargo_05_30_AM_CET_28_November_front_three_quarter-1__57654.1656700402.jpg','BigCommerce-hosted Porsche press image','porsche-911-992.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/porsche/911/992/source-original'),
    ('porsche','cayenne','9ya','https://commons.wikimedia.org/wiki/File:Porsche_Cayenne_(9YA)_Miami_Metro_Area,_USA.jpg','Wikimedia Commons','porsche-cayenne-9ya.jpg','APPROVED','cc-by','tymotors/vehicles/porsche/cayenne/9ya/source-original'),
    ('toyota','gr-supra','a90','https://s1.paultan.org/image/2019/09/2019-A90-Toyota-GR-Supra-Malaysia-official-8.jpg','paultan.org / Toyota official image','toyota-gr-supra-a90.jpg','REQUIRES_MANUAL_REVIEW','unverified','tymotors/vehicles/toyota/gr-supra/a90/source-original'),
    ('toyota','gr-yaris','xp210','https://commons.wikimedia.org/wiki/File:Toyota_GR_Yaris_RZ_1X7A0252.jpg','Wikimedia Commons','toyota-gr-yaris-xp210.jpg','APPROVED','cc-by-sa','tymotors/vehicles/toyota/gr-yaris/xp210/source-original')
), resolved as (
  select sm.*, vg.id as generation_id
  from source_manifest sm
  join public.brands b on b.slug = sm.brand_slug
  join public.vehicle_models vm on vm.brand_id = b.id and vm.slug = sm.model_slug
  join public.vehicle_generations vg on vg.vehicle_model_id = vm.id and vg.slug = sm.generation_slug
)
insert into public.vehicle_images (
  generation_id, asset_role, view_type, cloudinary_url, cloudinary_public_id,
  source_url, source_name, original_filename, rights_status, rights_basis,
  verification_status, is_current, transformation_ai, metadata
)
select generation_id, 'source', 'front_three_quarter',
  'https://res.cloudinary.com/dwsyixjux/image/upload/' || source_public_id,
  source_public_id, source_url, source_name, source_filename, rights_status, rights_basis,
  'approved', false, false, jsonb_build_object('preserved_for_rebuild', true)
from resolved r
where not exists (
  select 1 from public.vehicle_images vi
  where vi.generation_id = r.generation_id
    and vi.asset_role = 'source'
    and vi.cloudinary_public_id = r.source_public_id
);

with hotspot_manifest(brand_slug, model_slug, generation_slug, grille_x, grille_y, cabin_x, cabin_y) as (
  values
    ('bmw','serie-3','f30-f35',37.5,61.5,58.0,40.5), ('bmw','serie-4','f32-f36',38.0,61.0,59.0,40.0),
    ('bmw','serie-3','g20',37.0,62.5,58.0,40.0), ('audi','a3','8v',38.5,61.0,58.5,41.0),
    ('audi','a4','b9',37.0,61.5,58.0,40.0), ('mercedes-benz','classe-a','w177',38.0,62.0,57.5,41.0),
    ('mercedes-benz','classe-c','w205',37.0,62.0,58.5,40.5), ('volkswagen','golf-7','gti',38.5,63.0,58.5,42.0),
    ('volkswagen','golf-7','r',38.0,62.0,58.0,41.0), ('porsche','911','991',36.0,64.0,58.5,41.0),
    ('porsche','911','992',36.0,63.0,58.0,40.5), ('porsche','cayenne','9ya',35.5,64.0,59.0,40.0),
    ('toyota','gr-supra','a90',36.0,63.0,57.5,40.0), ('toyota','gr-yaris','xp210',37.5,63.0,57.0,41.5)
), resolved as (
  select hm.*, vg.id as generation_id
  from hotspot_manifest hm
  join public.brands b on b.slug = hm.brand_slug
  join public.vehicle_models vm on vm.brand_id = b.id and vm.slug = hm.model_slug
  join public.vehicle_generations vg on vg.vehicle_model_id = vm.id and vg.slug = hm.generation_slug
), zones as (
  select generation_id, 'calandre'::text as zone_slug, 'Calandre'::text as label,
    'exterior-calandres'::text as category_slug, grille_x as x_percent, grille_y as y_percent, 10 as display_order
  from resolved
  union all
  select generation_id, 'habitacle-carplay', 'Habitacle / CarPlay',
    'multimedia-technology-ecrans-carplay', cabin_x, cabin_y, 20
  from resolved
)
insert into public.vehicle_hotspots (
  generation_id, zone_slug, label, category_slug, x_percent, y_percent, is_verified, display_order
)
select generation_id, zone_slug, label, category_slug, x_percent, y_percent, true, display_order
from zones
on conflict (generation_id, zone_slug)
do update set label = excluded.label, category_slug = excluded.category_slug,
  x_percent = excluded.x_percent, y_percent = excluded.y_percent,
  is_verified = excluded.is_verified, display_order = excluded.display_order;
