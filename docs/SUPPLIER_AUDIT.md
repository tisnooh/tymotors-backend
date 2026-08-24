# TYMotors supplier audit

Date: 2026-08-24

## Publication rule

No legacy product is currently linked to a verified supplier offer. Every imported product therefore remains a private `draft` with `is_verified = false`, `stock = 0`, and supplier status `REQUIRES_MANUAL_REVIEW`.

A product may be activated only after an administrator has verified all of the following against the exact supplier listing:

- supplier legal/company identity and listing URL;
- exact vehicle, chassis, years, body style, trim, facelift and sensor/camera compatibility;
- material, finish, package contents and mounting method;
- current unit price, MOQ, shipping cost and delivery estimate to France;
- VAT/customs assumptions, return policy and actual warranty;
- real product images and permission to reuse them.

## Supplier research result

| Supplier name supplied for review | Public evidence found | Safe catalogue decision |
|---|---|---|
| Tianzhiyu | Alibaba supplier/category references exist, but no public one-to-one evidence was found for any exact TYMotors legacy SKU. | Do not attach the supplier to a product yet. |
| Soyintech | No sufficiently reliable public mapping to an exact current TYMotors product was established. | Do not attach the supplier to a product yet. |
| GZTM Auto | No sufficiently reliable public mapping to an exact current TYMotors product was established. | Do not attach the supplier to a product yet. |

Generic marketplace results, similar photos, matching titles, or another seller's listing are not accepted as proof. A logged-in Alibaba review is still required for exact supplier/product validation.

## Import behaviour

`scripts/import_legacy_catalog.py` deliberately imports catalogue content as unverified staging data. It never invents a supplier, purchase price, landed cost, stock, rating, review count, warranty, promotion, compatibility, or image verification status.

The database trigger `enforce_product_activation_requirements` prevents activation until the catalogue has at least one verified image, one exact compatibility record, verified supplier/cost data, delivery information, installation information and package contents.

