import asyncio
from pathlib import Path

from app.config import Settings
from app.services.email_service import EmailService
from app.services.email_templates import EmailContent, order_event, welcome
from app.services.email_tokens import new_confirmation_token, sign_token, verify_token
from app.supabase_rest import SupabaseError


def settings(**overrides):
    values = dict(
        environment="test", supabase_url="https://example.supabase.co", supabase_publishable_key="public",
        supabase_service_role_key="secret", frontend_url="http://localhost:3000", cors_origins=["http://localhost:3000"],
        cors_origin_regex=None, stripe_secret_key="", stripe_webhook_secret="", shipping_rate_cents=0,
        free_shipping_threshold_cents=0, cloudinary_url="", cloudinary_cloud_name="", cloudinary_api_key="",
        cloudinary_api_secret="", email_enabled=True, email_provider="smtp",
        email_from_address="test@example.com", email_from_name="TYMotors",
        email_reply_to="test@example.com", email_token_secret="test-secret-that-is-at-least-32-chars", brevo_api_key="",
        brevo_api_url="https://api.brevo.com/v3/smtp/email", smtp_host="smtp.example.com",
        smtp_port=587, smtp_username="test@example.com", smtp_password="app-password", smtp_use_tls=True,
    )
    values.update(overrides)
    return Settings(**values)


class FakeDb:
    def __init__(self, duplicate=False):
        self.duplicate = duplicate
        self.inserted = []
        self.updated = []

    async def insert(self, table, payload, **_kwargs):
        if self.duplicate:
            raise SupabaseError(409, "duplicate")
        self.inserted.append((table, payload))
        return [{"id": "log-1"}]

    async def update(self, table, payload, *, params):
        self.updated.append((table, payload, params))
        return [{"id": "log-1", **payload}]


def test_confirmation_tokens_store_only_a_hash_and_signed_tokens_expire():
    raw, digest = new_confirmation_token()
    assert raw != digest and len(digest) == 64
    token = sign_token("secret", {"purpose": "newsletter_unsubscribe", "subscriber_id": "abc"})
    assert verify_token("secret", token, purpose="newsletter_unsubscribe")["subscriber_id"] == "abc"
    assert verify_token("wrong", token, purpose="newsletter_unsubscribe") is None
    expired = sign_token("secret", {"purpose": "newsletter_unsubscribe"}, ttl_hours=-1)
    assert verify_token("secret", expired, purpose="newsletter_unsubscribe") is None


def test_email_service_is_idempotent_and_records_success():
    db = FakeDb()
    service = EmailService(settings(), db, transport=lambda _recipient, _content: "provider-1")
    result = asyncio.run(service.send(recipient=" Client@Example.com ", email_type="welcome",
        content=EmailContent("Sujet", "<p>Bonjour</p>", "Bonjour"), idempotency_key="welcome:user-1"))
    assert result["status"] == "sent"
    assert db.inserted[0][1]["recipient"] == "client@example.com"
    assert db.updated[-1][1]["provider_message_id"] == "provider-1"

    duplicate = EmailService(settings(), FakeDb(duplicate=True), transport=lambda *_args: "should-not-send")
    assert asyncio.run(duplicate.send(recipient="client@example.com", email_type="welcome",
        content=EmailContent("Sujet", "html", "text"), idempotency_key="welcome:user-1"))["status"] == "duplicate"


def test_enabled_email_configuration_requires_a_strong_token_secret():
    try:
        settings(email_token_secret="short").validate()
        assert False, "validation should reject a weak email token secret"
    except RuntimeError as error:
        assert "32 characters" in str(error)


def test_brevo_configuration_requires_an_api_key():
    try:
        settings(email_provider="brevo", brevo_api_key="").validate()
        assert False, "validation should reject a missing Brevo API key"
    except RuntimeError as error:
        assert "BREVO_API_KEY" in str(error)


def test_brevo_transport_sends_html_and_text(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"messageId": "brevo-message-1"}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("app.services.email_service.httpx.post", fake_post)
    service = EmailService(settings(email_provider="brevo", brevo_api_key="secret-key"), FakeDb())
    message_id = service._brevo_send("client@example.com", EmailContent("Sujet", "<p>Bonjour</p>", "Bonjour"))
    assert message_id == "brevo-message-1"
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"
    assert captured["headers"]["api-key"] == "secret-key"
    assert captured["json"]["htmlContent"] == "<p>Bonjour</p>"
    assert captured["json"]["textContent"] == "Bonjour"


def test_smtp_failure_is_logged_without_being_raised():
    db = FakeDb()
    def fail(*_args):
        raise OSError("private provider detail")
    result = asyncio.run(EmailService(settings(), db, transport=fail).send(recipient="client@example.com",
        email_type="payment_confirmed", content=EmailContent("Sujet", "html", "text"),
        idempotency_key="order:1:paid"))
    assert result["status"] == "failed"
    assert db.updated[-1][1]["error_message"] == "OSError: email delivery failed"


def test_templates_escape_user_and_order_content():
    assert "&lt;script&gt;" in welcome("<script>", "https://example.com/account").html
    content = order_event("order_confirmation", {"order_number": "<bad>", "total_cents": 1000, "currency": "EUR"},
        [{"product_name": "<img onerror=alert(1)>", "quantity": 1, "unit_amount_cents": 1000}], "https://example.com/order")
    assert "<img onerror" not in content.html
    assert "&lt;img onerror" in content.html


def test_email_migration_enables_rls_and_unique_idempotency():
    sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260912165642_complete_email_system.sql").read_text(encoding="utf-8")
    assert "newsletter_subscribers_email_normalized_idx" in sql
    assert "idempotency_key text not null unique" in sql
    assert "alter table public.email_logs enable row level security" in sql
    assert "revoke all on public.newsletter_subscribers" in sql
