"""Back-office API. All routes share the live server-side administrator check."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, model_validator


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StockInput(StrictInput):
    expected_stock: int = Field(ge=0)
    delta: int = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=3, max_length=200)


class ReturnInput(StrictInput):
    order_item_id: UUID
    quantity: int = Field(ge=1, le=20)
    reason: str = Field(min_length=3, max_length=1000)


class ReturnUpdate(StrictInput):
    status: Literal["requested", "review", "accepted", "received", "refunded", "rejected"] | None = None
    restock: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class ChannelInput(StrictInput):
    status: Literal["unpublished", "draft", "to_publish", "published", "needs_update", "error"]
    listing_id: str | None = Field(default=None, max_length=200)
    listing_url: str | None = Field(default=None, max_length=1000, pattern=r"^https://")
    notes: str | None = Field(default=None, max_length=2000)


class SettingsInput(StrictInput):
    shop_name: str = Field(min_length=2, max_length=100)
    contact_email: EmailStr | None = None
    low_stock_threshold: int = Field(ge=0, le=100000)
    currency: Literal["EUR"] = "EUR"


class PromotionInput(StrictInput):
    code: str = Field(pattern=r"^[A-Z0-9_-]{3,40}$")
    active: bool = False
    discount_type: Literal["percent", "fixed"]
    value: int = Field(gt=0, le=10000000)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    minimum_amount_cents: int = Field(default=0, ge=0)
    max_uses: int | None = Field(default=None, gt=0)
    product_ids: list[UUID] = Field(default_factory=list, max_length=100)
    category_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.discount_type == "percent" and self.value > 100:
            raise ValueError("Percentage must not exceed 100")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("End date must follow start date")
        return self


def search_filter(q: str, fields: list[str]) -> str:
    # PostgREST filter grammar is not SQL; remove its operators and wildcards.
    term = re.sub(r"[^\w\s@+\-]", " ", q, flags=re.UNICODE).strip()
    return "(" + ",".join(f"{field}.ilike.*{term}*" for field in fields) + ")"


def product_input_data(product: dict, schema) -> dict:
    result = {k: v for k, v in product.items() if k in schema.model_fields}
    result["compatibilities"] = [{k: v for k, v in c.items() if k != "id"} for c in result.get("compatibilities", [])]
    return result


def create_admin_router(db, catalog, require_admin, audit, stripe_test_mode: bool = False):
    router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

    @router.get("/dashboard")
    async def dashboard(admin=Depends(require_admin)):
        return await db.rpc("admin_dashboard", {"p_actor": admin["id"]})

    @router.get("/catalog-options")
    async def options():
        return {"brands": await catalog.brands(include_inactive=True),
                "categories": await catalog.categories(include_inactive=True)}

    @router.get("/products/{product_id}")
    async def product_detail(product_id: UUID):
        p = await catalog.product_by("id", str(product_id), public_only=False, include_admin=True)
        if not p:
            raise HTTPException(404, "Produit introuvable")
        return p

    @router.get("/orders/{order_id}")
    async def order_detail(order_id: UUID):
        rows = await db.select("orders", params={"id": f"eq.{order_id}", "limit": 1})
        if not rows:
            raise HTTPException(404, "Commande introuvable")
        payment_intent = rows[0].get("stripe_payment_intent_id")
        stripe_prefix = "https://dashboard.stripe.com/test/payments/" if stripe_test_mode else "https://dashboard.stripe.com/payments/"
        return {**rows[0],
                "stripe_dashboard_url": stripe_prefix + payment_intent if payment_intent else None,
                "items": await db.select("order_items", params={"order_id": f"eq.{order_id}", "order": "created_at.asc"}),
                "history": await db.select("admin_audit", params={"resource": f"eq.{order_id}", "order": "created_at.desc", "limit": 50}),
                "emails": await db.select("email_logs", params={"order_id": f"eq.{order_id}", "order": "created_at.desc", "limit": 50}),
                "returns": await db.select("returns", params={"order_id": f"eq.{order_id}", "order": "created_at.desc", "limit": 50})}

    @router.get("/inventory")
    async def inventory(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                        q: str = Query("", max_length=120), status: Literal["", "low", "out", "available"] = ""):
        params = {"select": "*", "order": "stock.asc,id.asc", "status": "neq.archived"}
        if q: params["or"] = search_filter(q, ["name", "sku"])
        if status: params["stock_status"] = f"eq.{status}"
        return await db.page("admin_inventory", params=params, page=page, limit=limit)

    @router.post("/inventory/{product_id}")
    async def adjust_stock(product_id: UUID, payload: StockInput, admin=Depends(require_admin)):
        return await db.rpc("admin_adjust_stock", {"p_actor": admin["id"], "p_product_id": str(product_id),
            "p_expected": payload.expected_stock, "p_delta": payload.delta, "p_reason": payload.reason})

    @router.get("/inventory/{product_id}/movements")
    async def movements(product_id: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100)):
        return await db.page("inventory_movements", params={"product_id": f"eq.{product_id}", "order": "created_at.desc,id.desc"}, page=page, limit=limit)

    @router.get("/customers")
    async def customers(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), q: str = Query("", max_length=120)):
        params = {"select": "*", "order": "last_order_at.desc.nullslast,email.asc"}
        if q: params["or"] = search_filter(q, ["full_name", "email"])
        return await db.page("admin_customers", params=params, page=page, limit=limit)

    @router.get("/customers/detail")
    async def customer(email: EmailStr, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100)):
        rows = await db.select("admin_customers", params={"email": f"eq.{str(email).lower()}", "limit": 1})
        if not rows: raise HTTPException(404, "Client introuvable")
        orders = await db.page("orders", params={"customer_email": f"ilike.{email}", "order": "created_at.desc,id.desc"}, page=page, limit=limit)
        return {**rows[0], "orders": orders}

    @router.get("/returns")
    async def returns(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                      status: Literal["", "requested", "review", "accepted", "received", "refunded", "rejected"] = ""):
        params = {"select": "*,orders(order_number,customer_email),order_items(product_name)", "order": "created_at.desc,id.desc"}
        if status: params["status"] = f"eq.{status}"
        return await db.page("returns", params=params, page=page, limit=limit)

    @router.post("/returns", status_code=201)
    async def create_return(payload: ReturnInput, admin=Depends(require_admin)):
        return {"id": await db.rpc("admin_return_action", {"p_actor": admin["id"], "p_id": None, "p_data": payload.model_dump(mode="json")})}

    @router.patch("/returns/{return_id}")
    async def update_return(return_id: UUID, payload: ReturnUpdate, admin=Depends(require_admin)):
        return {"id": await db.rpc("admin_return_action", {"p_actor": admin["id"], "p_id": str(return_id), "p_data": payload.model_dump(exclude_none=True)})}

    @router.get("/channels")
    async def channels():
        return {"items": await db.select("sales_channels", params={"order": "slug.desc"})}

    @router.get("/channels/{channel}")
    async def channel_products(channel: str, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), q: str = Query("", max_length=120)):
        channels = await db.select("sales_channels", params={"slug": f"eq.{channel}", "limit": 1})
        if not channels: raise HTTPException(404, "Canal inconnu")
        params = {"select": "id,name,sku,status", "order": "name.asc,id.asc"}
        if q: params["or"] = search_filter(q, ["name", "sku"])
        result = await db.page("products", params=params, page=page, limit=limit)
        ids = [p["id"] for p in result["items"]]
        records = await db.select("product_channels", params={"channel_slug": f"eq.{channel}", "product_id": "in.(" + ",".join(ids) + ")"}) if ids else []
        mapping = {r["product_id"]: r for r in records}
        result["items"] = [{**p, "publication": ({"status": "published" if p["status"] == "active" else "unpublished"} if channels[0]["mode"] == "website" else mapping.get(p["id"], {"status": "unpublished"}))} for p in result["items"]]
        return {**result, "channel": channels[0]}

    @router.put("/channels/{channel}/{product_id}")
    async def update_channel(channel: str, product_id: UUID, payload: ChannelInput, admin=Depends(require_admin)):
        rows = await db.select("sales_channels", params={"slug": f"eq.{channel}", "mode": "eq.manual", "limit": 1})
        if not rows: raise HTTPException(422, "La publication du site dépend du statut produit")
        return await db.rpc("admin_save_record", {"p_actor": admin["id"], "p_kind": "channel", "p_id": str(product_id),
            "p_data": {**payload.model_dump(), "channel_slug": channel}})

    @router.get("/settings")
    async def settings():
        return (await db.select("shop_settings", params={"id": "eq.true", "limit": 1}))[0]

    @router.put("/settings")
    async def save_settings(payload: SettingsInput, admin=Depends(require_admin)):
        return await db.rpc("admin_save_record", {"p_actor": admin["id"], "p_kind": "settings", "p_id": None, "p_data": payload.model_dump(mode="json")})

    @router.get("/promotions")
    async def promotions(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100), q: str = Query("", max_length=120)):
        params = {"select": "*", "order": "created_at.desc,id.desc"}
        if q: params["or"] = search_filter(q, ["code"])
        return await db.page("promotions", params=params, page=page, limit=limit)

    @router.post("/promotions", status_code=201)
    async def new_promotion(payload: PromotionInput, admin=Depends(require_admin)):
        return await db.rpc("admin_save_record", {"p_actor": admin["id"], "p_kind": "promotion", "p_id": None, "p_data": payload.model_dump(mode="json")})

    @router.put("/promotions/{promotion_id}")
    async def update_promotion(promotion_id: UUID, payload: PromotionInput, admin=Depends(require_admin)):
        return await db.rpc("admin_save_record", {"p_actor": admin["id"], "p_kind": "promotion", "p_id": str(promotion_id), "p_data": payload.model_dump(mode="json")})

    @router.get("/audit")
    async def history(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100)):
        return await db.page("admin_audit", params={"order": "created_at.desc,id.desc"}, page=page, limit=limit)

    return router
