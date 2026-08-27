begin;

delete from public.product_images
where product_id in (
  select id from public.products where slug in (
    'bmw-logo-door-projectors',
    'audi-a3-8v-rs3-grille',
    'audi-a3-8v-rear-spoiler',
    'audi-a4-b9-rs4-grille',
    'audi-a5-rear-spoiler',
    'audi-gloss-black-mirror-caps',
    'audi-logo-door-projectors',
    'mercedes-w205-panamericana-grille',
    'mercedes-w205-rear-spoiler',
    'mercedes-w177-amg-side-vents',
    'mercedes-w205-mirror-caps',
    'mercedes-logo-door-projectors',
    'vw-golf7-gti-r-spoiler',
    'vw-golf7-gti-grille',
    'vw-golf7-mirror-caps',
    'vw-golf7-r-rear-diffuser',
    'vw-logo-door-projectors',
    'porsche-911-rear-spoiler',
    'porsche-cayenne-front-grille',
    'porsche-mirror-caps-black',
    'porsche-logo-door-projectors',
    'porsche-911-diffuser-black',
    'toyota-gr-supra-rear-spoiler',
    'toyota-gr-yaris-grille',
    'toyota-gr86-mirror-caps',
    'toyota-logo-door-projectors',
    'toyota-supra-diffuser',
    'carplay-screen-12',
    'carplay-screen-10',
    'dashcam-4k-pro',
    'reverse-cam-hd',
    'tire-inflator-pro'
  )
);

with image_rows(slug, public_id, url) as (
  values
    ('bmw-logo-door-projectors', 'tymotors/products/o5ylil1cryn4uertnc89', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812274/tymotors/products/o5ylil1cryn4uertnc89.webp'),
    ('audi-a3-8v-rs3-grille', 'tymotors/products/bck3jzlnce1ibljambew', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812269/tymotors/products/bck3jzlnce1ibljambew.webp'),
    ('audi-a3-8v-rear-spoiler', 'tymotors/products/hzdciapklkgvwwcatpic', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812267/tymotors/products/hzdciapklkgvwwcatpic.webp'),
    ('audi-a4-b9-rs4-grille', 'tymotors/products/nt3kaqcyavdt8wyddowh', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812270/tymotors/products/nt3kaqcyavdt8wyddowh.webp'),
    ('audi-a5-rear-spoiler', 'tymotors/products/cb4rrpfwhdipxg8i9t3r', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812271/tymotors/products/cb4rrpfwhdipxg8i9t3r.jpg'),
    ('audi-gloss-black-mirror-caps', 'tymotors/products/ulycd4tnyyo6byw8bhiu', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812272/tymotors/products/ulycd4tnyyo6byw8bhiu.webp'),
    ('audi-logo-door-projectors', 'tymotors/products/esaujo8wx76wirmm5gsx', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812273/tymotors/products/esaujo8wx76wirmm5gsx.webp'),
    ('mercedes-w205-panamericana-grille', 'tymotors/products/a8uhlb4p8yktkr78fdwo', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812281/tymotors/products/a8uhlb4p8yktkr78fdwo.webp'),
    ('mercedes-w205-rear-spoiler', 'tymotors/products/uzc5j6i7pneej4ptd3qg', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812282/tymotors/products/uzc5j6i7pneej4ptd3qg.webp'),
    ('mercedes-w177-amg-side-vents', 'tymotors/products/qi2tuheecreo0n4tup9i', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812280/tymotors/products/qi2tuheecreo0n4tup9i.jpg'),
    ('mercedes-w205-mirror-caps', 'tymotors/products/lyijb0ypr7sxrtjquaig', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812281/tymotors/products/lyijb0ypr7sxrtjquaig.webp'),
    ('mercedes-logo-door-projectors', 'tymotors/products/xmjkhlornytdipkva8xe', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812279/tymotors/products/xmjkhlornytdipkva8xe.jpg'),
    ('vw-golf7-gti-r-spoiler', 'tymotors/products/hgfmmysfbmvsa8esnwwx', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812295/tymotors/products/hgfmmysfbmvsa8esnwwx.webp'),
    ('vw-golf7-gti-grille', 'tymotors/products/dj2c9synoroidw3yt9sf', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812294/tymotors/products/dj2c9synoroidw3yt9sf.webp'),
    ('vw-golf7-mirror-caps', 'tymotors/products/ccnn1ok3hxrjddibi29s', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812297/tymotors/products/ccnn1ok3hxrjddibi29s.webp'),
    ('vw-golf7-r-rear-diffuser', 'tymotors/products/rwd8ux7dqdgttxq85kyz', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812297/tymotors/products/rwd8ux7dqdgttxq85kyz.webp'),
    ('vw-logo-door-projectors', 'tymotors/products/bkk74v4iz2qolbk5ltz8', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812298/tymotors/products/bkk74v4iz2qolbk5ltz8.jpg'),
    ('porsche-911-rear-spoiler', 'tymotors/products/vchtci3a5ltf7efwa6iq', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812285/tymotors/products/vchtci3a5ltf7efwa6iq.jpg'),
    ('porsche-cayenne-front-grille', 'tymotors/products/mulk5ubnpqf6h8qvqbl1', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812286/tymotors/products/mulk5ubnpqf6h8qvqbl1.webp'),
    ('porsche-mirror-caps-black', 'tymotors/products/d33ieftm7pxftve7wzr8', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812287/tymotors/products/d33ieftm7pxftve7wzr8.webp'),
    ('porsche-logo-door-projectors', 'tymotors/products/wlyirhoycty4fg1xy45v', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812286/tymotors/products/wlyirhoycty4fg1xy45v.jpg'),
    ('porsche-911-diffuser-black', 'tymotors/products/a0x5gwf5v2bp2jwfj82x', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812283/tymotors/products/a0x5gwf5v2bp2jwfj82x.webp'),
    ('toyota-gr-supra-rear-spoiler', 'tymotors/products/d0avf2txmkwpdfclx3zq', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812290/tymotors/products/d0avf2txmkwpdfclx3zq.webp'),
    ('toyota-gr-yaris-grille', 'tymotors/products/cas5xqenmvec1ciakrtc', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812291/tymotors/products/cas5xqenmvec1ciakrtc.webp'),
    ('toyota-gr86-mirror-caps', 'tymotors/products/oajcplsyv50nlxllbb0b', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812292/tymotors/products/oajcplsyv50nlxllbb0b.webp'),
    ('toyota-logo-door-projectors', 'tymotors/products/wyastfk9r2jlvtubsg72', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812292/tymotors/products/wyastfk9r2jlvtubsg72.webp'),
    ('toyota-supra-diffuser', 'tymotors/products/nn87biriyjautzxdngcj', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812293/tymotors/products/nn87biriyjautzxdngcj.webp'),
    ('carplay-screen-12', 'tymotors/products/sfugsisrhrkx2r9f3shz', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812276/tymotors/products/sfugsisrhrkx2r9f3shz.webp'),
    ('carplay-screen-10', 'tymotors/products/ry5xqoo5vhzd5pzg70hv', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812275/tymotors/products/ry5xqoo5vhzd5pzg70hv.webp'),
    ('dashcam-4k-pro', 'tymotors/products/l3ktklfj5by1r3dbqfnu', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812277/tymotors/products/l3ktklfj5by1r3dbqfnu.jpg'),
    ('reverse-cam-hd', 'tymotors/products/zkmy4ozu3npnowl5r1ln', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812288/tymotors/products/zkmy4ozu3npnowl5r1ln.jpg'),
    ('tire-inflator-pro', 'tymotors/products/certt9jjcpbfvqugqkft', 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787812289/tymotors/products/certt9jjcpbfvqugqkft.webp')
)
insert into public.product_images (
  product_id, url, public_id, alt_text, image_type, is_verified, display_order
)
select p.id, i.url, i.public_id, p.name, 'main', false, 0
from image_rows i
join public.products p on p.slug = i.slug
on conflict (product_id, url) do update set
  public_id = excluded.public_id,
  alt_text = excluded.alt_text,
  image_type = excluded.image_type,
  is_verified = excluded.is_verified,
  display_order = excluded.display_order;

commit;
