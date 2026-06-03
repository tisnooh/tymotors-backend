from fastapi import FastAPI, APIRouter, HTTPException, Header, Query, UploadFile, File
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Literal
import uuid
import stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
from datetime import datetime, timezone
import cloudinary
import cloudinary.uploader

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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="TYMotors API", version="1.0.0")
api_router = APIRouter(prefix="/api")

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
    subcategories: List[str] = []  # e.g. ['Grilles','Spoilers']
    order: int = 0


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
    images: List[str] = []
    category_slug: str  # performance | interior | technology
    subcategory: str  # e.g. 'Grilles'
    compatible_brands: List[str] = []  # brand slugs
    badges: List[str] = []  # e.g. ['New','Best Seller','Carbon']
    sku: str
    stock: int = 25
    rating: float = 4.8
    review_count: int = 0
    featured: bool = False
    specs: dict = {}  # key/value spec sheet
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VehicleModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brand_slug: str
    name: str  # e.g. 'M3', 'C-Class'
    generations: List[str] = []  # e.g. ['G80 (2020+)','F80 (2014-2018)']


class ProductCreateInput(BaseModel):
    slug: str
    name: str
    subtitle: str
    description: str
    price: float
    compare_at_price: Optional[float] = None
    currency: str = "EUR"
    images: List[str] = []
    category_slug: str
    subcategory: str
    compatible_brands: List[str] = []
    badges: List[str] = []
    sku: str
    stock: int = 25
    rating: float = 4.8
    review_count: int = 0
    featured: bool = False
    specs: dict = {}


class ProductUpdateInput(BaseModel):
    name: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    compare_at_price: Optional[float] = None
    currency: Optional[str] = None
    images: Optional[List[str]] = None
    category_slug: Optional[str] = None
    subcategory: Optional[str] = None
    compatible_brands: Optional[List[str]] = None
    badges: Optional[List[str]] = None
    sku: Optional[str] = None
    stock: Optional[int] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    featured: Optional[bool] = None
    specs: Optional[dict] = None


class CartItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: str
    quantity: int = 1


class CartItemInput(BaseModel):
    product_id: str
    quantity: int = 1


class CartUpdateInput(BaseModel):
    product_id: str
    quantity: int


class WishlistInput(BaseModel):
    product_id: str


class NewsletterInput(BaseModel):
    email: EmailStr
    locale: Optional[str] = "en"


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
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")
    return x_session_id


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
    subcategory: Optional[str] = None,
    featured: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = Query(60, ge=1, le=200),
    skip: int = Query(0, ge=0)
):
    query: dict = {}
    if category:
        query["category_slug"] = category
    if subcategory:
        query["subcategory"] = subcategory
    if brand:
        query["compatible_brands"] = brand
    if featured is not None:
        query["featured"] = featured
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"subtitle": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"subcategory": {"$regex": q, "$options": "i"}},
        ]

    total = await db.products.count_documents(query)
    docs = await db.products.find(query, {"_id": 0}).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "items": docs}


@api_router.get("/products/{slug}")
async def get_product(slug: str):
    doc = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc


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
            })
    return {"session_id": sid, "items": items, "subtotal": round(subtotal, 2), "currency": "EUR"}


@api_router.post("/cart")
async def add_to_cart(payload: CartItemInput, x_session_id: Optional[str] = Header(default=None)):
    sid = await require_session(x_session_id)
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be >= 1")
    p = await db.products.find_one({"id": payload.product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    cart = await db.carts.find_one({"session_id": sid}, {"_id": 0})
    if not cart:
        cart = {"session_id": sid, "items": [{"product_id": payload.product_id, "quantity": payload.quantity}]}
        await db.carts.insert_one(cart)
    else:
        items = cart.get("items", [])
        found = False
        for it in items:
            if it["product_id"] == payload.product_id:
                it["quantity"] += payload.quantity
                found = True
                break
        if not found:
            items.append({"product_id": payload.product_id, "quantity": payload.quantity})
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


# ---------- ADMIN - UPLOAD IMAGE ----------

@api_router.post("/admin/upload-image")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    contents = await file.read()
    result = cloudinary.uploader.upload(
        contents,
        folder="tymotors/products",
        resource_type="image"
    )
    return {"url": result["secure_url"], "public_id": result["public_id"]}


# ---------- ADMIN - PRODUCTS CRUD ----------

@api_router.post("/admin/products")
async def create_product(payload: ProductCreateInput):
    existing = await db.products.find_one({"slug": payload.slug}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")
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
        badges=payload.badges,
        sku=payload.sku,
        stock=payload.stock,
        rating=payload.rating,
        review_count=payload.review_count,
        featured=payload.featured,
        specs=payload.specs,
    )
    doc = product.model_dump()
    doc["created_at"] = doc["created_at"].isoformat()
    await db.products.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/admin/products/{slug}")
async def update_product(slug: str, payload: ProductUpdateInput):
    existing = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.products.update_one({"slug": slug}, {"$set": updates})
    doc = await db.products.find_one({"slug": slug}, {"_id": 0})
    return doc


@api_router.delete("/admin/products/{slug}")
async def delete_product(slug: str):
    existing = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.products.delete_one({"slug": slug})
    return {"ok": True, "deleted": slug}


# Include the router
class CheckoutInput(BaseModel):
    items: List[CartItem]

@api_router.post("/create-checkout-session")
async def create_checkout_session(payload: CheckoutInput, x_session_id: Optional[str] = Header(default=None)):
    line_items = []
    for item in payload.items:
        p = await db.products.find_one({"id": item.product_id}, {"_id": 0})
        if p:
            line_items.append({
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": p["name"]},
                    "unit_amount": int(float(p["price"]) * 100),
                },
                "quantity": item.quantity,
            })
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url="https://tymotors.vercel.app/order-success",
        cancel_url="https://tymotors.vercel.app/cart",
    )
    return {"url": session.url}
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
