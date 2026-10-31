from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import re
from urllib.parse import urlsplit
from pydantic import EmailStr, TypeAdapter


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
    email_from_address: str = ""
    email_from_name: str = "TYMotors"
    email_reply_to: str = ""
    email_token_secret: str = ""
    brevo_api_key: str = ""
    brevo_api_url: str = "https://api.brevo.com/v3/smtp/email"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    stripe_mode: str = "test"
    test_catalog_enabled: bool = True
    public_test_checkout_enabled: bool = False
    shipping_countries: tuple[str, ...] = ("FR", "BE", "DE", "ES", "IT", "LU", "NL", "PT")

    @property
    def stripe_test_mode(self) -> bool:
        return self.stripe_mode == "test"

    @property
    def test_catalog_available(self) -> bool:
        # Never opens drafts in live mode, even if the test flag was left enabled.
        return self.stripe_test_mode and self.test_catalog_enabled and self.public_test_checkout_enabled

    def validate(self) -> None:
        project = urlsplit(self.supabase_url)
        if (project.scheme != 'https' or not re.fullmatch(r'[a-z0-9-]+\.supabase\.co', project.hostname or '')
                or project.username or project.password or project.port not in (None, 443)
                or project.path not in ('', '/') or project.query or project.fragment):
            raise RuntimeError("SUPABASE_URL must be a hosted Supabase project URL")
        if not self.supabase_publishable_key:
            raise RuntimeError("SUPABASE_PUBLISHABLE_KEY is required")
        if not self.supabase_service_role_key:
            raise RuntimeError("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is required")
        if self.supabase_publishable_key == self.supabase_service_role_key:
            raise RuntimeError("Publishable and service-role keys must be different")
        if "*" in self.cors_origins:
            raise RuntimeError("CORS_ORIGINS must not contain a wildcard")
        for origin in [self.frontend_url, *self.cors_origins]:
            parsed = urlsplit(origin)
            local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
            if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in ('', '/') or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http'))):
                raise RuntimeError('SITE_URL and CORS_ORIGINS must be HTTPS origins (HTTP allowed only on loopback)')
        if self.cors_origin_regex:
            if not self.cors_origin_regex.startswith('^https://') or not self.cors_origin_regex.endswith('$'):
                raise RuntimeError('CORS_ORIGIN_REGEX must be an anchored HTTPS expression')
            re.compile(self.cors_origin_regex)
        if self.stripe_mode not in {"test", "live"}:
            raise RuntimeError("STRIPE_MODE must be test or live")
        if self.stripe_secret_key and self.stripe_mode == "test" and not self.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
            raise RuntimeError("A live Stripe key cannot be used in test mode")
        if self.stripe_mode == "live" and (self.environment != "production" or not self.stripe_secret_key.startswith(("sk_live_", "rk_live_"))):
            raise RuntimeError("A live Stripe key cannot be used outside production")
        if not self.shipping_countries or any(len(code) != 2 or not code.isalpha() or not code.isupper() for code in self.shipping_countries):
            raise RuntimeError("SHIPPING_COUNTRIES must contain ISO two-letter country codes")
        if self.email_enabled:
            if not all((self.email_from_address, self.email_reply_to, self.email_token_secret)):
                raise RuntimeError("Email delivery is enabled but its common configuration is incomplete")
            if len(self.email_token_secret) < 32:
                raise RuntimeError("EMAIL_TOKEN_SECRET must contain at least 32 characters")
            try:
                for address in (self.email_from_address, self.email_reply_to):
                    TypeAdapter(EmailStr).validate_python(address)
                if any(char in self.email_from_name for char in '\r\n'):
                    raise ValueError('Email header contains a newline')
            except ValueError:
                raise RuntimeError('EMAIL_FROM, EMAIL_REPLY_TO and EMAIL_FROM_NAME must be valid email headers') from None
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
    # Legacy Render setting remains compatible; EMAIL_FROM is the canonical setting.
    sender = (os.getenv('EMAIL_FROM') or os.getenv('EMAIL_FROM_ADDRESS') or '').strip()
    settings = Settings(
        environment=os.getenv("ENVIRONMENT", "test").lower(),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_publishable_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
        supabase_service_role_key=(
            os.getenv("SUPABASE_SECRET_KEY", "")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        ),
        frontend_url=(os.getenv("SITE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/"),
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
        email_from_address=sender,
        email_from_name=os.getenv("EMAIL_FROM_NAME", "TYMotors").strip(),
        email_reply_to=(os.getenv("EMAIL_REPLY_TO") or sender).strip(),
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
        stripe_mode=os.getenv("STRIPE_MODE", "test").strip().lower(),
        test_catalog_enabled=os.getenv("TEST_CATALOG_ENABLED", "true").lower() in {"1", "true", "yes"},
        public_test_checkout_enabled=os.getenv("PUBLIC_TEST_CHECKOUT_ENABLED", "false").lower() in {"1", "true", "yes"},
        shipping_countries=tuple(_csv("SHIPPING_COUNTRIES", "FR,BE,DE,ES,IT,LU,NL,PT")),
    )
    return settings
