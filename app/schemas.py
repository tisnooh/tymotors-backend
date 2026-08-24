from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ProductCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    model: str | None = Field(default=None, max_length=100)
    chassis: str | None = Field(default=None, max_length=50)
    generation: str | None = Field(default=None, max_length=100)
    year_from: int | None = Field(default=None, ge=1950, le=2100)
    year_to: int | None = Field(default=None, ge=1950, le=2100)
    body_types: list[str] = Field(default_factory=list)
    facelift: Literal["pre-lci", "lci", "any", "unknown"] = "unknown"
    required_trim: list[str] = Field(default_factory=list)
    excluded_trims: list[str] = Field(default_factory=list)
    camera_compatible: bool | None = None
    parking_sensor_compatible: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)
    is_verified: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        return self


class VehicleSelection(BaseModel):
    brand_slug: str
    model: str | None = None
    chassis: str | None = None
    generation: str | None = None
    year: int | None = Field(default=None, ge=1950, le=2100)
    body_type: str | None = None
    trim: str | None = None
    has_camera: bool | None = None
    has_parking_sensors: bool | None = None


class SupplierData(BaseModel):
    supplier_reference: str | None = Field(default=None, max_length=200)
    supplier_name: str | None = Field(default=None, max_length=200)
    supplier_url: str | None = Field(default=None, max_length=1000)
    exact_source_url: str | None = Field(default=None, max_length=1000)
    cost_price: float | None = Field(default=None, ge=0)
    shipping_cost: float | None = Field(default=None, ge=0)
    landed_cost: float | None = Field(default=None, ge=0)
    margin_amount: float | None = None
    margin_percent: float | None = None
    moq: int | None = Field(default=None, ge=1)
    supplier_verified: bool = False
    notes: str | None = None


class ProductInput(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=160)
    subtitle: str = Field(default="", max_length=240)
    description: str = Field(min_length=20, max_length=5000)
    price: float = Field(gt=0, le=100000)
    compare_at_price: float | None = Field(default=None, gt=0, le=100000)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    images: list[str] = Field(default_factory=list)
    category_slug: str
    subcategory: str = ""
    compatible_brands: list[str] = Field(default_factory=list)
    compatibilities: list[ProductCompatibility] = Field(default_factory=list)
    badges: list[str] = Field(default_factory=list)
    sku: str = Field(min_length=2, max_length=80)
    stock: int = Field(default=0, ge=0, le=100000)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    featured: bool = False
    specs: dict[str, Any] = Field(default_factory=dict)
    package_contents: list[str] = Field(default_factory=list)
    installation_difficulty: Literal["easy", "medium", "advanced", "professional"] | None = None
    installation_minutes: int | None = Field(default=None, ge=0, le=1440)
    tools_required: list[str] = Field(default_factory=list)
    warranty_months: int | None = Field(default=None, ge=0, le=120)
    delivery_estimate: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "active", "archived"] = "draft"
    is_verified: bool = False
    admin: SupplierData = Field(default_factory=SupplierData)

    @model_validator(mode="after")
    def active_is_complete(self):
        if self.status != "active":
            return self
        missing: list[str] = []
        if not self.is_verified: missing.append("is_verified")
        if not self.images: missing.append("images")
        if not self.compatibilities or not all(c.is_verified for c in self.compatibilities): missing.append("verified compatibilities")
        if not self.package_contents: missing.append("package_contents")
        if not self.installation_difficulty: missing.append("installation_difficulty")
        if not self.delivery_estimate: missing.append("delivery_estimate")
        if not self.admin.supplier_name or not self.admin.supplier_verified: missing.append("verified supplier")
        if self.admin.cost_price is None: missing.append("cost_price")
        if missing:
            raise ValueError("Active products require: " + ", ".join(missing))
        return self


class ProductUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=160)
    subtitle: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, min_length=20, max_length=5000)
    price: float | None = Field(default=None, gt=0, le=100000)
    compare_at_price: float | None = Field(default=None, gt=0, le=100000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    images: list[str] | None = None
    category_slug: str | None = None
    subcategory: str | None = None
    compatible_brands: list[str] | None = None
    compatibilities: list[ProductCompatibility] | None = None
    badges: list[str] | None = None
    sku: str | None = Field(default=None, min_length=2, max_length=80)
    stock: int | None = Field(default=None, ge=0, le=100000)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    featured: bool | None = None
    specs: dict[str, Any] | None = None
    package_contents: list[str] | None = None
    installation_difficulty: Literal["easy", "medium", "advanced", "professional"] | None = None
    installation_minutes: int | None = Field(default=None, ge=0, le=1440)
    tools_required: list[str] | None = None
    warranty_months: int | None = Field(default=None, ge=0, le=120)
    delivery_estimate: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "active", "archived"] | None = None
    is_verified: bool | None = None
    admin: SupplierData | None = None


class CartItemInput(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1, le=20)
    selected_vehicle: VehicleSelection | None = None


class CartUpdateInput(BaseModel):
    product_id: str
    quantity: int = Field(ge=0, le=20)


class WishlistInput(BaseModel):
    product_id: str


class NewsletterInput(BaseModel):
    email: EmailStr
    locale: str = "fr"


class ContactInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=10, max_length=5000)
    website: str = Field(default="", max_length=200)


class AdminOrderUpdateInput(BaseModel):
    fulfillment_status: Literal["unfulfilled", "processing", "shipped", "delivered", "cancelled", "requires_review"]
    tracking_number: str | None = Field(default=None, max_length=200)


class ProfileUpdateInput(BaseModel):
    full_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    billing_address: dict[str, Any] | None = None
    shipping_address: dict[str, Any] | None = None
