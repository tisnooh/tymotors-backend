from fastapi import FastAPI, APIRouter, HTTPException, Header, Query, UploadFile, File, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import os
import logging
import time
import re
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict, SecretStr, model_validator
from typing import Any, List, Optional, Literal
import uuid
import stripe
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
import cloudinary
import cloudinary.uploader

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

# Support both CLOUDINARY_URL (single var) and separate vars
cloudinary_url = os.environ.get("CLOUDINARY_URL")
if cloudinary_url:
    cloudinary.config(cloudinary_url=cloudinary_url)
else:
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", ""),
        api_key=os.environ.get("CLOUDINARY_API_KEY", ""),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET", ""),
        secure=True
    )

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="TYMotors API", version="1.0.0")
api_router = APIRouter(prefix="/api")
bearer_scheme = HTTPBearer(auto_error=False)
admin_failures: dict[str, list[float]] = {}
checkout_attempts: dict[str, list[float]] = {}
contact_attempts: dict[str, list[float]] = {}

# =====================================================
# MODELS
# =====================================================

class Brand(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str
    name: str
    tagline: str
    description: str
    image: str
    logo_text: str  # short wordmark fallback
    order: int = 0


class Category(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str  # performance, interior, technology
    name: str
    tagline: str
    description: str
    image: str
    subcategories: List[str] = Field(default_factory=list)  # e.g. ['Grilles','Spoilers']
    order: int = 0


class ProductCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    model: Optional[str] = Field(default=None, max_length=100)
    chassis: Optional[str] = Field(default=None, max_length=50)
    generation: Optional[str] = Field(default=None, max_length=100)
    year_from: Optional[int] = Field(default=None, ge=1950, le=2100)
    year_to: Optional[int] = Field(default=None, ge=1950, le=2100)
    body_types: List[str] = Field(default_factory=list)
    facelift: Literal["pre-lci", "lci", "any", "unknown"] = "unknown"
    required_trim: List[str] = Field(default_factory=list)
    excluded_trims: List[str] = Field(default_factory=list)
    camera_compatible: Optional[bool] = None
    parking_sensor_compatible: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=1000)
    is_verified: bool = False

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be less than or equal to year_to")
        return self


class ProductAdminData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_reference: Optional[str] = Field(default=None, max_length=200)
    supplier_name: Optional[str] = Field(default=None, max_length=200)
    supplier_url: Optional[str] = Field(default=None, max_length=1000)
    cost_price: Optional[float] = Field(default=None, ge=0)
    shipping_cost: Optional[float] = Field(default=None, ge=0)
    landed_cost: Optional[float] = Field(default=None, ge=0)
    margin_amount: Optional[float] = None
    margin_percent: Optional[float] = None


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    slug: str
    name: str
    subtitle: str
    description: str
    price: float
    compare_at_price: Optional[float] = None
    currency: str = "EUR"
    images: List[str] = Field(default_factory=list)
    category_slug: str  # performance | interior | technology
    subcategory: str  # e.g. 'Grilles'
    compatible_brands: List[str] = Field(default_factory=list)  # legacy fallback
    compatibilities: List[ProductCompatibility] = Field(default_factory=list)
    badges: List[str] = Field(default_factory=list)
    sku: str
    stock: int = 0
    rating: Optional[float] = None
    review_count: int = 0
    featured: bool = False
    specs: dict = Field(default_factory=dict)
    package_contents: List[str] = Field(default_factory=list)
    installation_difficulty: Optional[Literal["easy", "medium", "advanced", "professional"]] = None
    installation_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    tools_required: List[str] = Field(default_factory=list)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    delivery_estimate: Optional[str] = Field(default=None, max_length=200)
    status: Literal["draft", "active", "archived"] = "draft"
    is_verified: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VehicleModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brand_slug: str
    name: str  # e.g. 'M3', 'C-Class'
    generations: List[str] = Field(default_factory=list)  # legacy display values


class ProductCreateInput(BaseModel):
    slug: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=160)
    subtitle: str = Field(min_length=2, max_length=240)
    description: str = Field(min_length=20, max_length=5000)
    price: float = Field(gt=0, le=100000)
    compare_at_price: Optional[float] = Field(default=None, gt=0, le=100000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    images: List[str] = Field(default_factory=list)
    category_slug: str
    subcategory: str
    compatible_brands: List[str] = Field(default_factory=list)
    compatibilities: List[ProductCompatibility] = Field(default_factory=list)
    badges: List[str] = Field(default_factory=list)
    sku: str = Field(min_length=2, max_length=80)
    stock: int = Field(default=0, ge=0, le=100000)
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    featured: bool = False
    specs: dict = Field(default_factory=dict)
    package_contents: List[str] = Field(default_factory=list)
    installation_difficulty: Optional[Literal["easy", "medium", "advanced", "professional"]] = None
    installation_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    tools_required: List[str] = Field(default_factory=list)
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    delivery_estimate: Optional[str] = Field(default=None, max_length=200)
    status: Literal["draft", "active", "archived"] = "draft"
    is_verified: bool = False
    admin: ProductAdminData = Field(default_factory=ProductAdminData)

    @model_validator(mode="after")
    def validate_active_product(self):
        if self.status == "active":
            missing = []
            if not self.is_verified:
                missing.append("is_verified")
            if not self.images:
                missing.append("images")
            if not self.compatibilities:
                missing.append("compatibilities")
            elif not all(item.is_verified for item in self.compatibilities):
                missing.append("verified compatibilities")
            if not self.package_contents:
                missing.append("package_contents")
            if not self.installation_difficulty:
                missing.append("installation_difficulty")
            if not self.delivery_estimate:
                missing.append("delivery_estimate")
            if not self.admin.supplier_name:
                missing.append("supplier_name")
            if self.admin.cost_price is None:
                missing.append("cost_price")
            if missing:
                raise ValueError(f"Active products require: {', '.join(missing)}")
        return self


class ProductUpdateInput(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    subtitle: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0, le=100000)
    compare_at_price: Optional[float] = Field(default=None, gt=0, le=100000)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    images: Optional[List[str]] = None
    category_slug: Optional[str] = None
    subcategory: Optional[str] = None
    compatible_brands: Optional[List[str]] = None
    compatibilities: Optional[List[ProductCompatibility]] = None
    badges: Optional[List[str]] = None
    sku: Optional[str] = None
    stock: Optional[int] = Field(default=None, ge=0, le=100000)
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    review_count: Optional[int] = Field(default=None, ge=0)
    featured: Optional[bool] = None
    specs: Optional[dict] = None
    package_contents: Optional[List[str]] = None
    installation_difficulty: Optional[Literal["easy", "medium", "advanced", "professional"]] = None
    installation_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    tools_required: Optional[List[str]] = None
    warranty_months: Optional[int] = Field(default=None, ge=0, le=120)
    delivery_estimate: Optional[str] = Field(default=None, max_length=200)
    status: Optional[Literal["draft", "active", "archived"]] = None
    is_verified: Optional[bool] = None
    admin: Optional[ProductAdminData] = None


class VehicleSelection(BaseModel):
    brand_slug: str
    model: Optional[str] = None
    chassis: Optional[str] = None
    generation: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1950, le=2100)
    body_type: Optional[str] = None
    trim: Optional[str] = None
    has_camera: Optional[bool] = None
    has_parking_sensors: Optional[bool] = None


class AdminLoginInput(BaseModel):
    password: SecretStr


class AdminOrderUpdateInput(BaseModel):
    fulfillment_status: Literal["unfulfilled", "processing", "shipped", "delivered", "cancelled", "requires_review"]
    tracking_number: Optional[str] = Field(default=None, max_length=200)


class CartItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: str
    quantity: int = 1
    selected_vehicle: Optional[VehicleSelection] = None


class CartItemInput(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=20)
    selected_vehicle: Optional[VehicleSelection] = None


class CartUpdateInput(BaseModel):
    product_id: str
    quantity: int = Field(ge=0, le=20)


class WishlistInput(BaseModel):
    product_id: str


class NewsletterInput(BaseModel):
    email: EmailStr
    locale: Optional[str] = "en"


class ContactInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)


class NewsletterRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    locale: str = "en"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =====================================================
# HELPERS
# =====================================================

async def require_session(x_session_id: Optional[str] = Header(default=None)) -> str:
    if not x_session_id or len(x_session_id) > 128:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")
    return x_session_id


def admin_token_ttl_minutes() -> int:
    try:
        return max(5, min(int(os.environ.get("ADMIN_TOKEN_TTL_MINUTES", "15")), 60))
    except ValueError:
        return 15


def create_admin_token() -> tuple[str, int]:
    jwt_secret = os.environ.get("ADMIN_JWT_SECRET", "")
    if len(jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    ttl_minutes = admin_token_ttl_minutes()
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "tymotors-admin",
            "role": "admin",
            "iss": "tymotors-api",
            "aud": "tymotors-admin",
            "iat": now,
            "exp": now + timedelta(minutes=ttl_minutes),
            "jti": str(uuid.uuid4()),
        },
        jwt_secret,
        algorithm="HS256",
    )
    return token, ttl_minutes * 60


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict[str, Any]:
    jwt_secret = os.environ.get("ADMIN_JWT_SECRET", "")
    if len(jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(
            credentials.credentials,
            jwt_secret,
            algorithms=["HS256"],
            audience="tymotors-admin",
            issuer="tymotors-api",
            options={"require": ["sub", "role", "exp", "iat", "jti"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    if claims.get("role") != "admin" or claims.get("sub") != "tymotors-admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return claims


async def audit_admin(action: str, admin: dict[str, Any], resource: str, metadata: Optional[dict] = None) -> None:
    await db.admin_audit.insert_one({
        "id": str(uuid.uuid4()),
        "admin_sub": admin.get("sub"),
        "token_id": admin.get("jti"),
        "action": action,
        "resource": resource,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def public_product_projection() -> dict[str, int]:
    return {"_id": 0, "admin": 0}


def make_order_number() -> str:
    return f"TY-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def normalize(value: Optional[str]) -> str:
    return (value or "").strip().casefold()


def check_compatibility(product: dict, vehicle: VehicleSelection) -> dict[str, Any]:
    compatibilities = product.get("compatibilities") or []
    if not compatibilities:
        legacy_match = vehicle.brand_slug in (product.get("compatible_brands") or [])
        return {
            "status": "unknown" if legacy_match else "incompatible",
            "reason": "Detailed compatibility data is missing" if legacy_match else "Brand is not listed for this product",
        }

    brand_matches = [c for c in compatibilities if normalize(c.get("brand_slug")) == normalize(vehicle.brand_slug)]
    if not brand_matches:
        return {"status": "incompatible", "reason": "Brand is not compatible"}

    missing_selection = not vehicle.model or not vehicle.chassis or vehicle.year is None
    for compatibility in brand_matches:
        if compatibility.get("model") and vehicle.model and normalize(compatibility["model"]) != normalize(vehicle.model):
            continue
        if compatibility.get("chassis") and vehicle.chassis:
            selected_chassis = normalize(vehicle.chassis)
            if selected_chassis not in {normalize(compatibility.get("chassis")), normalize(compatibility.get("generation"))}:
                continue
        if vehicle.year is not None:
            if compatibility.get("year_from") and vehicle.year < compatibility["year_from"]:
                continue
            if compatibility.get("year_to") and vehicle.year > compatibility["year_to"]:
                continue
        if vehicle.body_type and compatibility.get("body_types") and normalize(vehicle.body_type) not in {normalize(v) for v in compatibility["body_types"]}:
            continue
        if vehicle.trim and normalize(vehicle.trim) in {normalize(v) for v in compatibility.get("excluded_trims", [])}:
            continue
        if compatibility.get("required_trim") and (not vehicle.trim or normalize(vehicle.trim) not in {normalize(v) for v in compatibility["required_trim"]}):
            continue
        if vehicle.has_camera is not None and compatibility.get("camera_compatible") is False and vehicle.has_camera:
            continue
        if vehicle.has_parking_sensors is not None and compatibility.get("parking_sensor_compatible") is False and vehicle.has_parking_sensors:
            continue
        if missing_selection or not product.get("is_verified") or not compatibility.get("is_verified"):
            return {"status": "confirm", "reason": "Compatibility data must be completed and verified by TYMotors", "compatibility": compatibility}
        return {"status": "compatible", "reason": compatibility.get("notes") or "Vehicle matches the verified compatibility data", "compatibility": compatibility}

    return {"status": "incompatible", "reason": "The selected vehicle does not match this product"}


def clean_doc(doc: dict) -> dict:
    if not doc:
        return doc
    doc.pop("_id", None)
    if isinstance(doc.get("created_at"), str):
        try:
            doc["created_at"] = datetime.fromisoformat(doc["created_at"])
        except Exception:
            pass
    return doc


# =====================================================
# ROUTES
# =====================================================

@api_router.get("/")
async def root():
    return {"message": "TYMotors API", "version": "1.0.0"}


@api_router.get("/brands")
async def list_brands():
    docs = await db.brands.find({}, {"_id": 0}).sort("order", 1).to_list(50)
    return docs


@api_router.get("/brands/{slug}")
async def get_brand(slug: str):
    doc = await db.brands.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Brand not found")
    return doc


@api_router.get("/categories")
async def list_categories():
    docs = await db.categories.find({}, {"_id": 0}).sort("order", 1).to_list(50)
    return docs


@api_router.get("/categories/{slug}")
async def get_category(slug: str):
    doc = await db.categories.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Category not found")
    return doc


@api_router.get("/products")
async def list_products(
    category: Optional[str] = None,
    brand: Optional[str] = None,
    model: Optional[str] = None,
    chassis: Optional[str] = None,
    year: Optional[int] = Query(default=None, ge=1950, le=2100),
    body_type: Optional[str] = None,
    subcategory: Optional[str] = None,
    featured: Optional[bool] = None,
    q: Optional[str] = Query(default=None, max_length=100),
    sort: str = Query(default="relevance", pattern="^(relevance|price_asc|price_desc|newest)$"),
    limit: int = Query(60, ge=1, le=200),
    skip: int = Query(0, ge=0)
):
    conditions: list[dict] = [{"$or": [{"status": "active"}, {"status": {"$exists": False}}]}]
    if category:
        conditions.append({"category_slug": category})
    if subcategory:
        conditions.append({"subcategory": subcategory})
    if brand or model or chassis or year is not None or body_type:
        compatibility_match: dict[str, Any] = {}
        if brand:
            compatibility_match["brand_slug"] = brand
        if model:
            compatibility_match["model"] = {"$regex": f"^{re.escape(model)}$", "$options": "i"}
        if chassis:
            exact_chassis = {"$regex": f"^{re.escape(chassis)}$", "$options": "i"}
            compatibility_match["$or"] = [{"chassis": exact_chassis}, {"generation": exact_chassis}]
        if year is not None:
            compatibility_match["year_from"] = {"$lte": year}
            compatibility_match["year_to"] = {"$gte": year}
        if body_type:
            compatibility_match["body_types"] = body_type
        detailed_filter = {"compatibilities": {"$elemMatch": compatibility_match}}
        if brand and not any([model, chassis, year is not None, body_type]):
            conditions.append({"$or": [detailed_filter, {"compatible_brands": brand}]})
        else:
            conditions.append(detailed_filter)
    if featured is not None:
        conditions.append({"featured": featured})
    if q:
        safe_query = re.escape(q.strip())
        conditions.append({"$or": [
            {"name": {"$regex": safe_query, "$options": "i"}},
            {"subtitle": {"$regex": safe_query, "$options": "i"}},
            {"description": {"$regex": safe_query, "$options": "i"}},
            {"subcategory": {"$regex": safe_query, "$options": "i"}},
            {"sku": {"$regex": safe_query, "$options": "i"}},
        ]})

    query: dict = {"$and": conditions}
    total = await db.products.count_documents(query)
    sort_map = {
        "relevance": [("featured", -1), ("created_at", -1)],
        "price_asc": [("price", 1)],
        "price_desc": [("price", -1)],
        "newest": [("created_at", -1)],
    }
    docs = await db.products.find(query, public_product_projection()).sort(sort_map[sort]).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "items": docs}


@api_router.get("/products/{slug}")
async def get_product(slug: str):
    doc = await db.products.find_one(
        {"slug": slug, "$or": [{"status": "active"}, {"status": {"$exists": False}}]},
        public_product_projection(),
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc


@api_router.post("/products/{slug}/compatibility")
async def product_compatibility(slug: str, vehicle: VehicleSelection):
    product = await db.products.find_one(
        {"slug": slug, "$or": [{"status": "active"}, {"status": {"$exists": False}}]},
        public_product_projection(),
    )
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return check_compatibility(product, vehicle)


@api_router.get("/compatibility")
async def compatibility(brand: Optional[str] = None):
    query = {}
    if brand:
        query["brand_slug"] = brand
    docs = await db.vehicle_models.find(query, {"_id": 0}).to_list(500)
    return docs


# ---------- CART ----------

@api_router.get("/cart")
async def get_cart(x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    doc = await db.carts.find_one({"session_id": sid}, {"_id": 0}) or {"session_id": sid, "items": []}
    # enrich with product info
    items = []
    subtotal = 0.0
    for it in doc.get("items", []):
        p = await db.products.find_one({"id": it["product_id"]}, {"_id": 0})
        if p:
            line_total = float(p["price"]) * int(it["quantity"])
            subtotal += line_total
            items.append({
                "product_id": p["id"],
                "slug": p["slug"],
                "name": p["name"],
                "subtitle": p.get("subtitle", ""),
                "image": p["images"][0] if p.get("images") else "",
                "price": p["price"],
                "quantity": it["quantity"],
                "line_total": line_total,
                "subcategory": p.get("subcategory", ""),
                "stock": int(p.get("stock", 0)),
                "selected_vehicle": it.get("selected_vehicle"),
            })
    free_shipping_threshold = int(os.environ.get("FREE_SHIPPING_THRESHOLD_CENTS", "35000")) / 100
    shipping = 0 if subtotal >= free_shipping_threshold else (int(os.environ.get("SHIPPING_RATE_CENTS", "1500")) / 100 if items else 0)
    return {"session_id": sid, "items": items, "subtotal": round(subtotal, 2), "shipping": shipping, "total": round(subtotal + shipping, 2), "currency": "EUR"}


@api_router.post("/cart")
async def add_to_cart(payload: CartItemInput, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be >= 1")
    p = await db.products.find_one(
        {"id": payload.product_id, "$or": [{"status": "active"}, {"status": {"$exists": False}}]},
        {"_id": 0},
    )
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    if int(p.get("stock", 0)) < payload.quantity:
        raise HTTPException(status_code=400, detail="Requested quantity is not available")
    selected_vehicle = None
    if payload.selected_vehicle:
        result = check_compatibility(p, payload.selected_vehicle)
        if result["status"] == "incompatible":
            raise HTTPException(status_code=400, detail="This product is not compatible with the selected vehicle")
        selected_vehicle = {**payload.selected_vehicle.model_dump(), "compatibility_status": result["status"]}
    cart = await db.carts.find_one({"session_id": sid}, {"_id": 0})
    if not cart:
        cart = {"session_id": sid, "items": [{"product_id": payload.product_id, "quantity": payload.quantity, "selected_vehicle": selected_vehicle}]}
        await db.carts.insert_one(cart)
    else:
        items = cart.get("items", [])
        found = False
        for it in items:
            if it["product_id"] == payload.product_id:
                new_quantity = int(it["quantity"]) + payload.quantity
                if new_quantity > min(int(p.get("stock", 0)), 20):
                    raise HTTPException(status_code=400, detail="Requested quantity is not available")
                it["quantity"] = new_quantity
                if selected_vehicle:
                    it["selected_vehicle"] = selected_vehicle
                found = True
                break
        if not found:
            items.append({"product_id": payload.product_id, "quantity": payload.quantity, "selected_vehicle": selected_vehicle})
        await db.carts.update_one({"session_id": sid}, {"$set": {"items": items}})
    return await get_cart(sid)


@api_router.put("/cart")
async def update_cart_item(payload: CartUpdateInput, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    cart = await db.carts.find_one({"session_id": sid}, {"_id": 0})
    if not cart:
        raise HTTPException(status_code=404, detail="Cart not found")
    items = cart.get("items", [])
    if payload.quantity <= 0:
        items = [it for it in items if it["product_id"] != payload.product_id]
    else:
        product = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        if payload.quantity > int(product.get("stock", 0)):
            raise HTTPException(status_code=400, detail="Requested quantity is not available")
        for it in items:
            if it["product_id"] == payload.product_id:
                it["quantity"] = payload.quantity
                break
    await db.carts.update_one({"session_id": sid}, {"$set": {"items": items}})
    return await get_cart(sid)


@api_router.delete("/cart/{product_id}")
async def remove_from_cart(product_id: str, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    cart = await db.carts.find_one({"session_id": sid}, {"_id": 0})
    if not cart:
        return {"session_id": sid, "items": [], "subtotal": 0.0, "currency": "EUR"}
    items = [it for it in cart.get("items", []) if it["product_id"] != product_id]
    await db.carts.update_one({"session_id": sid}, {"$set": {"items": items}})
    return await get_cart(sid)


@api_router.delete("/cart")
async def clear_cart(x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    await db.carts.update_one({"session_id": sid}, {"$set": {"items": []}}, upsert=True)
    return {"session_id": sid, "items": [], "subtotal": 0.0, "currency": "EUR"}


# ---------- WISHLIST ----------

@api_router.get("/wishlist")
async def get_wishlist(x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    doc = await db.wishlists.find_one({"session_id": sid}, {"_id": 0}) or {"session_id": sid, "product_ids": []}
    ids = doc.get("product_ids", [])
    products = []
    if ids:
        products = await db.products.find({"id": {"$in": ids}}, {"_id": 0}).to_list(200)
    return {"session_id": sid, "items": products}


@api_router.post("/wishlist")
async def add_wishlist(payload: WishlistInput, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    p = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    doc = await db.wishlists.find_one({"session_id": sid}, {"_id": 0})
    if not doc:
        await db.wishlists.insert_one({"session_id": sid, "product_ids": [payload.product_id]})
    else:
        ids = set(doc.get("product_ids", []))
        ids.add(payload.product_id)
        await db.wishlists.update_one({"session_id": sid}, {"$set": {"product_ids": list(ids)}})
    return await get_wishlist(sid)


@api_router.delete("/wishlist/{product_id}")
async def remove_wishlist(product_id: str, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    doc = await db.wishlists.find_one({"session_id": sid}, {"_id": 0})
    if not doc:
        return {"session_id": sid, "items": []}
    ids = [i for i in doc.get("product_ids", []) if i != product_id]
    await db.wishlists.update_one({"session_id": sid}, {"$set": {"product_ids": ids}})
    return await get_wishlist(sid)


# ---------- NEWSLETTER ----------

@api_router.post("/newsletter")
async def newsletter_signup(payload: NewsletterInput):
    existing = await db.newsletter.find_one({"email": payload.email.lower()}, {"_id": 0})
    if existing:
        return {"ok": True, "message": "already_subscribed"}
    rec = NewsletterRecord(email=payload.email.lower(), locale=payload.locale or "en")
    doc = rec.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.newsletter.insert_one(doc)
    return {"ok": True, "message": "subscribed"}


@api_router.post("/contact", status_code=201)
async def contact_message(payload: ContactInput, request: Request):
    # Honeypot: bots commonly fill hidden website fields.
    if payload.website:
        return {"ok": True}
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [attempt for attempt in contact_attempts.get(client_ip, []) if now - attempt < 3600]
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="Too many contact requests")
    recent.append(now)
    contact_attempts[client_ip] = recent
    await db.contact_messages.insert_one({
        "id": str(uuid.uuid4()),
        "name": payload.name.strip(),
        "email": payload.email.lower(),
        "subject": payload.subject.strip(),
        "message": payload.message.strip(),
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


# ---------- ADMIN - UPLOAD IMAGE ----------

@api_router.post("/admin/login")
async def admin_login(payload: AdminLoginInput, request: Request):
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
    jwt_secret = os.environ.get("ADMIN_JWT_SECRET", "")
    if not password_hash or len(jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Admin access is not configured")
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [attempt for attempt in admin_failures.get(client_ip, []) if now - attempt < 900]
    admin_failures[client_ip] = recent
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="Too many authentication attempts")
    try:
        valid = bcrypt.checkpw(payload.password.get_secret_value().encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        valid = False
    if not valid:
        recent.append(now)
        logger.warning("Rejected admin login from %s", client_ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    admin_failures.pop(client_ip, None)
    token, expires_in = create_admin_token()
    logger.info("Admin login succeeded from %s", client_ip)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in}


@api_router.get("/admin/verify")
async def verify_admin(admin: dict[str, Any] = Depends(require_admin)):
    return {"ok": True, "expires_at": admin.get("exp")}


@api_router.get("/admin/products")
async def list_admin_products(
    q: Optional[str] = Query(default=None, max_length=100),
    status: Optional[Literal["draft", "active", "archived"]] = None,
    limit: int = Query(default=100, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    _: dict[str, Any] = Depends(require_admin),
):
    query: dict[str, Any] = {}
    if status:
        query["status"] = status
    if q:
        safe_query = re.escape(q.strip())
        query["$or"] = [
            {"name": {"$regex": safe_query, "$options": "i"}},
            {"sku": {"$regex": safe_query, "$options": "i"}},
            {"compatibilities.model": {"$regex": safe_query, "$options": "i"}},
            {"compatibilities.chassis": {"$regex": safe_query, "$options": "i"}},
        ]
    total = await db.products.count_documents(query)
    items = await db.products.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "items": items}


@api_router.post("/admin/upload-image")
async def upload_image(file: UploadFile = File(...), admin: dict[str, Any] = Depends(require_admin)):
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/avif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Allowed formats: JPEG, PNG, WebP or AVIF")
    max_size = 8 * 1024 * 1024
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise HTTPException(status_code=413, detail="Image is too large (8 MB maximum)")
    signatures = (
        contents.startswith(b"\xff\xd8\xff"),
        contents.startswith(b"\x89PNG\r\n\x1a\n"),
        contents.startswith(b"RIFF") and contents[8:12] == b"WEBP",
        len(contents) > 12 and contents[4:12] in {b"ftypavif", b"ftypavis"},
    )
    if not any(signatures):
        raise HTTPException(status_code=400, detail="Image content does not match an allowed format")
    result = cloudinary.uploader.upload(
        contents,
        folder="tymotors/products",
        resource_type="image",
        type="upload",
        overwrite=False,
    )
    await audit_admin("upload_image", admin, result["public_id"], {"content_type": file.content_type, "size": len(contents)})
    return {"url": result["secure_url"], "public_id": result["public_id"]}


# ---------- ADMIN - PRODUCTS CRUD ----------

@api_router.post("/admin/products")
async def create_product(payload: ProductCreateInput, admin: dict[str, Any] = Depends(require_admin)):
    existing = await db.products.find_one({"$or": [{"slug": payload.slug}, {"sku": payload.sku}]}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=409, detail="Slug or SKU already exists")
    product = Product(
        slug=payload.slug,
        name=payload.name,
        subtitle=payload.subtitle,
        description=payload.description,
        price=payload.price,
        compare_at_price=payload.compare_at_price,
        currency=payload.currency,
        images=payload.images,
        category_slug=payload.category_slug,
        subcategory=payload.subcategory,
        compatible_brands=payload.compatible_brands,
        compatibilities=payload.compatibilities,
        badges=payload.badges,
        sku=payload.sku,
        stock=payload.stock,
        rating=payload.rating,
        review_count=payload.review_count,
        featured=payload.featured,
        specs=payload.specs,
        package_contents=payload.package_contents,
        installation_difficulty=payload.installation_difficulty,
        installation_minutes=payload.installation_minutes,
        tools_required=payload.tools_required,
        warranty_months=payload.warranty_months,
        delivery_estimate=payload.delivery_estimate,
        status=payload.status,
        is_verified=payload.is_verified,
    )
    doc = product.model_dump()
    doc["admin"] = payload.admin.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    await audit_admin("create_product", admin, payload.slug, {"status": payload.status})
    return doc


@api_router.put("/admin/products/{slug}")
async def update_product(slug: str, payload: ProductUpdateInput, admin: dict[str, Any] = Depends(require_admin)):
    existing = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    candidate = {**existing, **updates}
    try:
        ProductCreateInput.model_validate(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if "sku" in updates:
        duplicate = await db.products.find_one({"sku": updates["sku"], "slug": {"$ne": slug}}, {"_id": 1})
        if duplicate:
            raise HTTPException(status_code=409, detail="SKU already exists")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.products.update_one({"slug": slug}, {"$set": updates})
    doc = await db.products.find_one({"slug": slug}, {"_id": 0})
    await audit_admin("update_product", admin, slug, {"fields": sorted(updates.keys())})
    return doc


@api_router.delete("/admin/products/{slug}")
async def delete_product(slug: str, admin: dict[str, Any] = Depends(require_admin)):
    existing = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.products.update_one(
        {"slug": slug},
        {"$set": {"status": "archived", "featured": False, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await audit_admin("archive_product", admin, slug)
    return {"ok": True, "archived": slug}


@api_router.post("/create-checkout-session")
async def create_checkout_session(x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    now = time.monotonic()
    recent = [attempt for attempt in checkout_attempts.get(sid, []) if now - attempt < 600]
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="Too many checkout attempts")
    recent.append(now)
    checkout_attempts[sid] = recent
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="Payments are not configured")
    cart = await db.carts.find_one({"session_id": sid}, {"_id": 0})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")

    line_items: list[dict[str, Any]] = []
    checkout_items: list[dict[str, Any]] = []
    subtotal_cents = 0
    requires_compatibility_review = False
    for item in cart["items"]:
        p = await db.products.find_one(
            {"id": item["product_id"], "$or": [{"status": "active"}, {"status": {"$exists": False}}]},
            public_product_projection(),
        )
        quantity = int(item["quantity"])
        if not p:
            raise HTTPException(status_code=400, detail="A product in the cart is unavailable")
        if quantity < 1 or quantity > min(int(p.get("stock", 0)), 20):
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {p['name']}")
        unit_amount = round(float(p["price"]) * 100)
        if unit_amount < 1:
            raise HTTPException(status_code=400, detail="Invalid product price")
        selected_vehicle = item.get("selected_vehicle")
        compatibility_status = "unknown"
        if p.get("compatibilities"):
            if not selected_vehicle:
                raise HTTPException(status_code=400, detail=f"Select and verify a vehicle for {p['name']}")
            vehicle_payload = {key: value for key, value in selected_vehicle.items() if key != "compatibility_status"}
            compatibility_result = check_compatibility(p, VehicleSelection.model_validate(vehicle_payload))
            compatibility_status = compatibility_result["status"]
            if compatibility_status == "incompatible":
                raise HTTPException(status_code=400, detail=f"{p['name']} is incompatible with the selected vehicle")
            if compatibility_status != "compatible":
                requires_compatibility_review = True
        else:
            requires_compatibility_review = True
        subtotal_cents += unit_amount * quantity
        checkout_items.append({
            "product_id": p["id"],
            "sku": p["sku"],
            "name": p["name"],
            "quantity": quantity,
            "unit_amount": unit_amount,
            "selected_vehicle": selected_vehicle,
            "compatibility_status": compatibility_status,
        })
        line_items.append({
            "price_data": {
                "currency": p.get("currency", "EUR").lower(),
                "product_data": {"name": p["name"], "metadata": {"product_id": p["id"], "sku": p["sku"]}},
                "unit_amount": unit_amount,
            },
            "quantity": quantity,
        })

    frontend_url = os.environ.get("FRONTEND_URL", "https://tymotors.vercel.app").rstrip("/")
    free_shipping_threshold = int(os.environ.get("FREE_SHIPPING_THRESHOLD_CENTS", "35000"))
    shipping_cents = 0 if subtotal_cents >= free_shipping_threshold else int(os.environ.get("SHIPPING_RATE_CENTS", "1500"))
    shipping_label = "Livraison UE offerte" if shipping_cents == 0 else "Livraison UE suivie"
    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "order_number": make_order_number(),
        "stripe_session_id": None,
        "stripe_payment_intent_id": None,
        "cart_session_id": sid,
        "status": "pending",
        "payment_status": "unpaid",
        "fulfillment_status": "requires_review" if requires_compatibility_review else "unfulfilled",
        "requires_compatibility_review": requires_compatibility_review,
        "customer_email": None,
        "customer_name": None,
        "shipping_address": {},
        "billing_address": {},
        "items": checkout_items,
        "subtotal_cents": subtotal_cents,
        "shipping_cents": shipping_cents,
        "tax_cents": 0,
        "total_cents": subtotal_cents + shipping_cents,
        "currency": "EUR",
        "stock_reduced": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paid_at": None,
        "shipped_at": None,
    }
    await db.orders.insert_one(order)
    try:
        session = stripe.checkout.Session.create(
            line_items=line_items,
            mode="payment",
            success_url=f"{frontend_url}/order-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/cart",
            client_reference_id=sid,
            customer_creation="always",
            billing_address_collection="required",
            shipping_address_collection={"allowed_countries": ["FR", "BE", "DE", "ES", "IT", "LU", "NL", "PT"]},
            phone_number_collection={"enabled": True},
            shipping_options=[{"shipping_rate_data": {"type": "fixed_amount", "fixed_amount": {"amount": shipping_cents, "currency": "eur"}, "display_name": shipping_label}}],
            metadata={"order_id": order_id, "cart_session_id": sid},
            payment_intent_data={"metadata": {"order_id": order_id, "cart_session_id": sid}},
        )
    except stripe.StripeError:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"status": "checkout_failed", "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        raise HTTPException(status_code=502, detail="Payment provider is temporarily unavailable")
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"stripe_session_id": session.id, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"url": session.url}


@api_router.get("/checkout-session/{stripe_session_id}")
async def get_checkout_session(stripe_session_id: str, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    if not stripe_session_id.startswith("cs_") or len(stripe_session_id) > 255:
        raise HTTPException(status_code=400, detail="Invalid checkout session")
    order = await db.orders.find_one({"stripe_session_id": stripe_session_id, "cart_session_id": sid}, {"_id": 0, "admin": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Checkout session not found")
    return {
        "paid": order.get("payment_status") == "paid",
        "status": order.get("status"),
        "payment_status": order.get("payment_status"),
        "fulfillment_status": order.get("fulfillment_status"),
        "order_reference": order.get("order_number"),
        "customer_email": order.get("customer_email"),
        "items": order.get("items", []),
        "subtotal": order.get("subtotal_cents", 0) / 100,
        "shipping": order.get("shipping_cents", 0) / 100,
        "tax": order.get("tax_cents", 0) / 100,
        "total": order.get("total_cents", 0) / 100,
        "currency": order.get("currency", "EUR"),
    }


async def mark_order_paid(order_id: str, payment_intent_id: Optional[str], session: Optional[dict] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    current_order = await db.orders.find_one({"id": order_id}, {"_id": 0, "requires_compatibility_review": 1})
    fulfillment_status = "requires_review" if (current_order or {}).get("requires_compatibility_review") else "processing"
    customer_details = (session or {}).get("customer_details") or {}
    collected = (session or {}).get("collected_information") or {}
    shipping_details = collected.get("shipping_details") or (session or {}).get("shipping_details") or {}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "status": "paid",
            "payment_status": "paid",
            "fulfillment_status": fulfillment_status,
            "stripe_payment_intent_id": payment_intent_id,
            "customer_email": customer_details.get("email"),
            "customer_name": customer_details.get("name"),
            "billing_address": customer_details.get("address") or {},
            "shipping_address": shipping_details.get("address") or {},
            "paid_at": now,
            "updated_at": now,
        }},
    )
    claimed = await db.orders.find_one_and_update(
        {"id": order_id, "stock_reduced": {"$ne": True}},
        {"$set": {"stock_reduced": True}},
        return_document=ReturnDocument.AFTER,
    )
    if not claimed:
        return
    stock_ok = True
    for item in claimed.get("items", []):
        result = await db.products.update_one(
            {"id": item["product_id"], "stock": {"$gte": item["quantity"]}},
            {"$inc": {"stock": -item["quantity"]}},
        )
        stock_ok = stock_ok and result.modified_count == 1
    if not stock_ok:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"fulfillment_status": "requires_review", "inventory_issue": True}},
        )
    await db.carts.update_one({"session_id": claimed["cart_session_id"]}, {"$set": {"items": []}}, upsert=True)


@api_router.get("/admin/orders")
async def list_admin_orders(
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
    _: dict[str, Any] = Depends(require_admin),
):
    query = {"status": status} if status else {}
    total = await db.orders.count_documents(query)
    items = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "items": items}


@api_router.put("/admin/orders/{order_id}")
async def update_admin_order(
    order_id: str,
    payload: AdminOrderUpdateInput,
    admin: dict[str, Any] = Depends(require_admin),
):
    updates: dict[str, Any] = {
        "fulfillment_status": payload.fulfillment_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload.tracking_number is not None:
        updates["tracking_number"] = payload.tracking_number.strip()
    if payload.fulfillment_status == "shipped":
        updates["shipped_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.orders.find_one_and_update(
        {"id": order_id}, {"$set": updates}, projection={"_id": 0}, return_document=ReturnDocument.AFTER
    )
    if not result:
        raise HTTPException(status_code=404, detail="Order not found")
    await audit_admin("update_order", admin, order_id, {"fulfillment_status": payload.fulfillment_status})
    return result


@api_router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(default=None)):
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook is not configured")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_id = event["id"]
    try:
        existing_event = await db.stripe_events.find_one_and_update(
            {"event_id": event_id},
            {"$setOnInsert": {"event_id": event_id, "type": event["type"], "status": "processing", "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
    except DuplicateKeyError:
        existing_event = await db.stripe_events.find_one({"event_id": event_id}, {"_id": 0})
    if existing_event and existing_event.get("status") == "completed":
        return {"received": True, "duplicate": True}

    try:
        event_type = event["type"]
        obj = event["data"]["object"]
        if event_type == "checkout.session.completed":
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id and obj.get("payment_status") == "paid":
                await mark_order_paid(order_id, obj.get("payment_intent"), obj)
        elif event_type == "payment_intent.succeeded":
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id:
                order = await db.orders.find_one({"id": order_id}, {"_id": 0})
                session = None
                if order and order.get("stripe_session_id"):
                    session = stripe.checkout.Session.retrieve(order["stripe_session_id"]).to_dict_recursive()
                await mark_order_paid(order_id, obj.get("id"), session)
        elif event_type == "payment_intent.payment_failed":
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id:
                await db.orders.update_one(
                    {"id": order_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "payment_failed", "payment_status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()}},
                )
        elif event_type == "charge.refunded":
            await db.orders.update_one(
                {"stripe_payment_intent_id": obj.get("payment_intent")},
                {"$set": {"status": "refunded", "payment_status": "refunded", "updated_at": datetime.now(timezone.utc).isoformat()}},
            )
        await db.stripe_events.update_one(
            {"event_id": event_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}},
        )
    except Exception:
        await db.stripe_events.update_one(
            {"event_id": event_id},
            {"$set": {"status": "failed", "failed_at": datetime.now(timezone.utc).isoformat()}},
        )
        logger.exception("Stripe webhook processing failed for event %s", event_id)
        raise HTTPException(status_code=500, detail="Webhook processing failed")
    return {"received": True}
app.include_router(api_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/admin") or "checkout" in request.url.path else "no-cache"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=[origin.strip() for origin in os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(',') if origin.strip()],
    allow_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-Id", "Stripe-Signature"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def validate_configuration_and_indexes():
    environment = os.environ.get("ENVIRONMENT", "test").lower()
    cors_origins = [value.strip() for value in os.environ.get("CORS_ORIGINS", "").split(",") if value.strip()]
    if "*" in cors_origins:
        raise RuntimeError("CORS_ORIGINS must not contain a wildcard")
    if environment != "production" and stripe.api_key and not stripe.api_key.startswith("sk_test_"):
        raise RuntimeError("A live Stripe key cannot be used outside production")
    await db.products.create_index("slug", unique=True)
    await db.products.create_index("sku", unique=True, sparse=True)
    await db.products.create_index([("status", 1), ("category_slug", 1), ("featured", 1)])
    await db.products.create_index([("compatibilities.brand_slug", 1), ("compatibilities.model", 1), ("compatibilities.chassis", 1)])
    await db.orders.create_index("order_number", unique=True)
    await db.orders.create_index("stripe_session_id", unique=True, sparse=True)
    await db.orders.create_index("stripe_payment_intent_id", sparse=True)
    await db.orders.create_index([("status", 1), ("created_at", -1)])
    await db.stripe_events.create_index("event_id", unique=True)
    await db.admin_audit.create_index("created_at")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
