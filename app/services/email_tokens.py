from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any


def new_confirmation_token() -> tuple[str, str]:
    """Return a raw URL token and the only value that may be persisted."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_confirmation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sign_token(secret: str, payload: dict[str, Any], *, ttl_hours: int = 24 * 365) -> str:
    if not secret:
        raise RuntimeError("EMAIL_TOKEN_SECRET is not configured")
    body = {**payload, "exp": int((datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp())}
    encoded = urlsafe_b64encode(json.dumps(body, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=")
    signature = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode()}.{urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def verify_token(secret: str, token: str, *, purpose: str) -> dict[str, Any] | None:
    if not secret:
        return None
    try:
        encoded, supplied = token.split(".", 1)
        encoded_bytes = encoded.encode()
        expected = hmac.new(secret.encode(), encoded_bytes, hashlib.sha256).digest()
        signature = urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        if not hmac.compare_digest(expected, signature):
            return None
        payload = json.loads(urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if payload.get("purpose") != purpose or int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
