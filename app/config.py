from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


def _csv(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


def _email_provider() -> str:
    configured = (os.getenv("EMAIL_PROVIDER") or "").strip().lower()
    # Render's free tier blocks SMTP. A configured Brevo key is therefore the
    # strongest signal that the HTTPS transport must be used, even when a
    # stale EMAIL_PROVIDER=smtp value remains in the service environment.
    if (os.getenv("BREVO_API_KEY") or "").strip():
        return "brevo"
    return configured or "brevo"


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
    email_enabled: bool = False
    email_provider: str = "brevo"
    email_from_address: str = "tyachatfr@gmail.com"
    email_from_name: str = "TYMotors"
    email_reply_to: str = "tyachatfr@gmail.com"
    email_token_secret: str = ""
    brevo_api_key: str = ""
    brevo_api_url: str = "https://api.brevo.com/v3/smtp/email"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

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
        if self.email_enabled:
            if not all((self.email_from_address, self.email_reply_to, self.email_token_secret)):
                raise RuntimeError("Email delivery is enabled but its common configuration is incomplete")
            if len(self.email_token_secret) < 32:
                raise RuntimeError("EMAIL_TOKEN_SECRET must contain at least 32 characters")
            if self.email_provider == "brevo":
                if not self.brevo_api_key:
                    raise RuntimeError("BREVO_API_KEY is required when EMAIL_PROVIDER=brevo")
                if self.brevo_api_url != "https://api.brevo.com/v3/smtp/email":
                    raise RuntimeError("BREVO_API_URL must use Brevo's HTTPS transactional endpoint")
            elif self.email_provider == "smtp":
                if not all((self.smtp_host, self.smtp_username, self.smtp_password)):
                    raise RuntimeError("SMTP email delivery is enabled but its configuration is incomplete")
                if not 1 <= self.smtp_port <= 65535:
                    raise RuntimeError("SMTP_PORT must be between 1 and 65535")
                if self.smtp_host.casefold() == "smtp.gmail.com" and not self.smtp_use_tls:
                    raise RuntimeError("Gmail SMTP requires TLS")
            else:
                raise RuntimeError("EMAIL_PROVIDER must be either smtp or brevo")


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
        email_enabled=os.getenv("EMAIL_ENABLED", "false").lower() in {"1", "true", "yes"},
        email_provider=_email_provider(),
        email_from_address=os.getenv("EMAIL_FROM_ADDRESS", "tyachatfr@gmail.com").strip(),
        email_from_name=os.getenv("EMAIL_FROM_NAME", "TYMotors").strip(),
        email_reply_to=os.getenv("EMAIL_REPLY_TO", "tyachatfr@gmail.com").strip(),
        email_token_secret=os.getenv("EMAIL_TOKEN_SECRET", ""),
        brevo_api_key=os.getenv("BREVO_API_KEY", ""),
        # Pin the provider endpoint so a stale or mistyped environment value
        # cannot redirect credentials or prevent the service from starting.
        brevo_api_url="https://api.brevo.com/v3/smtp/email",
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"},
    )
    return settings
