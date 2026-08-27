# Audit fournisseurs et images produits — 2026-08-27

## Périmètre

- Catalogue Supabase audité : 40 articles commerciaux et 1 produit technique Stripe staging.
- Fournisseurs recherchés : Tianzhiyu, Soyintech et GZTM Auto.
- Règle appliquée : aucune image n'est installée sans correspondance exploitable entre l'article, la pièce, le véhicule et la génération annoncée.
- Toutes les images fournisseur retenues portent `RIGHTS_STATUS=REQUIRES_MANUAL_REVIEW` et restent non vérifiées avant production.

## Correspondances installées

Huit images issues de fiches GZTM Auto / Leju ont été copiées dans Cloudinary puis reliées aux articles Supabase :

- `bmw-f30-double-slat-grille`
- `bmw-f30-f32-mirror-caps`
- `bmw-f30-m-performance-spoiler` — année fournisseur 2013-2019, à réconcilier avec l'article 2012-2019
- `bmw-f30-m-sport-rear-diffuser`
- `bmw-g20-gloss-black-grille`
- `bmw-g20-m-performance-spoiler`
- `bmw-g20-mirror-caps`
- `mercedes-w205-amg-grille`

Les URLs d'origine, URLs Cloudinary, identifiants publics, titres fournisseur et notes de compatibilité sont conservés dans `product_supplier_image_manifest.json` et `product_supplier_data`.

## Articles laissés inchangés

### Résultats proches mais incompatibles ou ambigus

- `audi-a3-8v-rs3-grille` — résultat GZTM limité à 2017-2019, alors que l'article annonce 2013-2020.
- `audi-a3-8v-rear-spoiler` et `audi-a5-rear-spoiler` — résultats trouvés en finition « carbon look », contraire au positionnement TYMotors sans pièces présentées comme carbone.
- `audi-a4-b9-rs4-grille` — résultat trouvé pour une grille antibrouillard inférieure, pas pour la calandre centrale RS4.
- `mercedes-w177-amg-side-vents` — résultat « wind knife » insuffisamment précis pour confirmer qu'il s'agit des mêmes side vents.

### Aucune fiche exacte confirmée chez les trois fournisseurs

- Audi : `audi-gloss-black-mirror-caps`, `audi-logo-door-projectors`.
- BMW : `bmw-logo-door-projectors`.
- Multimédia et accessoires universels : `carplay-screen-10`, `carplay-screen-12`, `dashcam-4k-pro`, `reverse-cam-hd`, `tire-inflator-pro`.
- Mercedes-Benz : `mercedes-logo-door-projectors`, `mercedes-w205-mirror-caps`, `mercedes-w205-panamericana-grille`, `mercedes-w205-rear-spoiler`.
- Porsche : `porsche-911-diffuser-black`, `porsche-911-rear-spoiler`, `porsche-cayenne-front-grille`, `porsche-logo-door-projectors`, `porsche-mirror-caps-black`.
- Toyota : `toyota-gr-supra-rear-spoiler`, `toyota-gr-yaris-grille`, `toyota-gr86-mirror-caps`, `toyota-logo-door-projectors`, `toyota-supra-diffuser`.
- Volkswagen : `vw-golf7-gti-grille`, `vw-golf7-gti-r-spoiler`, `vw-golf7-mirror-caps`, `vw-golf7-r-rear-diffuser`, `vw-logo-door-projectors`.

Le produit `staging-checkout-validation` est un article technique de test et ne doit pas être associé à un fournisseur ni à une image commerciale.

## État de publication

Les articles restent `draft`, les images restent `is_verified=false` et les fournisseurs restent `supplier_verified=false`. Ce rapport ne valide ni la matière, ni le prix, ni le MOQ, ni le stock, ni les droits commerciaux. Ces champs devront être confirmés auprès du fournisseur avant activation en production.
