from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from app.schemas import ProductInput
from app.supabase_rest import SupabaseRest


def _in(values: Iterable[str]) -> str:
    return "in.(" + ",".join(values) + ")"


def _money(cents: int | None) -> float | None:
    return None if cents is None else round(cents / 100, 2)


def _cents(amount: float | None) -> int | None:
    return None if amount is None else round(amount * 100)


class CatalogStore:
    def __init__(self, db: SupabaseRest):
        self.db = db

    async def brands(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "display_order.asc,name.asc"}
        if not include_inactive:
            params["is_active"] = "eq.true"
        rows = await self.db.select("brands", params=params)
        return [{**row, "image": row.get("image_url"), "order": row.get("display_order", 0)} for row in rows]

    async def categories(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "display_order.asc,name.asc"}
        if not include_inactive:
            params["is_active"] = "eq.true"
        rows = await self.db.select("categories", params=params)
        children: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            if row.get("parent_id"):
                children[row["parent_id"]].append(row["name"])
        return [
            {**row, "image": row.get("image_url"), "order": row.get("display_order", 0), "subcategories": children.get(row["id"], [])}
            for row in rows if not row.get("parent_id")
        ]

    async def compatibility_tree(self, brand_slug: str | None = None) -> list[dict[str, Any]]:
        brand_params: dict[str, Any] = {"select": "id,slug,name", "is_active": "eq.true"}
        if brand_slug:
            brand_params["slug"] = f"eq.{brand_slug}"
        brands = await self.db.select("brands", params=brand_params)
        if not brands:
            return []
        brand_by_id = {row["id"]: row for row in brands}
        models = await self.db.select("vehicle_models", params={
            "select": "*", "brand_id": _in(brand_by_id), "is_active": "eq.true", "order": "display_order.asc,name.asc"
        })
        if not models:
            return []
        generations = await self.db.select("vehicle_generations", params={
            "select": "*", "vehicle_model_id": _in(row["id"] for row in models), "is_active": "eq.true", "order": "display_order.asc,name.asc"
        })
        hotspots = []
        if generations:
            hotspots = await self.db.select("vehicle_hotspots", params={
                "select": "*", "generation_id": _in(row["id"] for row in generations), "is_verified": "eq.true", "order": "display_order.asc"
            })
        # A verified coordinate alone is not enough to make a zone useful. Only
        # expose hotspots backed by at least one active product with an exact,
        # verified compatibility for the selected generation.
        active_products = await self.db.select(
            "products", params={"select": "id,category_id", "status": "eq.active"}
        )
        active_product_ids = {row["id"] for row in active_products}
        active_categories_by_generation: dict[str, set[str]] = defaultdict(set)
        if active_product_ids and generations:
            category_ids = {row["category_id"] for row in active_products}
            categories = await self.db.select(
                "categories", params={"select": "id,slug", "id": _in(category_ids)}
            )
            category_slug_by_id = {row["id"]: row["slug"] for row in categories}
            product_category = {
                row["id"]: category_slug_by_id.get(row["category_id"])
                for row in active_products
            }
            rules = await self.db.select("product_compatibilities", params={
                "select": "product_id,generation_id", "product_id": _in(active_product_ids),
                "generation_id": _in(row["id"] for row in generations),
                "verification_state": "eq.verified",
            })
            for rule in rules:
                category_slug = product_category.get(rule["product_id"])
                if category_slug and rule.get("generation_id"):
                    active_categories_by_generation[rule["generation_id"]].add(category_slug)
        hot_by_generation: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for hotspot in hotspots:
            if hotspot["category_slug"] not in active_categories_by_generation[hotspot["generation_id"]]:
                continue
            hot_by_generation[hotspot["generation_id"]].append({
                "id": hotspot["zone_slug"], "label": hotspot["label"], "category_slug": hotspot["category_slug"],
                "x": float(hotspot["x_percent"]), "y": float(hotspot["y_percent"]),
                "image_url": hotspot.get("image_url"), "image_alt": hotspot.get("image_alt"),
            })
        gen_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for generation in generations:
            gen_by_model[generation["vehicle_model_id"]].append({
                "id": generation["id"], "slug": generation["slug"], "name": generation["name"],
                "chassis_codes": generation.get("chassis_codes") or [], "year_from": generation.get("year_from"),
                "year_to": generation.get("year_to"), "body_types": generation.get("body_types") or [],
                "trims": generation.get("trims") or [],
                "stage_image_url": generation.get("stage_image_url") if generation.get("image_verified") else None,
                "stage_image_alt": generation.get("stage_image_alt") if generation.get("image_verified") else None,
                "image_verified": generation.get("image_verified", False),
                "image_attribution": generation.get("image_attribution") if generation.get("image_verified") else None,
                "image_source_url": generation.get("image_source_url") if generation.get("image_verified") else None,
                "hotspots": hot_by_generation.get(generation["id"], []),
            })
        result = []
        for model in models:
            brand = brand_by_id[model["brand_id"]]
            result.append({
                "id": model["id"], "slug": model["slug"], "brand_slug": brand["slug"], "brand_name": brand["name"],
                "name": model["name"], "generation_records": gen_by_model.get(model["id"], []),
                "generations": [generation["name"] for generation in gen_by_model.get(model["id"], [])],
            })
        return result

    async def hydrate_products(self, rows: list[dict[str, Any]], *, include_admin: bool = False) -> list[dict[str, Any]]:
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        category_ids = {row["category_id"] for row in rows}
        categories = await self.db.select("categories", params={"select": "id,slug,name", "id": _in(category_ids)})
        cat_by_id = {row["id"]: row for row in categories}
        images = await self.db.select("product_images", params={"select": "*", "product_id": _in(ids), "order": "display_order.asc"})
        compatibility_rows = await self.db.select("product_compatibilities", params={"select": "*", "product_id": _in(ids)})
        brand_ids = {row["brand_id"] for row in compatibility_rows}
        model_ids = {row["vehicle_model_id"] for row in compatibility_rows if row.get("vehicle_model_id")}
        generation_ids = {row["generation_id"] for row in compatibility_rows if row.get("generation_id")}
        brands = await self.db.select("brands", params={"select": "id,slug,name", "id": _in(brand_ids)}) if brand_ids else []
        models = await self.db.select("vehicle_models", params={"select": "id,name", "id": _in(model_ids)}) if model_ids else []
        generations = await self.db.select("vehicle_generations", params={"select": "id,name", "id": _in(generation_ids)}) if generation_ids else []
        brand_by_id = {row["id"]: row for row in brands}
        model_by_id = {row["id"]: row for row in models}
        gen_by_id = {row["id"]: row for row in generations}
        image_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for image in images:
            image_by_product[image["product_id"]].append(image)
        compat_by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rule in compatibility_rows:
            compat_by_product[rule["product_id"]].append({
                "id": rule["id"], "brand_slug": brand_by_id.get(rule["brand_id"], {}).get("slug"),
                "model": rule.get("model_name") or model_by_id.get(rule.get("vehicle_model_id"), {}).get("name"),
                "chassis": rule.get("chassis"), "generation": rule.get("generation_name") or gen_by_id.get(rule.get("generation_id"), {}).get("name"),
                "year_from": rule.get("year_from"), "year_to": rule.get("year_to"), "body_types": rule.get("body_types") or [],
                "facelift": rule.get("facelift") or "unknown", "required_trim": rule.get("required_trims") or [],
                "excluded_trims": rule.get("excluded_trims") or [], "camera_compatible": rule.get("camera_compatible"),
                "parking_sensor_compatible": rule.get("parking_sensor_compatible"), "notes": rule.get("notes"),
                "is_verified": rule.get("verification_state") == "verified",
            })
        suppliers: dict[str, dict[str, Any]] = {}
        if include_admin:
            supplier_rows = await self.db.select("product_supplier_data", params={"select": "*", "product_id": _in(ids)})
            suppliers = {row["product_id"]: row for row in supplier_rows}
        result = []
        for row in rows:
            category = cat_by_id.get(row["category_id"], {})
            product_images = image_by_product.get(row["id"], [])
            item = {
                "id": row["id"], "slug": row["slug"], "sku": row["sku"], "name": row["name"],
                "subtitle": row.get("subtitle") or "", "description": row.get("description") or "",
                "price": _money(row["price_cents"]), "compare_at_price": _money(row.get("compare_at_price_cents")),
                "currency": row.get("currency", "EUR"), "stock": row.get("stock", 0), "status": row.get("status"),
                "is_verified": row.get("is_verified", False), "featured": row.get("featured", False),
                "badges": row.get("badges") or [], "rating": float(row["rating"]) if row.get("rating") is not None else None,
                "review_count": row.get("review_count", 0), "specs": row.get("specs") or {},
                "package_contents": row.get("package_contents") or [], "installation_difficulty": row.get("installation_difficulty"),
                "installation_minutes": row.get("installation_minutes"), "tools_required": row.get("tools_required") or [],
                "warranty_months": row.get("warranty_months"), "delivery_estimate": row.get("delivery_estimate"),
                "category_slug": category.get("slug"), "subcategory": row.get("subcategory") or "",
                "compatible_brands": row.get("legacy_compatible_brands") or [],
                "images": [image["url"] for image in product_images], "image_records": product_images,
                "compatibilities": compat_by_product.get(row["id"], []), "created_at": row.get("created_at"),
            }
            if include_admin:
                supplier = suppliers.get(row["id"], {})
                item["admin"] = {
                    "supplier_reference": supplier.get("supplier_reference"), "supplier_name": supplier.get("supplier_name"),
                    "supplier_url": supplier.get("supplier_url"), "exact_source_url": supplier.get("exact_source_url"),
                    "cost_price": _money(supplier.get("cost_price_cents")), "shipping_cost": _money(supplier.get("shipping_cost_cents")),
                    "landed_cost": _money(supplier.get("landed_cost_cents")), "margin_amount": _money(supplier.get("margin_amount_cents")),
                    "margin_percent": float(supplier["margin_percent"]) if supplier.get("margin_percent") is not None else None,
                    "moq": supplier.get("moq"), "supplier_verified": supplier.get("supplier_verified", False), "notes": supplier.get("notes"),
                }
            result.append(item)
        return result

    async def product_by(self, field: str, value: str, *, public_only: bool = True, include_admin: bool = False) -> dict[str, Any] | None:
        params: dict[str, Any] = {"select": "*", field: f"eq.{value}", "limit": 1}
        if public_only:
            params["status"] = "eq.active"
        rows = await self.db.select("products", params=params)
        hydrated = await self.hydrate_products(rows, include_admin=include_admin)
        return hydrated[0] if hydrated else None

    async def product_rows(self, *, public_only: bool = True) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": "*", "order": "created_at.desc"}
        if public_only:
            params["status"] = "eq.active"
        return await self.db.select("products", params=params)

    async def _category_id(self, slug: str) -> str:
        rows = await self.db.select("categories", params={"select": "id", "slug": f"eq.{slug}", "limit": 1})
        if not rows:
            raise ValueError("Unknown category")
        return rows[0]["id"]

    async def _brand_id(self, slug: str) -> str:
        rows = await self.db.select("brands", params={"select": "id", "slug": f"eq.{slug}", "limit": 1})
        if not rows:
            raise ValueError(f"Unknown brand: {slug}")
        return rows[0]["id"]

    async def _vehicle_ids(
        self, brand_id: str, model_name: str | None, generation_name: str | None, chassis: str | None
    ) -> tuple[str | None, str | None]:
        if not model_name:
            return None, None
        models = await self.db.select("vehicle_models", params={
            "select": "id,name", "brand_id": f"eq.{brand_id}", "is_active": "eq.true"
        })
        model = next((row for row in models if row["name"].casefold() == model_name.casefold()), None)
        if not model:
            return None, None
        generations = await self.db.select("vehicle_generations", params={
            "select": "id,name,chassis_codes", "vehicle_model_id": f"eq.{model['id']}", "is_active": "eq.true"
        })
        wanted_generation = (generation_name or "").casefold()
        wanted_chassis = (chassis or "").casefold()
        generation = next((row for row in generations if (
            (wanted_generation and row["name"].casefold() == wanted_generation)
            or (wanted_chassis and wanted_chassis in {code.casefold() for code in row.get("chassis_codes") or []})
        )), None)
        return model["id"], generation["id"] if generation else None

    async def write_product(self, payload: ProductInput, *, product_id: str | None = None) -> dict[str, Any]:
        data = payload.model_dump()
        category_id = await self._category_id(data["category_slug"])
        base = {
            "slug": data["slug"], "sku": data["sku"], "name": data["name"], "subtitle": data["subtitle"],
            "description": data["description"], "category_id": category_id, "subcategory": data["subcategory"],
            "price_cents": _cents(data["price"]), "compare_at_price_cents": _cents(data["compare_at_price"]),
            "currency": data["currency"], "stock": data["stock"], "status": "draft", "is_verified": data["is_verified"],
            "featured": data["featured"], "badges": data["badges"], "rating": data["rating"], "review_count": data["review_count"],
            "specs": data["specs"], "package_contents": data["package_contents"],
            "installation_difficulty": data["installation_difficulty"], "installation_minutes": data["installation_minutes"],
            "tools_required": data["tools_required"], "warranty_months": data["warranty_months"],
            "delivery_estimate": data["delivery_estimate"], "legacy_compatible_brands": data["compatible_brands"],
        }
        if product_id:
            rows = await self.db.update("products", base, params={"id": f"eq.{product_id}"})
            await self.db.delete("product_images", params={"product_id": f"eq.{product_id}"})
            await self.db.delete("product_compatibilities", params={"product_id": f"eq.{product_id}"})
        else:
            rows = await self.db.insert("products", base)
            product_id = rows[0]["id"]
        if data["images"]:
            await self.db.insert("product_images", [
                {"product_id": product_id, "url": url, "image_type": "main" if index == 0 else "gallery", "display_order": index, "is_verified": data["is_verified"]}
                for index, url in enumerate(data["images"])
            ])
        for rule in data["compatibilities"]:
            brand_id = await self._brand_id(rule["brand_slug"])
            vehicle_model_id, generation_id = await self._vehicle_ids(
                brand_id, rule["model"], rule["generation"], rule["chassis"]
            )
            await self.db.insert("product_compatibilities", {
                "product_id": product_id, "brand_id": brand_id, "vehicle_model_id": vehicle_model_id,
                "generation_id": generation_id, "model_name": rule["model"], "chassis": rule["chassis"],
                "generation_name": rule["generation"], "year_from": rule["year_from"], "year_to": rule["year_to"],
                "body_types": rule["body_types"], "facelift": rule["facelift"], "required_trims": rule["required_trim"],
                "excluded_trims": rule["excluded_trims"], "camera_compatible": rule["camera_compatible"],
                "parking_sensor_compatible": rule["parking_sensor_compatible"], "notes": rule["notes"],
                "verification_state": "verified" if rule["is_verified"] else "unverified",
                "verified_at": datetime.now(timezone.utc).isoformat() if rule["is_verified"] else None,
            })
        supplier = data["admin"]
        await self.db.insert("product_supplier_data", {
            "product_id": product_id, "supplier_reference": supplier["supplier_reference"], "supplier_name": supplier["supplier_name"],
            "supplier_url": supplier["supplier_url"], "exact_source_url": supplier["exact_source_url"],
            "cost_price_cents": _cents(supplier["cost_price"]), "shipping_cost_cents": _cents(supplier["shipping_cost"]),
            "landed_cost_cents": _cents(supplier["landed_cost"]), "margin_amount_cents": _cents(supplier["margin_amount"]),
            "margin_percent": supplier["margin_percent"], "moq": supplier["moq"],
            "supplier_verified": supplier["supplier_verified"], "notes": supplier["notes"],
        }, upsert=True, on_conflict="product_id")
        if data["status"] != "draft":
            await self.db.update("products", {"status": data["status"]}, params={"id": f"eq.{product_id}"})
        product = await self.product_by("id", product_id, public_only=False, include_admin=True)
        assert product is not None
        return product
