begin;

with supplier_rows(slug, supplier_name, supplier_url, source_url, notes) as (
  values
    ('bmw-f30-double-slat-grille', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/Car-Front-Kidney-Grille-Dual-Slat_1600728344099.html', 'Supplier listing states BMW F30/F35, 2013-2019. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('bmw-f30-f32-mirror-caps', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/A-Pair-Car-Glossy-Black-Rearview_1600507419193.html', 'Supplier listing explicitly includes F30, F32 and F36. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('bmw-f30-m-performance-spoiler', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/Glossy-Black-PSM-Style-Car-Accessories_1601408620626.html', 'Supplier listing starts at 2013 while the article says 2012-2019. Reconcile compatibility before publication. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=partial_year_match.'),
    ('bmw-f30-m-sport-rear-diffuser', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/Glossy-Black-ABS-MP-Style-Car_1601193357307.html', 'Supplier listing requires the M Sport bumper and states 2014-2019. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('bmw-g20-gloss-black-grille', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/ABS-Glossy-Black-Replacement-Grille-Car_1600833728383.html', 'Supplier listing explicitly states BMW G20, 2019-2021. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('bmw-g20-m-performance-spoiler', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/1-Pcs-ABS-Glossy-Black-Car_1600733329759.html', 'Supplier listing explicitly states BMW G20/G28, 2019-2021. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('bmw-g20-mirror-caps', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/2-Pcs-ABS-Glossy-Black-Side_1600727145118.html', 'Supplier listing explicitly states BMW G20/G21. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.'),
    ('mercedes-w205-amg-grille', 'GZTM Auto / Leju (Guangzhou) Trading Co., Ltd.', 'https://gztmauto.en.alibaba.com', 'https://www.alibaba.com/product-detail/Car-Front-Upper-Grille-Grill-AMG_1600995787850.html', 'Supplier listing explicitly states Mercedes-Benz W205, 2015-2018. RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW; MATCH_STATUS=verified_listing_match.')
)
insert into public.product_supplier_data (
  product_id, supplier_name, supplier_url, exact_source_url,
  supplier_verified, last_checked_at, notes, updated_at
)
select p.id, s.supplier_name, s.supplier_url, s.source_url,
       false, now(), s.notes, now()
from supplier_rows s
join public.products p on p.slug = s.slug
on conflict (product_id) do update set
  supplier_name = excluded.supplier_name,
  supplier_url = excluded.supplier_url,
  exact_source_url = excluded.exact_source_url,
  supplier_verified = excluded.supplier_verified,
  last_checked_at = excluded.last_checked_at,
  notes = excluded.notes,
  updated_at = excluded.updated_at;

delete from public.product_images
where product_id in (
  select id from public.products where slug in (
    'bmw-f30-double-slat-grille',
    'bmw-f30-f32-mirror-caps',
    'bmw-f30-m-performance-spoiler',
    'bmw-f30-m-sport-rear-diffuser',
    'bmw-g20-gloss-black-grille',
    'bmw-g20-m-performance-spoiler',
    'bmw-g20-mirror-caps',
    'mercedes-w205-amg-grille'
  )
);

with image_rows(slug, public_id, url, alt_text) as (
  values
    ('bmw-f30-double-slat-grille', 'bmw-f30-double-slat-grille_ex9is6', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-f30-double-slat-grille_ex9is6', 'Calandre double lame BMW Série 3 F30 F35'),
    ('bmw-f30-f32-mirror-caps', 'bmw-f30-f32-mirror-caps_ya00mr', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-f30-f32-mirror-caps_ya00mr', 'Coques de rétroviseurs BMW F30 F32 F36'),
    ('bmw-f30-m-performance-spoiler', 'bmw-f30-m-performance-spoiler_qkbzea', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-f30-m-performance-spoiler_qkbzea', 'Spoiler de coffre BMW F30 style M Performance'),
    ('bmw-f30-m-sport-rear-diffuser', 'bmw-f30-m-sport-rear-diffuser_az010c', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-f30-m-sport-rear-diffuser_az010c', 'Diffuseur arrière BMW F30 F31 pare-chocs M Sport'),
    ('bmw-g20-gloss-black-grille', 'bmw-g20-gloss-black-grille_at0m7c', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-g20-gloss-black-grille_at0m7c', 'Calandre noire brillante BMW Série 3 G20'),
    ('bmw-g20-m-performance-spoiler', 'bmw-g20-m-performance-spoiler_vtgmbk', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-g20-m-performance-spoiler_vtgmbk', 'Spoiler de coffre BMW G20 G28 style M Performance'),
    ('bmw-g20-mirror-caps', 'bmw-g20-mirror-caps_ue7qbb', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/bmw-g20-mirror-caps_ue7qbb', 'Coques de rétroviseurs BMW G20 G21'),
    ('mercedes-w205-amg-grille', 'mercedes-w205-amg-grille_lzs1ku', 'https://res.cloudinary.com/dwsyixjux/image/upload/f_auto,q_auto/v1787808146/mercedes-w205-amg-grille_lzs1ku', 'Calandre style AMG Mercedes-Benz Classe C W205')
)
insert into public.product_images (
  product_id, url, public_id, alt_text, image_type, is_verified, display_order
)
select p.id, i.url, i.public_id, i.alt_text, 'main', false, 0
from image_rows i
join public.products p on p.slug = i.slug
on conflict (product_id, url) do update set
  public_id = excluded.public_id,
  alt_text = excluded.alt_text,
  image_type = excluded.image_type,
  is_verified = excluded.is_verified,
  display_order = excluded.display_order;

commit;
