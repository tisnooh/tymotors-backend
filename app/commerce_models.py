"""Private commerce contracts. No supplier statement is verified by default."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import VehicleSelection

Money = Annotated[int, Field(strict=True, ge=0, le=2_000_000_000)]
Verification = Literal['pending', 'verified', 'rejected']
Kind = Literal['agent', 'variant', 'offer', 'shipping_rate']


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class AgentInput(StrictInput):
    profile_id: UUID
    name: str = Field(min_length=2, max_length=160)
    role: Literal['sourcing', 'catalogue', 'pricing', 'orders', 'supervisor']
    is_active: bool = False


class VariantInput(StrictInput):
    product_id: UUID
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=30)
    currency: Literal['EUR'] = 'EUR'
    price_cents: Money
    stock: int = Field(default=0, strict=True, ge=0, le=100000)
    status: Literal['draft', 'active', 'archived'] = 'draft'
    is_verified: bool = False
    requires_vehicle: bool = True
    sale_tax_bps: int | None = Field(default=None, strict=True, ge=0, le=10000)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    is_default: bool = False
    compatibility_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def activation(self):
        if self.status == 'active' and not (self.is_verified and self.evidence_ref):
            raise ValueError('An active variant requires verification evidence')
        if self.status == 'active' and self.requires_vehicle and not self.compatibility_ids:
            raise ValueError('A vehicle-specific active variant needs explicit fitment associations')
        if len(self.compatibility_ids) != len(set(self.compatibility_ids)):
            raise ValueError('Duplicate compatibility association')
        if any(len(k) > 100 or len(v) > 500 for k, v in self.attributes.items()):
            raise ValueError('Variant attributes too long')
        return self


class OfferInput(StrictInput):
    variant_id: UUID
    supplier_id: UUID
    supplier_sku: str = Field(min_length=1, max_length=200)
    supplier_variant: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=9, max_length=2000)
    verification_state: Verification = 'pending'
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    is_primary: bool = False
    availability: Literal['unknown', 'available', 'unavailable'] = 'unknown'
    available_quantity: int | None = Field(default=None, strict=True, ge=0, le=1000000)
    valid_until: AwareDatetime | None = None
    unit_cost_cents: Money | None = None
    recoverable_tax_cents: Money | None = None
    currency: Literal['EUR', 'USD', 'GBP', 'CNY'] = 'EUR'
    fx_rate: Decimal | None = Field(default=None, gt=0, le=1000000, max_digits=20, decimal_places=10)
    fx_evidence_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    fx_valid_until: AwareDatetime | None = None
    moq: int = Field(default=1, strict=True, ge=1, le=1000000)
    preparation_days_min: int | None = Field(default=None, strict=True, ge=0, le=730)
    preparation_days_max: int | None = Field(default=None, strict=True, ge=0, le=730)
    responsible_agent_id: UUID | None = None

    @field_validator('url')
    @classmethod
    def secure_url(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError('A public HTTPS supplier link without credentials is required')
        return value

    @model_validator(mode='after')
    def coherent_terms(self):
        if self.verification_state == 'verified' and not self.evidence_ref:
            raise ValueError('Verified supplier terms need identifiable evidence')
        if (self.recoverable_tax_cents is not None and self.unit_cost_cents is not None
                and self.recoverable_tax_cents > self.unit_cost_cents):
            raise ValueError('Recoverable tax cannot exceed the tax-inclusive unit cost')
        if (self.preparation_days_min is not None and self.preparation_days_max is not None
                and self.preparation_days_min > self.preparation_days_max):
            raise ValueError('Preparation range reversed')
        return self


class ShippingRateInput(StrictInput):
    offer_id: UUID
    country: str = Field(pattern=r'^[A-Z]{2}$')
    postal_prefix: str = Field(default='', max_length=20, pattern=r'^[A-Za-z0-9 -]*$')
    mode: str = Field(min_length=1, max_length=100)
    # Several variants from one supplier may not silently share or duplicate
    # transport terms. Independent parcels require explicit supplier evidence.
    multi_variant_policy: Literal['unknown', 'independent_parcels'] = 'unknown'
    min_quantity: int = Field(default=1, strict=True, ge=1, le=1000000)
    max_quantity: int = Field(strict=True, ge=1, le=1000000)
    currency: Literal['EUR'] = 'EUR'
    # These amounts cover the WHOLE line quantity in the stated range, not each unit.
    shipping_cost_cents: Money | None = None
    shipping_recoverable_tax_cents: Money | None = None
    customer_shipping_cents: Money | None = None
    goods_tax_bps: int | None = Field(default=None, strict=True, ge=0, le=10000)
    shipping_tax_bps: int | None = Field(default=None, strict=True, ge=0, le=10000)
    agent_fee_cents: Money | None = None
    import_duty_cents: Money | None = None
    nonrecoverable_tax_cents: Money | None = None
    other_cost_cents: Money | None = None
    verification_state: Verification = 'pending'
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1000)
    valid_until: AwareDatetime | None = None
    delivery_days_min: int | None = Field(default=None, strict=True, ge=0, le=730)
    delivery_days_max: int | None = Field(default=None, strict=True, ge=0, le=730)

    @model_validator(mode='after')
    def coherent_terms(self):
        if self.min_quantity > self.max_quantity:
            raise ValueError('Quantity range reversed')
        if self.verification_state == 'verified' and not self.evidence_ref:
            raise ValueError('Verified shipping needs identifiable evidence')
        if (self.shipping_recoverable_tax_cents is not None and self.shipping_cost_cents is not None
                and self.shipping_recoverable_tax_cents > self.shipping_cost_cents):
            raise ValueError('Recoverable shipping tax cannot exceed shipping cost')
        if (self.delivery_days_min is not None and self.delivery_days_max is not None
                and self.delivery_days_min > self.delivery_days_max):
            raise ValueError('Delivery range reversed')
        return self


class SaveInput(StrictInput):
    data: dict[str, Any]
    expected_updated_at: AwareDatetime | None = None


class QuoteInput(StrictInput):
    variant_id: UUID
    quantity: int = Field(strict=True, ge=1, le=20)
    country: str = Field(pattern=r'^[A-Z]{2}$')
    postal_code: str = Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9 -]+$')
    mode: str = Field(min_length=1, max_length=100)
    selected_vehicle: VehicleSelection | None = None

    @field_validator('postal_code')
    @classmethod
    def meaningful_postcode(cls, value):
        if not any(character.isalnum() for character in value):
            raise ValueError('A nonempty postal destination is required')
        return value


class QuoteDestinationInput(StrictInput):
    name: str = Field(min_length=2, max_length=160)
    line1: str = Field(min_length=3, max_length=200)
    line2: str = Field(default='', max_length=200)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(default='', max_length=100)
    postal_code: str = Field(min_length=1, max_length=20, pattern=r'^[A-Za-z0-9 -]+$')
    country: str = Field(pattern=r'^[A-Z]{2}$')
    phone: str = Field(default='', max_length=40)

    @field_validator('*')
    @classmethod
    def no_control_characters(cls, value):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError('Control characters are not allowed in a destination')
        return value

    @field_validator('postal_code')
    @classmethod
    def meaningful_postcode(cls, value):
        return QuoteInput.meaningful_postcode(value)

    @model_validator(mode='after')
    def french_postcode_format(self):
        # Format only, not a claim that the address exists or is serviceable.
        if self.country == 'FR' and (len(self.postal_code) != 5
                or any(character not in '0123456789' for character in self.postal_code)):
            raise ValueError('A French destination requires a five-digit postal code')
        return self


DELIVERY_DISCOVERY_MODE = '__delivery_options_discovery__'


class CartDeliveryOptionsInput(StrictInput):
    destination: QuoteDestinationInput


class CartQuoteInput(StrictInput):
    request_key: UUID
    destination: QuoteDestinationInput
    mode: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')

    @field_validator('mode')
    @classmethod
    def commercial_mode_only(cls, value):
        if value == DELIVERY_DISCOVERY_MODE:
            raise ValueError('Internal discovery mode cannot be quoted')
        return value


MODELS = {'agent': AgentInput, 'variant': VariantInput, 'offer': OfferInput, 'shipping_rate': ShippingRateInput}
TABLES = {'agent': 'commerce_agents', 'variant': 'product_variants', 'offer': 'supplier_offers', 'shipping_rate': 'shipping_rates'}
