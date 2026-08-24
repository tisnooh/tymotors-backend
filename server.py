from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import random
import string
import time
from typing import Any
import uuid

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
import stripe
from stripe import StripeClient
from starlette.middleware.cors import CORSMiddleware

from app.compatibility import check_compatibility
from app.config import Settings, get_settings
from app.schemas import (
    AdminOrderUpdateInput, CartItemInput, CartUpdateInput, ContactInput, NewsletterInput,
    ProductInput, ProductUpdateInput, ProfileUpdateInput, VehicleSelection, WishlistInput,
)
from app.store import CatalogStore
from app.supabase_rest import SupabaseError, SupabaseRest

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger("tymotors")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings: Settings = get_settings()
db = SupabaseRest(settings.supabase_url, settings.supabase_service_role_key, settings.supabase_publishable_key)
catalog = CatalogStore(db)
stripe_client: StripeClient | None = None
bearer = HTTPBearer(auto_error=False)
checkout_attempts: dict[str, list[float]] = {}
contact_attempts: dict[str, list[float]] = {}


def _configure_cloudinary() -> None:
    if settings.cloudinary_url:
        cloudinary.config(cloudinary_url=settings.cloudinary_url, secure=True)
    else:
        cloudinary.config(cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key,
                          api_secret=settings.cloudinary_api_secret, secure=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global stripe_client
    settings.validate()
    _configure_cloudinary()
    await db.open()
    if settings.stripe_secret_key:
        stripe_client = StripeClient(settings.stripe_secret_key, http_client=stripe.HTTPXClient())
    yield
    await db.close()


app = FastAPI(title="TYMotors API", version="2.0.0", lifespan=lifespan)
api = APIRouter(prefix="/api")


def _rate_limit(bucket: dict[str, list[float]], key: str, maximum: int, window: int) -> None:
    now = time.monotonic()
    current = [stamp for stamp in bucket.get(key, []) if now - stamp < window]
    if len(current) >= maximum:
        raise HTTPException(status_code=429, detail="Too many requests")
    current.append(now)
    bucket[key] = current


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


async def optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict[str, Any] | None:
    if not credentials:
        return None
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    user = await db.get_user(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase session")
    return user


async def require_user(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    rows = await db.select("profiles", params={"select": "id,role,email", "id": f"eq.{user['id']}", "limit": 1})
    if not rows or rows[0].get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return {**user, "profile": rows[0]}


async def _audit(admin: dict[str, Any], action: str, resource: str, metadata: dict[str, Any] | None = None) -> None:
    await db.insert("admin_audit", {"admin_user_id": admin["id"], "action": action,
                                    "resource": resource, "metadata": metadata or {}})


def _session_id(value: str | None) -> str:
    if not value or len(value) > 128:
        raise HTTPException(status_code=400, detail="Missing or invalid X-Session-Id header")
    return value


async def _cart_for(user: dict[str, Any] | None, session_id: str | None, *, create: bool = True) -> dict[str, Any] | None:
    if user:
        match = {"user_id": f"eq.{user['id']}"}; payload = {"user_id": user["id"]}
    else:
        guest = _session_id(session_id); match = {"guest_session_id": f"eq.{guest}"}; payload = {"guest_session_id": guest}
    rows = await db.select("carts", params={"select": "*", **match, "limit": 1})
    if rows or not create:
        return rows[0] if rows else None
    try:
        return (await db.insert("carts", payload))[0]
    except SupabaseError as error:
        if error.status_code != 409: raise
        rows = await db.select("carts", params={"select": "*", **match, "limit": 1})
        return rows[0] if rows else None


async def _cart_response(cart: dict[str, Any] | None) -> dict[str, Any]:
    if not cart:
        return {"items": [], "subtotal": 0, "shipping": 0, "total": 0, "currency": "EUR"}
    item_rows = await db.select("cart_items", params={"select": "*", "cart_id": f"eq.{cart['id']}", "order": "created_at.asc"})
    if not item_rows:
        return {"items": [], "subtotal": 0, "shipping": 0, "total": 0, "currency": cart.get("currency", "EUR")}
    product_ids = [row["product_id"] for row in item_rows]
    rows = await db.select("products", params={"select": "*", "id": "in.(" + ",".join(product_ids) + ")", "status": "eq.active"})
    products = await catalog.hydrate_products(rows); by_id = {p["id"]: p for p in products}
    items, subtotal_cents = [], 0
    for row in item_rows:
        product = by_id.get(row["product_id"])
        if not product: continue
        quantity = row["quantity"]
        unit_amount_cents = round(product["price"] * 100)
        line_total_cents = unit_amount_cents * quantity
        subtotal_cents += line_total_cents
        selected_vehicle = row.get("selected_vehicle")
        compatibility_result = (
            check_compatibility(product, VehicleSelection.model_validate(selected_vehicle))
            if selected_vehicle else {"status": "unknown", "reason": "No vehicle selected"}
        )
        if selected_vehicle:
            selected_vehicle = {
                **selected_vehicle,
                "compatibility_status": compatibility_result["status"],
                "compatibility_reason": compatibility_result.get("reason"),
            }
        items.append({
            **product,
            "product_id": product["id"],
            "quantity": quantity,
            "selected_vehicle": selected_vehicle,
            "compatibility_result": compatibility_result,
            "line_total": line_total_cents / 100,
        })
    shipping_cents = 0 if not items or subtotal_cents >= settings.free_shipping_threshold_cents else settings.shipping_rate_cents
    return {
        "items": items,
        "subtotal": subtotal_cents / 100,
        "shipping": shipping_cents / 100,
        "total": (subtotal_cents + shipping_cents) / 100,
        "currency": cart.get("currency", "EUR"),
    }


def _order_number() -> str:
    return f"TY-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def _address(value: Any) -> dict[str, Any]:
    if not value: return {}
    if hasattr(value, "to_dict_recursive"): return value.to_dict_recursive()
    return dict(value)


@api.get("/")
async def root(): return {"message": "TYMotors API", "version": "2.0.0", "database": "supabase"}


@api.get("/health")
async def health():
    await db.select("brands", params={"select": "id", "limit": 1})
    return {"status": "ok", "database": "supabase", "environment": settings.environment}


@api.get("/brands")
async def list_brands(): return await catalog.brands()


@api.get("/brands/{slug}")
async def get_brand(slug: str):
    rows = [row for row in await catalog.brands() if row["slug"] == slug]
    if not rows: raise HTTPException(status_code=404, detail="Brand not found")
    return rows[0]


@api.get("/categories")
async def list_categories(): return await catalog.categories()


@api.get("/categories/{slug}")
async def get_category(slug: str):
    slug = {"performance": "exterior", "technology": "multimedia-technology"}.get(slug, slug)
    rows = [row for row in await catalog.categories() if row["slug"] == slug]
    if not rows: raise HTTPException(status_code=404, detail="Category not found")
    return rows[0]


@api.get("/compatibility")
async def compatibility_tree(brand: str | None = None): return await catalog.compatibility_tree(brand)


@api.get("/products")
async def list_products(category: str | None = None, brand: str | None = None, model: str | None = None,
                        chassis: str | None = None, year: int | None = Query(default=None, ge=1950, le=2100),
                        body_type: str | None = None, q: str | None = Query(default=None, max_length=120),
                        featured: bool | None = None,
                        sort: str = Query(default="newest", pattern="^(relevance|newest|price_asc|price_desc|name)$"),
                        page: int = Query(default=1, ge=1), limit: int = Query(default=24, ge=1, le=100)):
    products = await catalog.hydrate_products(await catalog.product_rows())
    category = {"performance": "exterior", "technology": "multimedia-technology"}.get(category, category)
    if category: products = [p for p in products if p["category_slug"] == category]
    if featured is not None: products = [p for p in products if p["featured"] is featured]
    if q:
        term = q.strip().casefold(); products = [p for p in products if term in f"{p['name']} {p['subtitle']} {p['sku']}".casefold()]
    if brand: products = [p for p in products if brand in p["compatible_brands"] or any(c.get("brand_slug") == brand for c in p["compatibilities"])]
    if model: products = [p for p in products if any((c.get("model") or "").casefold() == model.casefold() for c in p["compatibilities"])]
    if chassis: products = [p for p in products if any(chassis.casefold() in {(c.get("chassis") or "").casefold(), (c.get("generation") or "").casefold()} for c in p["compatibilities"])]
    if year is not None: products = [p for p in products if any((c.get("year_from") is None or year >= c["year_from"]) and (c.get("year_to") is None or year <= c["year_to"]) for c in p["compatibilities"])]
    if body_type: products = [p for p in products if any(not c.get("body_types") or body_type.casefold() in {v.casefold() for v in c["body_types"]} for c in p["compatibilities"])]
    if sort == "price_asc": products.sort(key=lambda p: p["price"])
    elif sort == "price_desc": products.sort(key=lambda p: p["price"], reverse=True)
    elif sort == "name": products.sort(key=lambda p: p["name"].casefold())
    else: products.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    total = len(products); start = (page - 1) * limit
    return {"items": products[start:start + limit], "total": total, "page": page, "limit": limit, "pages": (total + limit - 1) // limit}


@api.get("/products/{slug}")
async def get_product(slug: str):
    product = await catalog.product_by("slug", slug)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    return product


@api.post("/products/{slug}/compatibility")
async def product_compatibility(slug: str, vehicle: VehicleSelection):
    product = await catalog.product_by("slug", slug)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    return check_compatibility(product, vehicle)


@api.get("/me")
async def get_me(user: dict[str, Any] = Depends(require_user)):
    rows = await db.select("profiles", params={"select": "id,email,full_name,phone,role,billing_address,shipping_address,created_at", "id": f"eq.{user['id']}", "limit": 1})
    if not rows: raise HTTPException(status_code=404, detail="Profile not found")
    return rows[0]


@api.patch("/me")
async def update_me(payload: ProfileUpdateInput, user: dict[str, Any] = Depends(require_user)):
    changes = payload.model_dump(exclude_none=True)
    if not changes: return await get_me(user)
    return (await db.update("profiles", changes, params={"id": f"eq.{user['id']}"}))[0]


@api.get("/me/orders")
async def my_orders(user: dict[str, Any] = Depends(require_user)):
    rows = await db.select("orders", params={"select": "*", "user_id": f"eq.{user['id']}", "order": "created_at.desc"})
    return {"items": await _orders_with_items(rows)}


@api.get("/cart")
async def get_cart(x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    return await _cart_response(await _cart_for(user, x_session_id))


@api.post("/cart/claim")
async def claim_guest_cart(x_session_id: str | None = Header(default=None), user: dict[str, Any] = Depends(require_user)):
    guest_id = _session_id(x_session_id)
    guest_rows = await db.select("carts", params={"select": "*", "guest_session_id": f"eq.{guest_id}", "limit": 1})
    user_cart = await _cart_for(user, None)
    assert user_cart
    if not guest_rows or guest_rows[0]["id"] == user_cart["id"]:
        return await _cart_response(user_cart)
    guest_cart = guest_rows[0]
    guest_items = await db.select("cart_items", params={"select": "*", "cart_id": f"eq.{guest_cart['id']}"})
    for item in guest_items:
        existing = await db.select("cart_items", params={"select": "quantity", "cart_id": f"eq.{user_cart['id']}", "product_id": f"eq.{item['product_id']}", "limit": 1})
        quantity = min(20, item["quantity"] + (existing[0]["quantity"] if existing else 0))
        await db.insert("cart_items", {"cart_id": user_cart["id"], "product_id": item["product_id"],
            "quantity": quantity, "selected_vehicle": item.get("selected_vehicle")}, upsert=True, on_conflict="cart_id,product_id")
    await db.delete("carts", params={"id": f"eq.{guest_cart['id']}"})
    return await _cart_response(user_cart)


@api.post("/cart")
async def add_to_cart(payload: CartItemInput, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    product = await catalog.product_by("id", payload.product_id)
    if not product: raise HTTPException(status_code=404, detail="Active product not found")
    if product["stock"] < payload.quantity: raise HTTPException(status_code=409, detail="Insufficient stock")
    cart = await _cart_for(user, x_session_id); assert cart
    existing = await db.select("cart_items", params={"select": "*", "cart_id": f"eq.{cart['id']}", "product_id": f"eq.{payload.product_id}", "limit": 1})
    quantity = payload.quantity + (existing[0]["quantity"] if existing else 0)
    if quantity > 20 or quantity > product["stock"]: raise HTTPException(status_code=409, detail="Requested quantity is unavailable")
    row = {"cart_id": cart["id"], "product_id": payload.product_id, "quantity": quantity,
           "selected_vehicle": payload.selected_vehicle.model_dump() if payload.selected_vehicle else None}
    await db.insert("cart_items", row, upsert=True, on_conflict="cart_id,product_id")
    return await _cart_response(cart)


@api.put("/cart")
async def update_cart(payload: CartUpdateInput, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    cart = await _cart_for(user, x_session_id, create=False)
    if not cart: return await _cart_response(None)
    if payload.quantity == 0:
        await db.delete("cart_items", params={"cart_id": f"eq.{cart['id']}", "product_id": f"eq.{payload.product_id}"})
    else:
        product = await catalog.product_by("id", payload.product_id)
        if not product or product["stock"] < payload.quantity: raise HTTPException(status_code=409, detail="Requested quantity is unavailable")
        await db.update("cart_items", {"quantity": payload.quantity}, params={"cart_id": f"eq.{cart['id']}", "product_id": f"eq.{payload.product_id}"})
    return await _cart_response(cart)


@api.delete("/cart/{product_id}")
async def remove_cart_item(product_id: str, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    return await update_cart(CartUpdateInput(product_id=product_id, quantity=0), x_session_id, user)


@api.delete("/cart")
async def clear_cart(x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    cart = await _cart_for(user, x_session_id, create=False)
    if cart: await db.delete("cart_items", params={"cart_id": f"eq.{cart['id']}"})
    return await _cart_response(cart)


async def _wishlist_response(user_id: str) -> dict[str, Any]:
    rows = await db.select("wishlists", params={"select": "product_id", "user_id": f"eq.{user_id}", "order": "created_at.desc"})
    if not rows: return {"items": []}
    ids = [row["product_id"] for row in rows]
    products = await db.select("products", params={"select": "*", "id": "in.(" + ",".join(ids) + ")", "status": "eq.active"})
    return {"items": await catalog.hydrate_products(products)}


@api.get("/wishlist")
async def get_wishlist(user: dict[str, Any] = Depends(require_user)): return await _wishlist_response(user["id"])


@api.post("/wishlist")
async def add_wishlist(payload: WishlistInput, user: dict[str, Any] = Depends(require_user)):
    if not await catalog.product_by("id", payload.product_id): raise HTTPException(status_code=404, detail="Product not found")
    await db.insert("wishlists", {"user_id": user["id"], "product_id": payload.product_id}, upsert=True, on_conflict="user_id,product_id")
    return await _wishlist_response(user["id"])


@api.delete("/wishlist/{product_id}")
async def remove_wishlist(product_id: str, user: dict[str, Any] = Depends(require_user)):
    await db.delete("wishlists", params={"user_id": f"eq.{user['id']}", "product_id": f"eq.{product_id}"})
    return await _wishlist_response(user["id"])


@api.post("/newsletter", status_code=201)
async def newsletter(payload: NewsletterInput, user: dict[str, Any] | None = Depends(optional_user)):
    await db.insert("newsletter_subscriptions", {"email": str(payload.email).lower(), "locale": payload.locale[:8],
                    "user_id": user["id"] if user else None, "unsubscribed_at": None}, upsert=True, on_conflict="email")
    return {"subscribed": True}


@api.post("/contact", status_code=201)
async def contact(payload: ContactInput, request: Request, user: dict[str, Any] | None = Depends(optional_user)):
    if payload.website: return {"received": True}
    _rate_limit(contact_attempts, _client_key(request), 5, 3600)
    await db.insert("contact_messages", {**payload.model_dump(exclude={"website"}), "email": str(payload.email), "user_id": user["id"] if user else None})
    return {"received": True}


@api.post("/admin/login", include_in_schema=False)
async def retired_admin_login(): raise HTTPException(status_code=410, detail="Use Supabase Auth")


@api.get("/admin/verify")
async def verify_admin(admin: dict[str, Any] = Depends(require_admin)): return {"authenticated": True, "user_id": admin["id"]}


@api.get("/admin/products")
async def admin_products(limit: int = Query(default=200, ge=1, le=500), admin: dict[str, Any] = Depends(require_admin)):
    rows = (await catalog.product_rows(public_only=False))[:limit]
    return {"items": await catalog.hydrate_products(rows, include_admin=True), "total": len(rows)}


@api.post("/admin/upload-image")
async def upload_image(file: UploadFile = File(...), admin: dict[str, Any] = Depends(require_admin)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "image/avif"}: raise HTTPException(status_code=415, detail="Unsupported image type")
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024: raise HTTPException(status_code=413, detail="Image exceeds 8 MB")
    signatures = (content.startswith(b"\xff\xd8\xff"), content.startswith(b"\x89PNG\r\n\x1a\n"), content[:4] in {b"RIFF", b"\x00\x00\x00\x1c", b"\x00\x00\x00\x20"})
    if len(content) < 12 or not any(signatures): raise HTTPException(status_code=400, detail="Invalid image")
    try:
        result = cloudinary.uploader.upload(content, folder="tymotors/products", resource_type="image", use_filename=False,
                                             unique_filename=True, overwrite=False,
                                             transformation=[{"quality": "auto:good", "fetch_format": "auto"}])
    except Exception:
        logger.exception("Cloudinary upload failed"); raise HTTPException(status_code=502, detail="Image storage failed")
    await _audit(admin, "image.upload", result.get("public_id", "unknown"), {"bytes": len(content)})
    return {"url": result["secure_url"], "public_id": result.get("public_id"), "width": result.get("width"), "height": result.get("height")}


@api.post("/admin/products", status_code=201)
async def create_product(payload: ProductInput, admin: dict[str, Any] = Depends(require_admin)):
    if not payload.slug: raise HTTPException(status_code=422, detail="slug is required")
    try: product = await catalog.write_product(payload)
    except (ValueError, SupabaseError) as error: raise HTTPException(status_code=422, detail=str(error))
    await _audit(admin, "product.create", product["id"], {"slug": product["slug"]}); return product


@api.put("/admin/products/{slug}")
async def update_product(slug: str, payload: ProductUpdateInput, admin: dict[str, Any] = Depends(require_admin)):
    current = await catalog.product_by("slug", slug, public_only=False, include_admin=True)
    if not current: raise HTTPException(status_code=404, detail="Product not found")
    merged = {**current, **payload.model_dump(exclude_unset=True), "slug": current["slug"]}
    for key in ("id", "image_records", "created_at"): merged.pop(key, None)
    try:
        product = await catalog.write_product(ProductInput.model_validate(merged), product_id=current["id"])
    except ValidationError as error: raise HTTPException(status_code=422, detail=error.errors())
    except (ValueError, SupabaseError) as error: raise HTTPException(status_code=422, detail=str(error))
    await _audit(admin, "product.update", product["id"], {"slug": slug}); return product


@api.delete("/admin/products/{slug}")
async def archive_product(slug: str, admin: dict[str, Any] = Depends(require_admin)):
    product = await catalog.product_by("slug", slug, public_only=False, include_admin=True)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    await db.update("products", {"status": "archived", "featured": False}, params={"id": f"eq.{product['id']}"})
    await _audit(admin, "product.archive", product["id"], {"slug": slug}); return {"archived": True}


async def _orders_with_items(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not orders: return []
    ids = [order["id"] for order in orders]
    rows = await db.select("order_items", params={"select": "*", "order_id": "in.(" + ",".join(ids) + ")", "order": "created_at.asc"})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        grouped.setdefault(item["order_id"], []).append({"product_id": item.get("product_id"), "name": item["product_name"],
            "slug": item["product_slug"], "sku": item["sku"], "quantity": item["quantity"], "unit_amount": item["unit_amount_cents"],
            "image": item.get("image_url"), "selected_vehicle": item.get("selected_vehicle"), "compatibility_result": item.get("compatibility_result")})
    return [{**order, "items": grouped.get(order["id"], [])} for order in orders]


@api.get("/admin/orders")
async def admin_orders(limit: int = Query(default=100, ge=1, le=500), admin: dict[str, Any] = Depends(require_admin)):
    rows = await db.select("orders", params={"select": "*", "order": "created_at.desc", "limit": limit})
    return {"items": await _orders_with_items(rows), "total": len(rows)}


@api.put("/admin/orders/{order_id}")
async def update_order(order_id: str, payload: AdminOrderUpdateInput, admin: dict[str, Any] = Depends(require_admin)):
    changes: dict[str, Any] = {"fulfillment_status": payload.fulfillment_status, "tracking_number": payload.tracking_number}
    if payload.fulfillment_status == "shipped": changes["shipped_at"] = datetime.now(timezone.utc).isoformat()
    rows = await db.update("orders", changes, params={"id": f"eq.{order_id}"})
    if not rows: raise HTTPException(status_code=404, detail="Order not found")
    await _audit(admin, "order.update", order_id, changes); return (await _orders_with_items(rows))[0]


@api.post("/create-checkout-session")
async def create_checkout_session(request: Request, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    if stripe_client is None: raise HTTPException(status_code=503, detail="Stripe test checkout is not configured")
    actor = user["id"] if user else _session_id(x_session_id); _rate_limit(checkout_attempts, actor, 8, 60)
    cart = await _cart_for(user, x_session_id, create=False); cart_view = await _cart_response(cart)
    if not cart or not cart_view["items"]: raise HTTPException(status_code=400, detail="Cart is empty")
    line_items, order_items, subtotal_cents, requires_review = [], [], 0, False
    for item in cart_view["items"]:
        quantity = item["quantity"]
        if item["status"] != "active" or item["stock"] < quantity: raise HTTPException(status_code=409, detail=f"Unavailable product: {item['name']}")
        compatibility_result = check_compatibility(item, VehicleSelection.model_validate(item["selected_vehicle"])) if item.get("selected_vehicle") else {"status": "unknown", "reason": "No vehicle selected"}
        if compatibility_result["status"] == "incompatible":
            raise HTTPException(status_code=409, detail=f"Produit incompatible avec le véhicule sélectionné : {item['name']}")
        requires_review = requires_review or compatibility_result["status"] != "compatible"
        unit_amount = round(item["price"] * 100); subtotal_cents += unit_amount * quantity
        product_data: dict[str, Any] = {"name": item["name"], "metadata": {"product_id": item["id"], "sku": item["sku"]}}
        if item["images"]: product_data["images"] = [item["images"][0]]
        line_items.append({"quantity": quantity, "price_data": {"currency": item["currency"].lower(), "unit_amount": unit_amount, "product_data": product_data}})
        order_items.append({"product_id": item["id"], "product_name": item["name"], "product_slug": item["slug"], "sku": item["sku"],
            "quantity": quantity, "unit_amount_cents": unit_amount, "currency": item["currency"], "image_url": item["images"][0] if item["images"] else None,
            "selected_vehicle": item.get("selected_vehicle"), "compatibility_result": compatibility_result})
    shipping = 0 if subtotal_cents >= settings.free_shipping_threshold_cents else settings.shipping_rate_cents
    order_payload = {"order_number": _order_number(), "user_id": user["id"] if user else None, "cart_id": cart["id"],
        "guest_session_id": None if user else x_session_id, "subtotal_cents": subtotal_cents, "shipping_amount_cents": shipping,
        "tax_amount_cents": 0, "total_cents": subtotal_cents + shipping, "currency": cart_view["currency"],
        "requires_compatibility_review": requires_review}
    if user:
        profiles = await db.select("profiles", params={"select": "email,full_name,stripe_customer_id", "id": f"eq.{user['id']}", "limit": 1})
        if profiles: order_payload.update(customer_email=profiles[0].get("email"), customer_name=profiles[0].get("full_name"))
    order = (await db.insert("orders", order_payload))[0]
    await db.insert("order_items", [{**item, "order_id": order["id"]} for item in order_items])
    if shipping: line_items.append({"quantity": 1, "price_data": {"currency": cart_view["currency"].lower(), "unit_amount": shipping, "product_data": {"name": "Livraison suivie"}}})
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    params: dict[str, Any] = {"mode": "payment", "line_items": line_items,
        "success_url": f"{settings.frontend_url}/order-success?session_id={{CHECKOUT_SESSION_ID}}", "cancel_url": f"{settings.frontend_url}/cart?checkout=cancelled",
        "client_reference_id": order["id"], "integration_identifier": f"tymotors_checkout_{suffix}",
        "metadata": {"order_id": order["id"], "user_id": user["id"] if user else "guest"},
        "payment_intent_data": {"metadata": {"order_id": order["id"], "user_id": user["id"] if user else "guest"}},
        "shipping_address_collection": {"allowed_countries": ["FR", "BE", "DE", "ES", "IT", "LU", "NL", "PT"]},
        "billing_address_collection": "required", "phone_number_collection": {"enabled": True}}
    if order_payload.get("customer_email"): params["customer_email"] = order_payload["customer_email"]
    if os.getenv("STRIPE_AUTOMATIC_TAX", "false").lower() == "true": params["automatic_tax"] = {"enabled": True}
    try:
        session = await stripe_client.v1.checkout.sessions.create_async(params=params, options={"idempotency_key": f"checkout_{order['id']}"})
    except stripe.StripeError:
        await db.update("orders", {"status": "payment_failed", "payment_status": "failed"}, params={"id": f"eq.{order['id']}"})
        logger.exception("Stripe Checkout creation failed"); raise HTTPException(status_code=502, detail="Unable to create secure checkout")
    await db.update("orders", {"stripe_session_id": session.id}, params={"id": f"eq.{order['id']}"})
    return {"url": session.url, "order_reference": order["order_number"]}


@api.get("/checkout-session/{stripe_session_id}")
async def checkout_session(stripe_session_id: str, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    rows = await db.select("orders", params={"select": "*", "stripe_session_id": f"eq.{stripe_session_id}", "limit": 1})
    if not rows: raise HTTPException(status_code=404, detail="Order not found")
    order = rows[0]; allowed = bool(user and order.get("user_id") == user["id"]) or bool(not user and x_session_id and order.get("guest_session_id") == x_session_id)
    if not allowed: raise HTTPException(status_code=403, detail="Order access denied")
    if order.get("payment_status") != "paid" and stripe_client is not None:
        try:
            session = await stripe_client.v1.checkout.sessions.retrieve_async(stripe_session_id)
            session_data = session.to_dict()
            if session_data.get("payment_status") == "paid":
                await _complete_checkout_payment(session_data)
                rows = await db.select("orders", params={"select": "*", "id": f"eq.{order['id']}", "limit": 1})
                order = rows[0]
        except stripe.StripeError:
            logger.exception("Unable to reconcile Stripe Checkout session %s", stripe_session_id)
    result = (await _orders_with_items([order]))[0]
    return {"paid": result["payment_status"] == "paid", "status": result["status"], "payment_status": result["payment_status"],
        "order_reference": result["order_number"], "customer_email": result.get("customer_email"), "items": result["items"],
        "subtotal": result["subtotal_cents"] / 100, "shipping": result["shipping_amount_cents"] / 100,
        "tax": result["tax_amount_cents"] / 100, "total": result["total_cents"] / 100, "currency": result["currency"],
        "shipping_address": result.get("shipping_address") or {}}


async def _complete_checkout_payment(obj: Any) -> str | None:
    if obj.get("payment_status") != "paid":
        return None
    order_id = (obj.get("metadata") or {}).get("order_id")
    if not order_id:
        return None
    order_rows = await db.select("orders", params={
        "select": "id,total_cents,currency,stripe_session_id", "id": f"eq.{order_id}", "limit": 1,
    })
    if not order_rows:
        raise RuntimeError("Stripe event references an unknown order")
    expected = order_rows[0]
    if (
        obj.get("id") != expected.get("stripe_session_id")
        or obj.get("client_reference_id") != order_id
        or obj.get("amount_total") != expected.get("total_cents")
        or (obj.get("currency") or "").upper() != expected.get("currency")
    ):
        raise RuntimeError("Stripe Checkout totals or references do not match the order")
    customer = obj.get("customer_details") or {}
    collected = obj.get("collected_information") or {}
    shipping = obj.get("shipping_details") or collected.get("shipping_details") or {}
    completed = await db.rpc("complete_paid_order", {"p_order_id": order_id, "p_payment_intent_id": obj.get("payment_intent"),
        "p_customer_email": customer.get("email"), "p_customer_name": customer.get("name"),
        "p_shipping_address": _address(shipping.get("address")), "p_billing_address": _address(customer.get("address"))})
    if completed is not True:
        raise RuntimeError("Order completion transaction was not applied")
    orders = await db.select("orders", params={"select": "user_id", "id": f"eq.{order_id}", "limit": 1})
    if orders and orders[0].get("user_id") and obj.get("customer"):
        await db.update("profiles", {"stripe_customer_id": obj.get("customer")}, params={"id": f"eq.{orders[0]['user_id']}"})
    return order_id


@api.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")):
    if not settings.stripe_webhook_secret or not stripe_signature: raise HTTPException(status_code=400, detail="Missing webhook signature")
    payload = await request.body()
    try: event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError): raise HTTPException(status_code=400, detail="Invalid webhook signature")
    event_id = event["id"]; existing = await db.select("stripe_events", params={"select": "status", "event_id": f"eq.{event_id}", "limit": 1})
    if existing and existing[0]["status"] == "completed": return {"received": True, "duplicate": True}
    if not existing:
        try: await db.insert("stripe_events", {"event_id": event_id, "event_type": event["type"], "status": "processing"})
        except SupabaseError as error:
            if error.status_code != 409: raise
    try:
        obj = event["data"]["object"]; event_type = event["type"]
        if event_type == "checkout.session.completed" and obj.get("payment_status") == "paid":
            await _complete_checkout_payment(obj)
        elif event_type == "payment_intent.payment_failed":
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id: await db.update("orders", {"status": "payment_failed", "payment_status": "failed"}, params={"id": f"eq.{order_id}", "payment_status": "neq.paid"})
        elif event_type in {"charge.refunded", "refund.created"} and obj.get("payment_intent"):
            await db.update("orders", {"status": "refunded", "payment_status": "refunded"}, params={"stripe_payment_intent_id": f"eq.{obj['payment_intent']}"})
        await db.update("stripe_events", {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}, params={"event_id": f"eq.{event_id}"})
    except Exception as error:
        await db.update("stripe_events", {"status": "failed", "error_message": type(error).__name__}, params={"event_id": f"eq.{event_id}"})
        logger.exception("Stripe event processing failed: %s", event_id); raise HTTPException(status_code=500, detail="Webhook processing failed")
    return {"received": True}


app.include_router(api)


@app.exception_handler(SupabaseError)
async def supabase_error_handler(_: Request, error: SupabaseError):
    from fastapi.responses import JSONResponse
    logger.error("Supabase request failed with status %s", error.status_code)
    return JSONResponse(status_code=error.status_code if error.status_code in {400, 404, 409, 422} else 502,
                        content={"detail": "Database request failed"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
    if request.url.scheme == "https": response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/admin") or "checkout" in request.url.path else "no-cache"
    return response


app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=settings.cors_origins,
                   allow_origin_regex=settings.cors_origin_regex, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Session-Id", "Stripe-Signature"])

# Stable aliases used by migration tooling and tests.
ProductCreateInput = ProductInput
