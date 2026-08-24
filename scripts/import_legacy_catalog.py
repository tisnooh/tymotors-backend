"""Idempotent import of the historical TYMotors catalogue into Supabase.

This importer deliberately creates every product as an unverified draft. Generic
legacy images are retained only as unverified admin references; they are never
sufficient to activate a product.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata

from app.config import get_settings
from app.supabase_rest import SupabaseRest
from seed_data import BRANDS, CATEGORIES, PRODUCTS, VEHICLE_MODELS


CATEGORY_ALIASES = {"performance": "exterior", "technology": "multimedia-technology"}
ROOT_CATEGORIES = [
    ("exterior", "Extérieur", 1),
    ("interior", "Intérieur", 2),
    ("multimedia-technology", "Multimédia et technologie", 3),
    ("steering-wheels", "Volants", 4),
    ("active-sound", "Active Sound", 5),
    ("practical-accessories", "Accessoires pratiques", 6),
]

# Stored by exact generation instead of the previous model-only mapping.
# Verification remains false until a human confirms rights and exact fitment.
KNOWN_STAGE_IMAGES = {
    ("bmw", "Série 3", "F30 / F35"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784050/bmw-serie-3-f30-blanc-profil-cote-01_wlybwk.png",
    ("bmw", "Série 3", "G20"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784048/bmw-serie-3-g20-blanc-profil-cote-01_dptrxh.png",
    ("audi", "A3", "8V"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784042/audi-a3-sportback-blanc-profil-cote-01_dirzxr.png",
    ("audi", "A4", "B9"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784040/audi-a4-avant-blanc-profil-cote-01_ukj4tb.png",
    ("mercedes-benz", "Classe C", "W205"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784033/mercedes-classe-c-w205-blanc-profil-cote-01_w1qmii.png",
    ("mercedes-benz", "Classe A", "W177"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784035/mercedes-classe-a-w177-blanc-profil-cote-01_lk4nrk.png",
    ("volkswagen", "Golf 7", "GTI / R"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784027/volkswagen-golf-7-gti-rouge-profil-cote-01_vtqwa5.png",
    ("porsche", "Cayenne", "9YA"): "https://res.cloudinary.com/dwsyixjux/image/upload/v1782784027/porsche-cayenne-noir-profil-cote-01_xhszyy.png",
}


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-") or "unknown"


async def upsert_one(db: SupabaseRest, table: str, payload: dict, conflict: str) -> dict:
    return (await db.insert(table, payload, upsert=True, on_conflict=conflict))[0]


def contains_replacement_character(value: object) -> bool:
    """Detect text that was irreversibly decoded with the Unicode replacement char."""
    if isinstance(value, str):
        return "\ufffd" in value
    if isinstance(value, dict):
        return any(contains_replacement_character(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_replacement_character(item) for item in value)
    return False


async def deactivate_malformed_catalog_rows(db: SupabaseRest) -> int:
    """Hide malformed legacy duplicates without deleting potentially useful records."""
    deactivated = 0
    for table in ("brands", "categories", "vehicle_models", "vehicle_generations"):
        rows = await db.select(table, params={"select": "*", "is_active": "eq.true"})
        for row in rows:
            if contains_replacement_character(row):
                await db.update(table, {"is_active": False}, params={"id": f"eq.{row['id']}"})
                deactivated += 1
    return deactivated


async def run() -> None:
    settings = get_settings(); settings.validate()
    db = SupabaseRest(settings.supabase_url, settings.supabase_service_role_key, settings.supabase_publishable_key)
    await db.open()
    try:
        brand_ids: dict[str, str] = {}
        for item in BRANDS:
            row = await upsert_one(db, "brands", {
                "slug": item["slug"], "name": item["name"], "tagline": item.get("tagline"),
                "description": item.get("description"), "image_url": item.get("image"),
                "logo_text": item.get("logo_text"), "display_order": item.get("order", 0), "is_active": True,
            }, "slug")
            brand_ids[item["slug"]] = row["id"]

        category_ids: dict[str, str] = {}
        legacy_categories = {CATEGORY_ALIASES.get(item["slug"], item["slug"]): item for item in CATEGORIES}
        for slug, name, order in ROOT_CATEGORIES:
            legacy = legacy_categories.get(slug, {})
            row = await upsert_one(db, "categories", {
                "slug": slug, "name": name, "tagline": legacy.get("tagline"), "description": legacy.get("description"),
                "image_url": legacy.get("image"), "display_order": order, "is_active": True,
            }, "slug")
            category_ids[slug] = row["id"]
            for sub_order, sub_name in enumerate(legacy.get("subcategories", []), start=1):
                await upsert_one(db, "categories", {
                    "parent_id": row["id"], "slug": f"{slug}-{slugify(sub_name)}", "name": sub_name,
                    "display_order": sub_order, "is_active": True,
                }, "slug")

        grouped_models: dict[tuple[str, str], set[str]] = {}
        for item in VEHICLE_MODELS:
            grouped_models.setdefault((item["brand_slug"], item["name"]), set()).update(item.get("generations") or [])
        for (brand_slug, model_name), generations in grouped_models.items():
            model = await upsert_one(db, "vehicle_models", {
                "brand_id": brand_ids[brand_slug], "slug": slugify(model_name), "name": model_name, "is_active": True,
            }, "brand_id,slug")
            for order, generation_name in enumerate(sorted(generations), start=1):
                stage_url = KNOWN_STAGE_IMAGES.get((brand_slug, model_name, generation_name))
                await upsert_one(db, "vehicle_generations", {
                    "vehicle_model_id": model["id"], "slug": slugify(generation_name), "name": generation_name,
                    "chassis_codes": [part.strip() for part in generation_name.split("/")],
                    "stage_image_url": stage_url, "stage_image_alt": f"{model_name} {generation_name} — vue latérale",
                    "image_verified": False, "image_source_url": None, "image_rights_basis": None,
                    "image_attribution": None, "image_verified_at": None,
                    "display_order": order, "is_active": True,
                }, "vehicle_model_id,slug")

        for item in PRODUCTS:
            category_slug = CATEGORY_ALIASES.get(item["category_slug"], item["category_slug"])
            product = await upsert_one(db, "products", {
                "slug": item["slug"], "sku": item["sku"], "name": item["name"], "subtitle": item.get("subtitle"),
                "description": item["description"], "category_id": category_ids[category_slug],
                "subcategory": item.get("subcategory"), "price_cents": round(item["price"] * 100),
                "compare_at_price_cents": None, "currency": item.get("currency", "EUR"), "stock": 0,
                "status": "draft", "is_verified": False, "featured": False, "badges": [], "rating": None,
                "review_count": 0, "specs": {}, "package_contents": [], "tools_required": [],
                "legacy_compatible_brands": item.get("compatible_brands") or [],
            }, "slug")
            await db.delete("product_images", params={"product_id": f"eq.{product['id']}"})
            if item.get("images"):
                await db.insert("product_images", [{
                    "product_id": product["id"], "url": url, "image_type": "main" if index == 0 else "gallery",
                    "alt_text": f"Référence historique non vérifiée — {item['name']}", "display_order": index,
                    "is_verified": False,
                } for index, url in enumerate(item["images"])])
            await upsert_one(db, "product_supplier_data", {
                "product_id": product["id"], "supplier_verified": False,
                "notes": "REQUIRES_MANUAL_REVIEW: exact supplier, price, rights, dimensions and fitment are not verified.",
            }, "product_id")
        deactivated = await deactivate_malformed_catalog_rows(db)
        print(
            f"Imported {len(BRANDS)} brands, {len(grouped_models)} models and "
            f"{len(PRODUCTS)} draft products; deactivated {deactivated} malformed legacy rows."
        )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(run())
