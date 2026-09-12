from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
import re
import smtplib
import ssl
from typing import Any, Callable

import httpx

from app.config import Settings
from app.services.email_templates import EmailContent
from app.supabase_rest import SupabaseError


class EmailService:
    def __init__(self, settings: Settings, db: Any, transport: Callable[[str, EmailContent], str | None] | None = None):
        self.settings = settings
        self.db = db
        self.transport = transport or (self._brevo_send if settings.email_provider == "brevo" else self._smtp_send)

    @staticmethod
    def normalize_email(value: str) -> str:
        email = value.strip().lower()
        if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Invalid email address")
        return email

    async def send(
        self,
        *,
        recipient: str,
        email_type: str,
        content: EmailContent,
        idempotency_key: str,
        user_id: str | None = None,
        order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recipient = self.normalize_email(recipient)
        try:
            rows = await self.db.insert("email_logs", {
                "user_id": user_id,
                "order_id": order_id,
                "recipient": recipient,
                "email_type": email_type,
                "status": "queued",
                "idempotency_key": idempotency_key,
                "metadata": metadata or {},
            })
        except SupabaseError as error:
            if error.status_code == 409:
                return {"status": "duplicate", "sent": False}
            raise

        log_id = rows[0]["id"]
        return await self._deliver(log_id, recipient, content)

    async def retry(self, log_id: str, recipient: str, content: EmailContent) -> dict[str, Any]:
        recipient = self.normalize_email(recipient)
        claimed = await self.db.update("email_logs", {
            "status": "queued", "error_message": None,
        }, params={"id": f"eq.{log_id}", "status": "in.(failed,queued)"})
        if not claimed:
            return {"status": "not_retryable", "sent": False, "log_id": log_id}
        return await self._deliver(log_id, recipient, content)

    async def _deliver(self, log_id: str, recipient: str, content: EmailContent) -> dict[str, Any]:
        if not self.settings.email_enabled:
            await self._mark_failed(log_id, "Email delivery is not configured")
            return {"status": "failed", "sent": False, "log_id": log_id}
        try:
            message_id = await asyncio.to_thread(self.transport, recipient, content)
            await self.db.update("email_logs", {
                "status": "sent", "provider_message_id": message_id,
                "sent_at": datetime.now(timezone.utc).isoformat(), "error_message": None,
            }, params={"id": f"eq.{log_id}", "status": "eq.queued"})
            return {"status": "sent", "sent": True, "log_id": log_id}
        except Exception as error:  # Delivery must never roll back a paid order.
            await self._mark_failed(log_id, f"{type(error).__name__}: email delivery failed")
            return {"status": "failed", "sent": False, "log_id": log_id}

    async def _mark_failed(self, log_id: str, reason: str) -> None:
        await self.db.update("email_logs", {"status": "failed", "error_message": reason[:500]}, params={"id": f"eq.{log_id}"})

    def _smtp_send(self, recipient: str, content: EmailContent) -> str | None:
        message = EmailMessage()
        message["Subject"] = content.subject
        message["From"] = formataddr((self.settings.email_from_name, self.settings.email_from_address))
        message["To"] = recipient
        message["Reply-To"] = self.settings.email_reply_to
        message.set_content(content.text)
        message.add_alternative(content.html, subtype="html")

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if self.settings.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
        return message.get("Message-ID")

    def _brevo_send(self, recipient: str, content: EmailContent) -> str | None:
        response = httpx.post(
            self.settings.brevo_api_url,
            headers={
                "accept": "application/json",
                "api-key": self.settings.brevo_api_key,
                "content-type": "application/json",
            },
            json={
                "sender": {
                    "name": self.settings.email_from_name,
                    "email": self.settings.email_from_address,
                },
                "to": [{"email": recipient}],
                "replyTo": {
                    "name": self.settings.email_from_name,
                    "email": self.settings.email_reply_to,
                },
                "subject": content.subject,
                "htmlContent": content.html,
                "textContent": content.text,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("messageId")
