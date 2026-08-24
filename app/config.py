from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _csv(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


@dataclass(frozen=True)
class Settings:
    environment: str
    supabase_url: str
    supabase_publishable_key: str
    supabase_service_role_key: str
    frontend_url: str
    cors_origins: list[str]
    cors_origin_regex: str | None
    stripe_secret_key: str
    stripe_webhook_secret: str
    shipping_rate_cents: int
    free_shipping_threshold_cents: int
    cloudinary_url: str
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str

    def validate(self) -> None:
        if not self.supabase_url.startswith("https://") or ".supabase.co" not in self.supabase_url:
            raise RuntimeError("SUPABASE_URL must be a hosted Supabase project URL")
        if not self.supabase_publishable_key:
            raise RuntimeError("SUPABASE_PUBLISHABLE_KEY is required")
        if not self.supabase_service_role_key:
            raise RuntimeError("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is required")
        if self.supabase_publishable_key == self.supabase_service_role_key:
            raise RuntimeError("Publishable and service-role keys must be different")
        if "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS must not contain a wildcard")
        if self.environment != "production" and self.stripe_secret_key and not self.stripe_secret_key.startswith("sk_test_"):
            raise RuntimeError("A live Stripe key cannot be used outside production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings(
        environment=os.getenv("ENVIRONMENT", "test").lower(),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
        supabase_service_role_key=(
            os.getenv("SUPABASE_SECRET_KEY", "")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        ),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/"),
        cors_origins=_csv("CORS_ORIGINS", "http://localhost:3000"),
        cors_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", ""),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
        shipping_rate_cents=max(0, int(os.getenv("SHIPPING_RATE_CENTS", "1500"))),
        free_shipping_threshold_cents=max(0, int(os.getenv("FREE_SHIPPING_THRESHOLD_CENTS", "35000"))),
        cloudinary_url=os.getenv("CLOUDINARY_URL", ""),
        cloudinary_cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
        cloudinary_api_key=os.getenv("CLOUDINARY_API_KEY", ""),
        cloudinary_api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
    )
    return settings
