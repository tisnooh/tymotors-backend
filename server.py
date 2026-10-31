from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import random
import re
import string
import time
from typing import Any, Literal
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
from fastapi.exceptions import RequestValidationError
import httpx
from app.request_guard import RequestGuard

from app.compatibility import check_compatibility
from app.vehicle_catalog import matches_verified_vehicle
from app.catalog_availability import purchase_availability, purchasable
from app.admin import create_admin_router, search_filter, product_input_data
from app.config import Settings, get_settings
from app.schemas import (
    AdminOrderUpdateInput, AuthEmailInput, CartItemInput, CartUpdateInput, ContactInput,
    EmailPreferencesInput, NewsletterInput, OrderTrackingLookupInput, ProductInput, ProductUpdateInput, ProfileUpdateInput,
    VehicleSelection, WelcomeEmailInput, WishlistInput, WithdrawalInput, LoginInput, WithdrawalStatusInput,
)
from app.services.email_service import EmailService
from app.services.email_templates import newsletter_confirmation, order_event, welcome
from app.services.email_tokens import hash_confirmation_token, new_confirmation_token, verify_token
from app.store import CatalogStore
from app.site_config import public_site_configuration, order_document, legal_ready
from app.services.email_templates import EmailContent, _layout
from app.supabase_rest import SupabaseError, SupabaseRest

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
logger = logging.getLogger("tymotors")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
# HTTP client URLs include PostgREST filters; access URLs may contain newsletter
# confirmation tokens. Keep structured application errors, never raw URL logs.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('uvicorn.access').disabled = True

settings: Settings = get_settings()
db = SupabaseRest(settings.supabase_url, settings.supabase_service_role_key, settings.supabase_publishable_key)
catalog = CatalogStore(db)
stripe_client: StripeClient | None = None
bearer = HTTPBearer(auto_error=False)
checkout_attempts: dict[str, list[float]] = {}
contact_attempts: dict[str, list[float]] = {}
newsletter_attempts: dict[str, list[float]] = {}
auth_email_attempts: dict[str, list[float]] = {}
tracking_attempts: dict[str, list[float]] = {}
login_attempts: dict[str, list[float]] = {}
email_service = EmailService(settings, db)


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
app.add_middleware(RequestGuard)
api = APIRouter(prefix="/api")


@api.get('/site-config')
async def site_configuration():
    return public_site_configuration(settings)


def _rate_limit(bucket: dict[str, list[float]], key: str, maximum: int, window: int) -> None:
    now = time.monotonic()
    # Bounded process-local storage. Multi-worker deployments need a shared limiter.
    if key not in bucket and len(bucket) >= 10000:
        for old_key, stamps in list(bucket.items()):
            if not stamps or now - stamps[-1] >= window:
                bucket.pop(old_key, None)
        if len(bucket) >= 10000:
            raise HTTPException(429, 'Too many requests', headers={'Retry-After': str(window)})
    current = [stamp for stamp in bucket.get(key, []) if now - stamp < window]
    if len(current) >= maximum:
        raise HTTPException(status_code=429, detail="Too many requests", headers={'Retry-After': str(max(1, int(window - (now - current[0])) + 1))})
    current.append(now)
    bucket[key] = current


def _client_key(request: Request) -> str:
    # Uvicorn's trusted-proxy configuration owns proxy interpretation, never a raw client header.
    return request.client.host if request.client else "unknown"


def _checkout_frontend_url(request: Request) -> str:
    """Return only a configured/allow-listed frontend origin for Stripe redirects."""
    origin = request.headers.get("origin", "").rstrip("/")
    if origin in settings.cors_origins:
        return origin
    if origin and settings.cors_origin_regex and re.fullmatch(settings.cors_origin_regex, origin):
        return origin
    return settings.frontend_url


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


@api.get('/admin/orders/{order_id}/document')
async def admin_order_document(order_id: uuid.UUID, admin=Depends(require_admin)):
    rows = await db.select('orders', params={'id': f'eq.{order_id}', 'limit': 1})
    if not rows: raise HTTPException(404, 'Order not found')
    items = await db.select('order_items', params={'order_id': f'eq.{order_id}'})
    return order_document(rows[0], items)


@api.post('/withdrawals', status_code=201)
async def withdrawal(payload: WithdrawalInput, request: Request):
    from html import escape
    _rate_limit(contact_attempts, 'withdrawal:'+_client_key(request), 5, 3600)
    rows = await db.select('orders', params={'select':'id,order_number', 'order_number':f'eq.{payload.order_number}', 'customer_email':f'eq.{str(payload.email).lower()}', 'limit':1})
    if not rows: raise HTTPException(404, 'Commande introuvable pour ces informations')
    stamp = datetime.now(timezone.utc).isoformat()
    receipt = f'Demande de rétractation reçue le {stamp}\nCommande : {payload.order_number}\nNom : {payload.name}\nJe vous notifie ma rétractation du contrat.\n{payload.message}'
    saved = await db.insert('contact_messages', {'name':payload.name, 'email':str(payload.email).lower(), 'subject':'Rétractation '+payload.order_number, 'message':receipt})
    html, text = _layout('Votre demande de rétractation est enregistrée', '<p style="color:#C7CDD6;white-space:pre-wrap">'+escape(receipt)+'</p><p>Conservez cet accusé de réception. Aucun remboursement n’est déclenché automatiquement.</p>', receipt)
    sent = False
    try:
        delivered = await email_service.send(recipient=str(payload.email), email_type='withdrawal_received', content=EmailContent('TYMotors — demande de rétractation reçue',html,text), idempotency_key='withdrawal:'+saved[0]['id'], order_id=rows[0]['id'], metadata={'receipt_text':receipt})
        sent = delivered.get('sent', False)
    except Exception:
        logger.warning('Withdrawal stored; email receipt unavailable')
    return {'reference':saved[0]['id'], 'received_at':stamp, 'receipt_text':receipt, 'email_sent':sent}


def _session_id(value: str | None) -> str:
    if not value or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', value):
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
    rows = await db.select("products", params={"select": "*", "id": "in.(" + ",".join(product_ids) + ")", "status": "in.(active,draft)" if settings.test_catalog_available else "eq.active"})
    products = await catalog.hydrate_products(rows); by_id = {p["id"]: purchase_availability(p, settings) for p in products}
    items, subtotal_cents = [], 0
    for row in item_rows:
        product = by_id.get(row["product_id"])
        if not product: continue
        quantity = row["quantity"]
        unit_amount_cents = product["price_cents"]
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


async def _send_order_email(kind: str, order_id: str, *, amount_cents: int | None = None,
                            retry_log_id: str | None = None) -> dict[str, Any] | None:
    """Best-effort delivery after the database transition has committed."""
    try:
        rows = await db.select("orders", params={"select": "*", "id": f"eq.{order_id}", "limit": 1})
        if not rows or not rows[0].get("customer_email"):
            return
        order = rows[0]
        items = await db.select("order_items", params={"select": "*", "order_id": f"eq.{order_id}", "order": "created_at.asc"})
        content = order_event(kind, order, items, f"{settings.frontend_url}/account/orders/{order_id}", amount_cents=amount_cents)
        suffix = str(amount_cents) if kind == "refund_confirmed" else "once"
        if retry_log_id:
            return await email_service.retry(retry_log_id, order["customer_email"], content)
        return await email_service.send(recipient=order["customer_email"], email_type=kind, content=content,
                idempotency_key=f"order:{order_id}:{kind}:{suffix}", user_id=order.get("user_id"), order_id=order_id,
                metadata={"order_number": order.get("order_number"), **({"amount_cents": amount_cents} if amount_cents is not None else {})})
    except Exception:
        logger.error("Order email queue unavailable: %s %s", kind, order_id)
        return None


async def _start_newsletter_subscription(payload: NewsletterInput, user: dict[str, Any] | None) -> dict[str, bool]:
    email = email_service.normalize_email(str(payload.email))
    current = await db.select("newsletter_subscribers", params={"select": "id,status", "email": f"eq.{email}", "limit": 1})
    if current and current[0].get("status") == "subscribed":
        return {"pending": False, "already_subscribed": True}
    raw_token, token_hash = new_confirmation_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    rows = await db.insert("newsletter_subscribers", {
        "email": email, "locale": payload.locale[:8], "user_id": user["id"] if user else None,
        "status": "pending", "consent_source": payload.consent_source,
        "consent_at": datetime.now(timezone.utc).isoformat(), "confirmed_at": None, "unsubscribed_at": None,
        "confirmation_token_hash": token_hash, "confirmation_expires_at": expires_at,
    }, upsert=True, on_conflict="email")
    subscriber_id = rows[0]["id"]
    confirm_url = f"{settings.frontend_url}/newsletter/confirm?token={raw_token}"
    await email_service.send(recipient=email, email_type="newsletter_confirmation",
        content=newsletter_confirmation(confirm_url), idempotency_key=f"newsletter-confirm:{subscriber_id}:{token_hash[:16]}",
        user_id=user["id"] if user else None, metadata={"subscriber_id": subscriber_id})
    return {"pending": True, "already_subscribed": False}


@api.get("/")
async def root(): return {"message": "TYMotors API", "version": "2.0.0", "database": "supabase"}


@api.get("/health")
async def health():
    try:
        await db.select("brands", params={"select": "id", "limit": 1})
    except (SupabaseError, httpx.RequestError):
        raise HTTPException(503, 'Service unavailable') from None
    return {"status": "ok"}


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
                        preview: bool = False,
                        strict_vehicle: bool = False, trim: str | None = None,
                        facelift: Literal['pre-lci', 'lci', 'unknown'] | None = None,
                        has_camera: bool | None = None, has_parking_sensors: bool | None = None,
                        sort: str = Query(default="newest", pattern="^(relevance|newest|price_asc|price_desc|name)$"),
                        page: int = Query(default=1, ge=1), limit: int = Query(default=24, ge=1, le=100)):
    products = await catalog.hydrate_products(await catalog.product_rows(public_only=False))
    products = [product for product in products if product.get("status") != "archived"]
    products = [purchase_availability(product, settings) for product in products]
    category = {"performance": "exterior", "technology": "multimedia-technology"}.get(category, category)
    if category: products = [p for p in products if p["category_slug"] == category]
    if featured is not None: products = [p for p in products if p["featured"] is featured]
    if q:
        term = q.strip().casefold(); products = [p for p in products if term in f"{p['name']} {p['subtitle']} {p['sku']}".casefold()]
    if strict_vehicle:
        if not brand or not brand.strip() or not model or not model.strip() or not chassis or not chassis.strip():
            raise HTTPException(422, "La marque, le modèle et la génération sont requis")
        try:
            vehicle = VehicleSelection(brand_slug=brand, model=model, chassis=chassis, year=year,
                                       body_type=body_type, trim=trim, facelift=facelift, has_camera=has_camera,
                                       has_parking_sensors=has_parking_sensors)
        except ValidationError:
            raise HTTPException(422, "Sélection de véhicule invalide") from None
        products = [p for p in products if matches_verified_vehicle(p, vehicle)]
    else:
        if brand: products = [p for p in products if brand in p["compatible_brands"] or any(c.get("brand_slug") == brand for c in p["compatibilities"])]
        if model: products = [p for p in products if p.get("status") != "active" or any((c.get("model") or "").casefold() == model.casefold() for c in p["compatibilities"])]
        if chassis: products = [p for p in products if p.get("status") != "active" or any(chassis.casefold() in {(c.get("chassis") or "").casefold(), (c.get("generation") or "").casefold()} for c in p["compatibilities"])]
        if year is not None: products = [p for p in products if p.get("status") != "active" or any((c.get("year_from") is None or year >= c["year_from"]) and (c.get("year_to") is None or year <= c["year_to"]) for c in p["compatibilities"])]
        if body_type: products = [p for p in products if p.get("status") != "active" or any(not c.get("body_types") or body_type.casefold() in {v.casefold() for v in c["body_types"]} for c in p["compatibilities"])]
    if sort == "price_asc": products.sort(key=lambda p: p["price"])
    elif sort == "price_desc": products.sort(key=lambda p: p["price"], reverse=True)
    elif sort == "name": products.sort(key=lambda p: p["name"].casefold())
    else: products.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    total = len(products); start = (page - 1) * limit
    result = {"items": products[start:start + limit], "total": total, "page": page, "limit": limit, "pages": (total + limit - 1) // limit}
    if strict_vehicle:
        result["fitment_scope"] = "verified_vehicle"
    return result


@api.get("/products/{slug}")
async def get_product(slug: str, preview: bool = False):
    product = await catalog.product_by("slug", slug, public_only=False)
    if product and product.get("status") == "archived":
        product = None
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    return purchase_availability(product, settings)


@api.post("/products/{slug}/compatibility")
async def product_compatibility(slug: str, vehicle: VehicleSelection):
    product = await _purchasable_product("slug", slug)
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


async def _purchasable_product(field: str, value: str) -> dict[str, Any] | None:
    product = await catalog.product_by(field, value, public_only=not settings.test_catalog_available)
    if not product or product.get('status') not in ({'active', 'draft'} if settings.test_catalog_available else {'active'}):
        return None
    return purchase_availability(product, settings)


@api.post("/cart")
async def add_to_cart(payload: CartItemInput, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    product = await _purchasable_product("id", payload.product_id)
    if not product: raise HTTPException(status_code=404, detail="Active product not found")
    if not purchasable(product, settings, payload.quantity): raise HTTPException(status_code=409, detail="Insufficient stock")
    cart = await _cart_for(user, x_session_id); assert cart
    existing = await db.select("cart_items", params={"select": "*", "cart_id": f"eq.{cart['id']}", "product_id": f"eq.{payload.product_id}", "limit": 1})
    quantity = payload.quantity + (existing[0]["quantity"] if existing else 0)
    if not purchasable(product, settings, quantity): raise HTTPException(status_code=409, detail="Requested quantity is unavailable")
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
        product = await _purchasable_product("id", payload.product_id)
        if not product or not purchasable(product, settings, payload.quantity): raise HTTPException(status_code=409, detail="Requested quantity is unavailable")
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
    products = await db.select("products", params={"select": "*", "id": "in.(" + ",".join(ids) + ")", "status": "in.(active,draft)" if settings.test_catalog_available else "eq.active"})
    return {"items": [purchase_availability(p, settings) for p in await catalog.hydrate_products(products)]}


@api.get("/wishlist")
async def get_wishlist(user: dict[str, Any] = Depends(require_user)): return await _wishlist_response(user["id"])


@api.post("/wishlist")
async def add_wishlist(payload: WishlistInput, user: dict[str, Any] = Depends(require_user)):
    if not await _purchasable_product("id", payload.product_id): raise HTTPException(status_code=404, detail="Product not found")
    await db.insert("wishlists", {"user_id": user["id"], "product_id": payload.product_id}, upsert=True, on_conflict="user_id,product_id")
    return await _wishlist_response(user["id"])


@api.delete("/wishlist/{product_id}")
async def remove_wishlist(product_id: str, user: dict[str, Any] = Depends(require_user)):
    await db.delete("wishlists", params={"user_id": f"eq.{user['id']}", "product_id": f"eq.{product_id}"})
    return await _wishlist_response(user["id"])


@api.post("/newsletter", status_code=202)
async def newsletter(payload: NewsletterInput, request: Request, user: dict[str, Any] | None = Depends(optional_user)):
    if payload.website:
        return {"pending": True, "already_subscribed": False}
    _rate_limit(newsletter_attempts, 'ip:'+_client_key(request), 10, 3600)
    _rate_limit(newsletter_attempts, f"{_client_key(request)}:{str(payload.email).lower()}", 4, 3600)
    return await _start_newsletter_subscription(payload, user)


@api.get("/newsletter/confirm")
async def confirm_newsletter(token: str = Query(min_length=32, max_length=200)):
    token_hash = hash_confirmation_token(token)
    rows = await db.select("newsletter_subscribers", params={
        "select": "id,status,confirmation_expires_at", "confirmation_token_hash": f"eq.{token_hash}", "limit": 1,
    })
    if not rows:
        raise HTTPException(status_code=400, detail="Invalid newsletter confirmation link")
    subscriber = rows[0]
    if subscriber["status"] == "subscribed":
        return {"confirmed": True, "already_confirmed": True}
    expires = subscriber.get("confirmation_expires_at")
    if not expires or datetime.fromisoformat(expires.replace("Z", "+00:00")) < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Newsletter confirmation link expired")
    await db.update("newsletter_subscribers", {
        "status": "subscribed", "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "unsubscribed_at": None, "confirmation_expires_at": None,
    }, params={"id": f"eq.{subscriber['id']}", "status": "eq.pending"})
    return {"confirmed": True, "already_confirmed": False}


@api.get("/newsletter/unsubscribe")
async def unsubscribe_newsletter(token: str = Query(min_length=32, max_length=1000)):
    payload = verify_token(settings.email_token_secret, token, purpose="newsletter_unsubscribe")
    if not payload or not payload.get("subscriber_id"):
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link")
    await db.update("newsletter_subscribers", {
        "status": "unsubscribed", "unsubscribed_at": datetime.now(timezone.utc).isoformat(),
        "confirmation_token_hash": None, "confirmation_expires_at": None,
    }, params={"id": f"eq.{payload['subscriber_id']}"})
    return {"unsubscribed": True}


@api.get("/me/email-preferences")
async def email_preferences(user: dict[str, Any] = Depends(require_user)):
    email = email_service.normalize_email(user.get("email") or "")
    rows = await db.select("newsletter_subscribers", params={"select": "status", "email": f"eq.{email}", "limit": 1})
    status = rows[0]["status"] if rows else "unsubscribed"
    return {"newsletter": status == "subscribed", "status": status, "transactional": True}


@api.patch("/me/email-preferences")
async def update_email_preferences(payload: EmailPreferencesInput, request: Request,
                                   user: dict[str, Any] = Depends(require_user)):
    email = email_service.normalize_email(user.get("email") or "")
    if payload.newsletter:
        _rate_limit(newsletter_attempts, f"account:{user['id']}", 4, 3600)
        result = await _start_newsletter_subscription(
            NewsletterInput(email=email, locale="fr", consent_source="account"), user,
        )
        return {"newsletter": False, "status": "pending", **result, "transactional": True}
    rows = await db.select("newsletter_subscribers", params={"select": "id", "email": f"eq.{email}", "limit": 1})
    changes = {"status": "unsubscribed", "unsubscribed_at": datetime.now(timezone.utc).isoformat(),
               "confirmation_token_hash": None, "confirmation_expires_at": None}
    if rows:
        await db.update("newsletter_subscribers", changes, params={"id": f"eq.{rows[0]['id']}"})
    else:
        await db.insert("newsletter_subscribers", {**changes, "email": email, "user_id": user["id"],
            "locale": "fr", "consent_source": "account", "consent_at": datetime.now(timezone.utc).isoformat()})
    return {"newsletter": False, "status": "unsubscribed", "transactional": True}


@api.post("/auth/forgot-password", status_code=202)
async def forgot_password(payload: AuthEmailInput, request: Request):
    _rate_limit(auth_email_attempts, f'forgot-ip:{_client_key(request)}', 10, 3600)
    _rate_limit(auth_email_attempts, f"forgot:{_client_key(request)}:{str(payload.email).lower()}", 4, 3600)
    await db.send_password_recovery(str(payload.email).lower(), f"{settings.frontend_url}/reset-password")
    return {"accepted": True}


@api.post("/auth/resend-confirmation", status_code=202)
async def resend_confirmation(payload: AuthEmailInput, request: Request):
    _rate_limit(auth_email_attempts, f'resend-ip:{_client_key(request)}', 10, 3600)
    _rate_limit(auth_email_attempts, f"resend:{_client_key(request)}:{str(payload.email).lower()}", 4, 3600)
    await db.resend_signup_confirmation(str(payload.email).lower(), f"{settings.frontend_url}/auth/confirm")
    return {"accepted": True}


@api.post('/auth/login')
async def login(payload: LoginInput, request: Request):
    _rate_limit(login_attempts, 'ip:'+_client_key(request), 5, 60)
    import hashlib
    identity = hashlib.sha256(str(payload.email).lower().encode()).hexdigest()
    _rate_limit(login_attempts, 'email:'+identity, 8, 900)
    try:
        return await db.sign_in_password(str(payload.email).lower(), payload.password)
    except SupabaseError as error:
        raise HTTPException(error.status_code, error.detail,
                            headers={'Retry-After':'60'} if error.status_code == 429 else None) from None


@api.post("/auth/welcome", status_code=202)
async def send_welcome(payload: WelcomeEmailInput, user: dict[str, Any] = Depends(require_user)):
    if not user.get("email_confirmed_at"):
        raise HTTPException(status_code=409, detail="Email confirmation required")
    recipient = email_service.normalize_email(user.get("email") or "")
    first_name = payload.first_name or (user.get("user_metadata") or {}).get("full_name")
    first_name = first_name.strip().split()[0] if isinstance(first_name, str) and first_name.strip() else None
    result = await email_service.send(recipient=recipient, email_type="welcome",
        content=welcome(first_name, f"{settings.frontend_url}/account"), idempotency_key=f"welcome:{user['id']}",
        user_id=user["id"])
    return {"accepted": True, "delivery": result["status"]}


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
async def admin_products(limit: int = Query(default=25, ge=1, le=100), page: int = Query(1, ge=1),
                         q: str = Query("", max_length=120), status: str = Query("", pattern="^(|draft|active|archived)$"),
                         admin: dict[str, Any] = Depends(require_admin)):
    params = {"select": "*", "order": "created_at.desc,id.desc"}
    if q: params["or"] = search_filter(q, ["name", "sku"])
    if status: params["status"] = f"eq.{status}"
    result = await db.page("products", params=params, page=page, limit=limit)
    result["items"] = await catalog.hydrate_products(result["items"], include_admin=True)
    return result


@api.post("/admin/upload-image")
async def upload_image(file: UploadFile = File(...), admin: dict[str, Any] = Depends(require_admin)):
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "image/avif"}: raise HTTPException(status_code=415, detail="Unsupported image type")
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024: raise HTTPException(status_code=413, detail="Image exceeds 8 MB")
    from app.product_image_policy import image_bytes_usage_denied
    if image_bytes_usage_denied(content):
        raise HTTPException(status_code=422, detail="Image use denied by its source; upload an independently authorized replacement")
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        "image/avif": content[4:8] == b"ftyp" and b"avif" in content[8:32],
    }
    if len(content) < 12 or not signatures[file.content_type]: raise HTTPException(status_code=400, detail="Invalid image")
    try:
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(cloudinary.uploader.upload, content, folder="tymotors/products", resource_type="image", use_filename=False,
                                             unique_filename=True, overwrite=False,
                                             transformation=[{"quality": "auto:good", "fetch_format": "auto"}])
    except Exception:
        logger.error("Cloudinary upload failed"); raise HTTPException(status_code=502, detail="Image storage failed")
    await _audit(admin, "image.upload", result.get("public_id", "unknown"), {"bytes": len(content)})
    return {"url": result["secure_url"], "public_id": result.get("public_id"), "width": result.get("width"), "height": result.get("height")}


@api.post("/admin/products", status_code=201)
async def create_product(payload: ProductInput, admin: dict[str, Any] = Depends(require_admin)):
    if not payload.slug: raise HTTPException(status_code=422, detail="slug is required")
    try: return await catalog.write_product_atomic(payload, actor=admin["id"])
    except ValueError as error: raise HTTPException(status_code=422, detail=str(error))


@api.put("/admin/products/{slug}")
async def update_product(slug: str, payload: ProductUpdateInput, admin: dict[str, Any] = Depends(require_admin)):
    current = await catalog.product_by("slug", slug, public_only=False, include_admin=True)
    if not current: raise HTTPException(status_code=404, detail="Product not found")
    merged = {**product_input_data(current, ProductInput), **payload.model_dump(exclude_unset=True, exclude={"expected_updated_at"})}
    try:
        return await catalog.write_product_atomic(ProductInput.model_validate(merged), actor=admin["id"],
            product_id=current["id"], expected_updated_at=payload.expected_updated_at)
    except ValidationError as error: raise HTTPException(status_code=422, detail=error.errors(include_context=False))
    except ValueError as error: raise HTTPException(status_code=422, detail=str(error))


@api.delete("/admin/products/{slug}")
async def archive_product(slug: str, admin: dict[str, Any] = Depends(require_admin)):
    product = await catalog.product_by("slug", slug, public_only=False, include_admin=True)
    if not product: raise HTTPException(status_code=404, detail="Product not found")
    await db.rpc("admin_save_record", {"p_actor": admin["id"], "p_kind": "archive", "p_id": product["id"], "p_data": {}})
    return {"archived": True}


async def _orders_with_items(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.product_image_policy import permitted_image
    if not orders: return []
    ids = [order["id"] for order in orders]
    rows = await db.select("order_items", params={"select": "*", "order_id": "in.(" + ",".join(ids) + ")", "order": "created_at.asc"})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        grouped.setdefault(item["order_id"], []).append({"product_id": item.get("product_id"), "name": item["product_name"],
            "slug": item["product_slug"], "sku": item["sku"], "quantity": item["quantity"], "unit_amount": item["unit_amount_cents"],
            "image": permitted_image(item.get("image_url")), "selected_vehicle": item.get("selected_vehicle"), "compatibility_result": item.get("compatibility_result")})
    events = await db.select("order_tracking_events", params={"select": "*", "order_id": "in.(" + ",".join(ids) + ")", "order": "occurred_at.asc,id.asc"})
    grouped_events: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("is_customer_visible"):
            grouped_events.setdefault(event["order_id"], []).append(event)
    return [{**order, "items": grouped.get(order["id"], []), "tracking_events": grouped_events.get(order["id"], [])} for order in orders]


@api.post("/order-tracking")
async def order_tracking(payload: OrderTrackingLookupInput, request: Request):
    _rate_limit(tracking_attempts, _client_key(request), 10, 300)
    rows = await db.select("orders", params={
        "select": "id,order_number,customer_email,payment_status,fulfillment_status,carrier,tracking_number,tracking_url,created_at,paid_at,shipped_at,delivered_at",
        "order_number": f"eq.{payload.order_number.upper()}",
        "limit": 1,
    })
    if not rows or (rows[0].get("customer_email") or "").casefold() != str(payload.email).casefold():
        raise HTTPException(status_code=404, detail="Commande introuvable avec ces informations")
    order = rows[0]
    order.pop("customer_email", None)
    events = await db.select("order_tracking_events", params={"select": "*", "order_id": f"eq.{order['id']}", "order": "occurred_at.asc,id.asc"})
    public_events = [{key: event.get(key) for key in ("id", "title", "description", "occurred_at")}
                     for event in events if event.get("is_customer_visible")]
    order.pop("id", None)
    return {**order, "tracking_events": public_events}


@api.get("/admin/orders")
async def admin_orders(limit: int = Query(default=25, ge=1, le=100), page: int = Query(1, ge=1),
                       q: str = Query("", max_length=120),
                       status: str = Query("", pattern="^(|pending|paid|processing|shipped|delivered|cancelled|refunded)$"),
                       admin: dict[str, Any] = Depends(require_admin)):
    params = {"select": "*", "order": "created_at.desc,id.desc"}
    if q: params["or"] = search_filter(q, ["order_number", "customer_email", "customer_name"])
    if status: params["fulfillment_status" if status in {"processing", "shipped", "delivered"} else "status"] = f"eq.{status}"
    return await db.page("orders", params=params, page=page, limit=limit)


@api.get("/admin/email-center")
async def admin_email_center(admin: dict[str, Any] = Depends(require_admin)):
    async def count(table: str, params: dict[str, Any]) -> int:
        return (await db.page(table, params={"select": "id", **params}, page=1, limit=1))["total"]
    return {
        "newsletter": {
            status: await count("newsletter_subscribers", {"status": f"eq.{status}"})
            for status in ("subscribed", "pending", "unsubscribed")
        },
        "emails": {
            status: await count("email_logs", {"status": f"eq.{status}"})
            for status in ("sent", "queued", "failed")
        },
        "recent": await db.select("email_logs", params={
            "select": "id,order_id,recipient,email_type,status,error_message,sent_at,created_at",
            "order": "created_at.desc", "limit": 25,
        }),
    }


@api.get("/admin/email-logs")
async def admin_email_logs(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                           status: str = Query("", pattern="^(|queued|sent|failed)$"),
                           admin: dict[str, Any] = Depends(require_admin)):
    params = {"select": "*", "order": "created_at.desc,id.desc"}
    if status:
        params["status"] = f"eq.{status}"
    return await db.page("email_logs", params=params, page=page, limit=limit)


@api.get("/admin/newsletter-subscribers")
async def admin_newsletter_subscribers(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                                       status: str = Query("", pattern="^(|pending|subscribed|unsubscribed)$"),
                                       admin: dict[str, Any] = Depends(require_admin)):
    params = {"select": "id,email,status,consent_source,consent_at,confirmed_at,unsubscribed_at,created_at",
              "order": "created_at.desc,id.desc"}
    if status:
        params["status"] = f"eq.{status}"
    return await db.page("newsletter_subscribers", params=params, page=page, limit=limit)


@api.post("/admin/email-logs/{log_id}/retry", status_code=202)
async def retry_email(log_id: str, admin: dict[str, Any] = Depends(require_admin)):
    try:
        log_id = str(uuid.UUID(log_id))
    except ValueError:
        raise HTTPException(422, "Invalid email log ID")
    rows = await db.select("email_logs", params={"select": "*", "id": f"eq.{log_id}", "limit": 1})
    allowed = {"order_confirmation", "payment_confirmed", "order_processing", "order_shipped",
               "order_delivered", "order_cancelled", "refund_confirmed", "withdrawal_received"}
    if not rows or rows[0].get("status") not in {"failed", "queued"} or rows[0].get("email_type") not in allowed or not rows[0].get("order_id"):
        raise HTTPException(409, "Email is not retryable")
    if rows[0]["status"] == "queued":
        created = datetime.fromisoformat(rows[0]["created_at"].replace("Z", "+00:00"))
        if created > datetime.now(timezone.utc) - timedelta(minutes=5):
            raise HTTPException(409, "Email delivery is still in progress")
    amount = (rows[0].get("metadata") or {}).get("amount_cents")
    if rows[0]['email_type'] == 'withdrawal_received':
        from html import escape
        receipt = (rows[0].get('metadata') or {}).get('receipt_text')
        if not isinstance(receipt, str) or not receipt:
            raise HTTPException(409, 'Withdrawal receipt is unavailable')
        html, text = _layout('Demande de rétractation reçue', [escape(receipt).replace('\n','<br>')])
        result = await email_service.retry(log_id, rows[0]['recipient'], EmailContent('TYMotors — demande de rétractation reçue', html, text))
    else:
        result = await _send_order_email(rows[0]["email_type"], rows[0]["order_id"], amount_cents=amount, retry_log_id=log_id)
    await _audit(admin, "email.retry", log_id, {"order_id": rows[0]["order_id"], "email_type": rows[0]["email_type"]})
    return {"accepted": bool(result), "delivery": result["status"] if result else "failed"}


@api.get('/admin/withdrawal-requests')
async def withdrawal_requests(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), admin: dict[str, Any] = Depends(require_admin)):
    return await db.page('contact_messages', params={'select':'id,name,email,subject,message,status,created_at',
        'subject':'ilike.Rétractation TY-*', 'order':'created_at.desc,id.desc'}, page=page, limit=limit)


@api.patch('/admin/withdrawal-requests/{request_id}')
async def update_withdrawal_request(request_id: uuid.UUID, payload: WithdrawalStatusInput, admin: dict[str, Any] = Depends(require_admin)):
    rows = await db.update('contact_messages', {'status':payload.status}, params={'id':'eq.'+str(request_id),
        'subject':'ilike.Rétractation TY-*', 'status':'eq.'+payload.expected_status})
    if not rows: raise HTTPException(409, 'Request not found or updated by another administrator')
    await _audit(admin, 'withdrawal.status', str(request_id), {'from':payload.expected_status, 'to':payload.status})
    return {'updated':True}


@api.put("/admin/orders/{order_id}")
async def update_order(order_id: str, payload: AdminOrderUpdateInput, admin: dict[str, Any] = Depends(require_admin)):
    try: order_id = str(uuid.UUID(order_id))
    except ValueError: raise HTTPException(422, "Invalid order ID")
    before_rows = await db.select("orders", params={"select": "fulfillment_status", "id": f"eq.{order_id}", "limit": 1})
    if not before_rows:
        raise HTTPException(404, "Commande introuvable")
    result = await db.rpc("admin_update_order", {"p_actor": admin["id"], "p_id": order_id, "p_status": payload.fulfillment_status,
        "p_tracking": payload.tracking_number, "p_expected": payload.expected_updated_at})
    await db.update("orders", {"carrier": payload.carrier, "tracking_url": payload.tracking_url}, params={"id": f"eq.{order_id}"})
    if before_rows[0]["fulfillment_status"] != payload.fulfillment_status:
        email_kind = {
            "processing": "order_processing", "shipped": "order_shipped",
            "delivered": "order_delivered", "cancelled": "order_cancelled",
        }.get(payload.fulfillment_status)
        if email_kind:
            await _send_order_email(email_kind, order_id)
    return result


@api.post("/create-checkout-session")
async def create_checkout_session(request: Request, promotion_code: str | None = Query(None, max_length=40),
                                  x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    if settings.stripe_test_mode and not settings.public_test_checkout_enabled:
        raise HTTPException(status_code=503, detail="Checkout is not open")
    if stripe_client is None: raise HTTPException(status_code=503, detail="Checkout is not configured")
    if not settings.stripe_test_mode and not legal_ready():
        raise HTTPException(503, 'Legal identity must be completed before live checkout')
    _rate_limit(checkout_attempts, 'ip:'+_client_key(request), 8, 60)
    actor = user["id"] if user else _session_id(x_session_id); _rate_limit(checkout_attempts, 'actor:'+actor, 8, 60)
    cart = await _cart_for(user, x_session_id, create=False); cart_view = await _cart_response(cart)
    if not cart or not cart_view["items"]: raise HTTPException(status_code=400, detail="Cart is empty")
    line_items, order_items, subtotal_cents, requires_review = [], [], 0, False
    for item in cart_view["items"]:
        quantity = item["quantity"]
        if not purchasable(item, settings, quantity): raise HTTPException(status_code=409, detail=f"Unavailable product: {item['name']}")
        # Hydrated cart rows carry display-only compatibility metadata. Validate only
        # vehicle facts, then recompute; never trust a carried 'compatible' label.
        vehicle_facts = {key: value for key, value in (item.get('selected_vehicle') or {}).items() if key in VehicleSelection.model_fields}
        compatibility_result = check_compatibility(item, VehicleSelection.model_validate(vehicle_facts)) if vehicle_facts else {"status": "unknown", "reason": "No vehicle selected"}
        if compatibility_result["status"] == "incompatible":
            raise HTTPException(status_code=409, detail=f"Produit incompatible avec le véhicule sélectionné : {item['name']}")
        if not settings.stripe_test_mode and compatibility_result["status"] != "compatible":
            raise HTTPException(status_code=409, detail=f"Compatibilité non confirmée avant paiement : {item['name']}")
        if not settings.stripe_test_mode:
            offers = await db.select("product_supplier_data", params={
                "select": "supplier_name,supplier_reference,cost_price_cents,shipping_cost_cents,supplier_verified",
                "product_id": f"eq.{item['id']}", "limit": 1})
            offer = offers[0] if offers else {}
            if (not offer.get("supplier_verified") or not (offer.get("supplier_name") or "").strip()
                    or not (offer.get("supplier_reference") or "").strip()
                    or offer.get("cost_price_cents") is None or offer.get("shipping_cost_cents") is None):
                raise HTTPException(status_code=409, detail=f"Offre fournisseur ou livraison non confirmée : {item['name']}")
        requires_review = requires_review or compatibility_result["status"] != "compatible"
        # Integer cents come from the hydrated database product, never the browser.
        unit_amount = item["price_cents"]; subtotal_cents += unit_amount * quantity
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
        "requires_compatibility_review": requires_review, "is_test": settings.stripe_test_mode}
    if user:
        profiles = await db.select("profiles", params={"select": "email,full_name,stripe_customer_id", "id": f"eq.{user['id']}", "limit": 1})
        if profiles: order_payload.update(customer_email=profiles[0].get("email"), customer_name=profiles[0].get("full_name"))
    order = (await db.insert("orders", order_payload))[0]
    await db.insert("order_items", [{**item, "order_id": order["id"]} for item in order_items])
    promotion = None
    if promotion_code:
        promotion = await db.rpc("apply_order_promotion", {"p_order_id": order["id"], "p_code": promotion_code.upper()})
    if shipping: line_items.append({"quantity": 1, "price_data": {"currency": cart_view["currency"].lower(), "unit_amount": shipping, "product_data": {"name": "Livraison suivie"}}})
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(8))
    frontend_url = _checkout_frontend_url(request)
    params: dict[str, Any] = {"mode": "payment", "line_items": line_items,
        "success_url": f"{frontend_url}/order-success?session_id={{CHECKOUT_SESSION_ID}}", "cancel_url": f"{frontend_url}/cart?checkout=cancelled",
        "client_reference_id": order["id"], "integration_identifier": f"tymotors_checkout_{suffix}",
        "metadata": {"order_id": order["id"], "user_id": user["id"] if user else "guest"},
        "payment_intent_data": {"metadata": {"order_id": order["id"], "user_id": user["id"] if user else "guest"}},
        "shipping_address_collection": {"allowed_countries": list(settings.shipping_countries)},
        "billing_address_collection": "required", "phone_number_collection": {"enabled": True}}
    if order_payload.get("customer_email"): params["customer_email"] = order_payload["customer_email"]
    params["expires_at"] = int(time.time()) + 1800
    if os.getenv("STRIPE_AUTOMATIC_TAX", "false").lower() == "true": params["automatic_tax"] = {"enabled": True}
    try:
        if promotion:
            coupon = await stripe_client.v1.coupons.create_async(
                params={"amount_off": promotion["discount_cents"], "currency": "eur", "duration": "once",
                        "max_redemptions": 1, "name": promotion_code.upper()},
                options={"idempotency_key": f"coupon_{order['id']}"})
            params["discounts"] = [{"coupon": coupon.id}]
        session = await stripe_client.v1.checkout.sessions.create_async(params=params, options={"idempotency_key": f"checkout_{order['id']}"})
    except stripe.StripeError:
        await db.update("orders", {"status": "payment_failed", "payment_status": "failed"}, params={"id": f"eq.{order['id']}"})
        logger.error("Stripe Checkout creation failed"); raise HTTPException(status_code=502, detail="Unable to create secure checkout")
    await db.update("orders", {"stripe_session_id": session.id}, params={"id": f"eq.{order['id']}"})
    if order_payload.get("customer_email"):
        await _send_order_email("order_confirmation", order["id"])
    return {"url": session.url, "order_reference": order["order_number"]}


@api.get("/checkout-session/{stripe_session_id}")
async def checkout_session(stripe_session_id: str, x_session_id: str | None = Header(default=None), user: dict[str, Any] | None = Depends(optional_user)):
    rows = await db.select("orders", params={"select": "*", "stripe_session_id": f"eq.{stripe_session_id}", "limit": 1})
    if not rows: raise HTTPException(status_code=404, detail="Order not found")
    order = rows[0]; allowed = bool(user and order.get("user_id") == user["id"]) or bool(not user and x_session_id and order.get("guest_session_id") == x_session_id)
    if not allowed: raise HTTPException(status_code=404, detail="Order not found")
    # Read-only: signed webhooks alone authorize payment side effects.
    result = (await _orders_with_items([order]))[0]
    return {"paid": result["payment_status"] == "paid", "is_test": result.get("is_test", False), "status": result["status"], "payment_status": result["payment_status"],
        "order_reference": result["order_number"], "customer_email": result.get("customer_email"), "items": result["items"],
        "subtotal": result["subtotal_cents"] / 100, "shipping": result["shipping_amount_cents"] / 100,
        "tax": result["tax_amount_cents"] / 100, "total": result["total_cents"] / 100, "currency": result["currency"],
        "shipping_address": result.get("shipping_address") or {}}


async def _complete_checkout_payment(obj: Any) -> str | None:
    if obj.get("payment_status") not in {"paid", "no_payment_required"}:
        return None
    order_id = (obj.get("metadata") or {}).get("order_id")
    if not order_id:
        return None
    order_rows = await db.select("orders", params={
        "select": "id,total_cents,currency,stripe_session_id,customer_email,is_test", "id": f"eq.{order_id}", "limit": 1,
    })
    if not order_rows:
        raise RuntimeError("Stripe event references an unknown order")
    expected = order_rows[0]
    if expected.get('is_test') and not settings.stripe_test_mode:
        raise RuntimeError('A test order cannot be completed by a live payment')
    if obj.get("payment_status") == "no_payment_required" and expected["total_cents"] != 0:
        raise RuntimeError("A non-zero order cannot be completed without payment")
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
    if customer.get("phone"):
        await db.update("orders", {"customer_phone": str(customer["phone"])[:40]}, params={"id": f"eq.{order_id}"})
    orders = await db.select("orders", params={"select": "user_id,customer_email", "id": f"eq.{order_id}", "limit": 1})
    if orders and orders[0].get("user_id") and obj.get("customer"):
        await db.update("profiles", {"stripe_customer_id": obj.get("customer")}, params={"id": f"eq.{orders[0]['user_id']}"})
    if orders and not order_rows[0].get("customer_email"):
        await _send_order_email("order_confirmation", order_id)
    await _send_order_email("payment_confirmed", order_id)
    return order_id


@api.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")):
    if not settings.stripe_webhook_secret or not stripe_signature: raise HTTPException(status_code=400, detail="Missing webhook signature")
    payload = await request.body()
    # SDK resources are not dictionaries. Convert recursively after signature
    # verification so nested Checkout data supports dictionary operations too.
    try: event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret).to_dict()
    except (ValueError, stripe.SignatureVerificationError): raise HTTPException(status_code=400, detail="Invalid webhook signature")
    if event.get("livemode") is not (not settings.stripe_test_mode):
        raise HTTPException(status_code=400, detail="Stripe event mode does not match checkout configuration")
    event_id = event["id"]; existing = await db.select("stripe_events", params={"select": "status", "event_id": f"eq.{event_id}", "limit": 1})
    if existing and existing[0]["status"] == "completed": return {"received": True, "duplicate": True}
    if not existing:
        try: await db.insert("stripe_events", {"event_id": event_id, "event_type": event["type"], "status": "processing"})
        except SupabaseError as error:
            if error.status_code != 409: raise
    try:
        obj = event["data"]["object"]; event_type = event["type"]
        if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"} and obj.get("payment_status") in {"paid", "no_payment_required"}:
            await _complete_checkout_payment(obj)
        elif event_type == "payment_intent.payment_failed":
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id: await db.update("orders", {"status": "payment_failed", "payment_status": "failed"}, params={"id": f"eq.{order_id}", "payment_status": "in.(unpaid,failed)", "stock_applied_at": "is.null"})
        elif event_type in {"charge.refunded", "refund.created", "refund.updated", "refund.failed"} and obj.get("payment_intent"):
            await _sync_refunds(obj["payment_intent"])
        elif event_type in {"checkout.session.expired", "checkout.session.async_payment_failed"}:
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id:
                await db.update("orders", {"status": "payment_failed", "payment_status": "failed"},
                    params={"id": f"eq.{order_id}", "stock_applied_at": "is.null", "payment_status": "in.(unpaid,failed)"})
        await db.update("stripe_events", {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}, params={"event_id": f"eq.{event_id}"})
    except Exception as error:
        await db.update("stripe_events", {"status": "failed", "error_message": type(error).__name__}, params={"event_id": f"eq.{event_id}"})
        logger.error("Stripe event processing failed: %s (%s)", event_id, type(error).__name__); raise HTTPException(status_code=500, detail="Webhook processing failed")
    return {"received": True}


async def _sync_refunds(payment_intent: str) -> None:
    if stripe_client is None:
        raise RuntimeError("Stripe client required to confirm refunds")
    before = await db.select("orders", params={"select": "id,refunded_amount_cents", "stripe_payment_intent_id": f"eq.{payment_intent}", "limit": 1})
    refunds = await stripe_client.v1.refunds.list_async(params={"payment_intent": payment_intent, "limit": 100})
    succeeded = 0
    async for refund in refunds.auto_paging_iter():
        refund_data = refund.to_dict()
        if refund_data.get("status") == "succeeded":
            succeeded += refund_data["amount"]
    await db.rpc("record_order_refund", {"p_payment_intent": payment_intent, "p_refunded": succeeded})
    if before and succeeded > int(before[0].get("refunded_amount_cents") or 0):
        await _send_order_email("refund_confirmed", before[0]["id"], amount_cents=succeeded)


api.include_router(create_admin_router(
    db,
    catalog,
    require_admin,
    _audit,
    stripe_test_mode=settings.stripe_test_mode,
))
app.include_router(api)


@app.exception_handler(SupabaseError)
async def supabase_error_handler(_: Request, error: SupabaseError):
    from fastapi.responses import JSONResponse
    logger.error("Supabase request failed with status %s", error.status_code)
    messages = {
        "changed. Reload": "Les données ont changé. Rechargez la page avant d’enregistrer.",
        "Use inventory": "Modifiez le stock depuis la rubrique Stocks.",
        "Insufficient stock": "Stock insuffisant pour cette opération.",
        "insufficient stock": "Stock insuffisant pour cette opération.",
        "Invalid transition": "Cette transition de commande n’est pas autorisée.",
        "Invalid return transition": "Cette transition de retour n’est pas autorisée.",
        "Payment required": "Un paiement confirmé est nécessaire.",
        "Tracking number required": "Un numéro de suivi est nécessaire.",
        "Ship the order first": "La commande doit d’abord être expédiée.",
        "This order is closed": "Cette commande est clôturée.",
        "Use a return": "Ouvrez un retour pour une commande déjà expédiée.",
        "Receive and inspect": "Recevez et inspectez l’article avant une unique remise en stock.",
        "Confirm the full refund": "Le remboursement intégral doit être confirmé par Stripe.",
        "Return quantity exceeds": "La quantité retournée dépasse la quantité achetée.",
        "Promotion unavailable": "Ce code promotionnel n’est pas applicable à ce panier.",
        "Promotion usage limit": "Le nombre maximum d’utilisations du code est atteint.",
        "No eligible products": "Aucun produit du panier n’est éligible à ce code.",
        "duplicate key": "Un produit ou code avec cet identifiant existe déjà.",
    }
    for fragment, message in messages.items():
        if fragment in error.detail:
            return JSONResponse(status_code=409, content={"detail": message})
    return JSONResponse(status_code=error.status_code if error.status_code in {400, 404, 409, 422} else 502,
                        content={"detail": "Database request failed"})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    from fastapi.responses import JSONResponse
    try:
        response = await call_next(request)
    except Exception as error:
        logger.error('Unhandled request failure (%s)', type(error).__name__)
        response = JSONResponse(status_code=503 if isinstance(error, httpx.RequestError) else 500,
                                content={'detail': 'Service unavailable'})
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})
    if request.url.scheme == "https": response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    private = request.url.path.startswith(('/api/admin', '/api/auth', '/api/me', '/api/cart', '/api/wishlist', '/api/order-tracking', '/api/withdrawals')) or 'checkout' in request.url.path or request.headers.get('authorization')
    response.headers["Cache-Control"] = "no-store" if private else "no-cache"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, error: RequestValidationError):
    from fastapi.responses import JSONResponse
    # Pydantic normally echoes input, which can expose passwords/contact bodies.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(e['loc']), 'type': e['type'], 'msg': 'Invalid input'} for e in error.errors()
    ]})


app.add_middleware(CORSMiddleware, allow_credentials=False, allow_origins=settings.cors_origins,
                   allow_origin_regex=settings.cors_origin_regex, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Session-Id", "Stripe-Signature"])

# Stable aliases used by migration tooling and tests.
ProductCreateInput = ProductInput
