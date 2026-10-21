"""Supplier inbox MVP: WhatsApp Cloud API + manual Alibaba conversation log.

No autonomous sends. All WhatsApp sends require an authenticated admin approval,
an enabled integration, verified supplier consent and an open 24h service window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
from typing import Any, Callable
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl

from app.supabase_rest import SupabaseError, SupabaseRest


def verify_meta_signature(payload: bytes, header: str | None, secret: str) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def service_window_open(last_inbound: str | None, now: datetime | None = None) -> bool:
    if not last_inbound:
        return False
    try:
        latest = datetime.fromisoformat(last_inbound.replace("Z", "+00:00"))
    except ValueError:
        return False
    if latest.tzinfo is None:
        return False
    now = now or datetime.now(timezone.utc)
    return latest <= now < latest + timedelta(hours=24)


def normalize_phone(number: str) -> str:
    value = re.sub(r"[\s()+.-]", "", number)
    if not re.fullmatch(r"[1-9][0-9]{7,14}", value):
        raise ValueError("Phone must include country code, with 8 to 15 digits")
    return value


class SupplierInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    whatsapp_phone: str
    alibaba_url: HttpUrl | None = None
    whatsapp_opt_in: bool = False
    notes: str = Field(default="", max_length=2000)


class SupplierMessageInput(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    channel: str = Field(default="whatsapp", pattern=r"^(whatsapp|alibaba)$")
    direction: str = Field(default="outbound", pattern=r"^(outbound|inbound)$")


def _admin_supplier(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return rows[0]


def create_supplier_router(db: SupabaseRest, require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter(tags=["Supplier Inbox"])

    @router.get("/whatsapp/webhook", include_in_schema=False)
    async def whatsapp_verify(
        mode: str | None = Query(default=None, alias="hub.mode"),
        token: str | None = Query(default=None, alias="hub.verify_token"),
        challenge: str | None = Query(default=None, alias="hub.challenge"),
    ):
        from fastapi.responses import PlainTextResponse
        secret = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
        if mode != "subscribe" or not secret or not token or not hmac.compare_digest(token, secret):
            raise HTTPException(status_code=403, detail="Webhook verification rejected")
        return PlainTextResponse(challenge or "")

    @router.post("/whatsapp/webhook", include_in_schema=False)
    async def whatsapp_incoming(
        request: Request, signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    ):
        payload = await request.body()
        if len(payload) > 1_000_000:
            raise HTTPException(status_code=413, detail="Webhook payload too large")
        if not verify_meta_signature(payload, signature, os.getenv("WHATSAPP_APP_SECRET", "")):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
        try:
            event = json.loads(payload)
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid webhook JSON")
        for entry in event.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    external_id = message.get("id")
                    sender = message.get("from", "")
                    body = (message.get("text") or {}).get("body", "")
                    if not external_id or not body or len(body) > 4000:
                        continue  # Ignore non-text media in this MVP; do not fabricate content.
                    try:
                        sender = normalize_phone(sender)
                    except ValueError:
                        continue
                    suppliers = await db.select("supplier_contacts", params={
                        "select": "id,last_inbound_at", "whatsapp_phone": f"eq.{sender}", "limit": 1,
                    })
                    if not suppliers:
                        continue  # Never create supplier contacts from unsolicited messages.
                    supplier = suppliers[0]
                    try:
                        timestamp = datetime.fromtimestamp(int(message["timestamp"]), tz=timezone.utc)
                    except (KeyError, ValueError, TypeError, OverflowError, OSError):
                        timestamp = datetime.now(timezone.utc)
                    stamp = timestamp.isoformat()
                    try:
                        await db.insert("supplier_messages", {
                            "supplier_id": supplier["id"], "channel": "whatsapp", "direction": "inbound",
                            "status": "received", "body": body,
                            "external_message_id": external_id, "created_at": stamp,
                        })
                    except SupabaseError as error:
                        if error.status_code != 409:
                            raise
                        continue  # Idempotent webhook replay.
                    previous = supplier.get("last_inbound_at")
                    if not previous or datetime.fromisoformat(previous.replace("Z", "+00:00")) < timestamp:
                        await db.update("supplier_contacts", {"last_inbound_at": stamp}, params={
                            "id": f"eq.{supplier['id']}",
                            "or": f"(last_inbound_at.is.null,last_inbound_at.lt.{stamp})",
                        })
        return {"received": True}

    @router.get("/admin/suppliers")
    async def list_suppliers(admin: dict = Depends(require_admin)):
        rows = await db.select("supplier_contacts", params={"select": "*", "order": "created_at.desc", "limit": 100})
        return {"items": rows}

    @router.post("/admin/suppliers", status_code=201)
    async def create_supplier(payload: SupplierInput, admin: dict = Depends(require_admin)):
        try:
            phone = normalize_phone(payload.whatsapp_phone)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error))
        rows = await db.insert("supplier_contacts", {
            "name": payload.name.strip(), "whatsapp_phone": phone,
            "alibaba_url": str(payload.alibaba_url) if payload.alibaba_url else None,
            "whatsapp_opt_in": payload.whatsapp_opt_in, "notes": payload.notes,
        })
        return rows[0]

    @router.get("/admin/suppliers/{supplier_id}/messages")
    async def messages(supplier_id: UUID, admin: dict = Depends(require_admin)):
        await _get_supplier(supplier_id)
        rows = await db.select("supplier_messages", params={
            "select": "*", "supplier_id": f"eq.{supplier_id}",
            "order": "created_at.desc", "limit": 100,
        })
        return {"items": rows}

    async def _get_supplier(supplier_id: UUID) -> dict[str, Any]:
        return _admin_supplier(await db.select("supplier_contacts", params={
            "select": "*", "id": f"eq.{supplier_id}", "limit": 1,
        }))

    @router.post("/admin/suppliers/{supplier_id}/messages", status_code=201)
    async def create_draft(supplier_id: UUID, payload: SupplierMessageInput, admin: dict = Depends(require_admin)):
        await _get_supplier(supplier_id)
        # Alibaba is manual-only: importing a conversation is a record, never an API send.
        if payload.channel == "whatsapp" and payload.direction != "outbound":
            raise HTTPException(status_code=422, detail="Incoming WhatsApp messages must come from signed webhook")
        status = "draft" if payload.direction == "outbound" else "received"
        rows = await db.insert("supplier_messages", {
            "supplier_id": str(supplier_id), "channel": payload.channel, "direction": payload.direction,
            "status": status, "body": payload.body,
        })
        return rows[0]

    @router.post("/admin/supplier-messages/{message_id}/approve-send")
    async def approve_send(message_id: UUID, admin: dict = Depends(require_admin)):
        if os.getenv("WHATSAPP_OUTBOUND_ENABLED", "false").lower() != "true":
            raise HTTPException(status_code=503, detail="WhatsApp outbound is disabled")
        token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v24.0")
        if not token or not number_id or not re.fullmatch(r"v[0-9]+\\.[0-9]+", api_version):
            raise HTTPException(status_code=503, detail="WhatsApp connection is incomplete")
        rows = await db.select("supplier_messages", params={
            "select": "*", "id": f"eq.{message_id}", "status": "eq.draft",
            "channel": "eq.whatsapp", "direction": "eq.outbound", "limit": 1,
        })
        if not rows:
            raise HTTPException(status_code=409, detail="WhatsApp draft not found or already processed")
        draft = rows[0]
        supplier = await _get_supplier(UUID(draft["supplier_id"]))
        if not supplier.get("whatsapp_opt_in"):
            raise HTTPException(status_code=409, detail="Supplier permission must be recorded first")
        if not service_window_open(supplier.get("last_inbound_at")):
            raise HTTPException(status_code=409, detail="No open 24h service window; use a separately approved template")
        # Single-use compare-and-set prevents two admins submitting the same draft twice.
        claimed = await db.update("supplier_messages", {"status": "sending"}, params={
            "id": f"eq.{message_id}", "status": "eq.draft",
        })
        if not claimed:
            raise HTTPException(status_code=409, detail="Already processed")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"https://graph.facebook.com/{api_version}/{number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"messaging_product": "whatsapp", "to": supplier["whatsapp_phone"],
                          "type": "text", "text": {"body": draft["body"], "preview_url": False}},
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Meta API returned HTTP {response.status_code}")
            payload = response.json()
            external_id = (payload.get("messages") or [{}])[0].get("id")
            if not external_id:
                raise RuntimeError("Meta API did not return message id")
        except (httpx.RequestError, RuntimeError, ValueError):
            # Timeout can mean a send actually happened. Never auto-retry an ambiguous send.
            await db.update("supplier_messages", {"status": "failed", "error_code": "manual_review_required"}, params={
                "id": f"eq.{message_id}", "status": "eq.sending",
            })
            raise HTTPException(status_code=502, detail="Send was not confirmed. Check WhatsApp before retrying")
        await db.update("supplier_messages", {"status": "sent", "external_message_id": external_id,
            "sent_at": datetime.now(timezone.utc).isoformat()}, params={"id": f"eq.{message_id}", "status": "eq.sending"})
        return {"status": "sent", "message_id": str(message_id), "external_message_id": external_id}

    return router
