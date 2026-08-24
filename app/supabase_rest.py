from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class SupabaseError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SupabaseRest:
    """Small async PostgREST/Auth client used only by the server.

    The secret/service-role key never leaves the backend. Public/user authorization is
    still enforced at the API boundary and in PostgreSQL RLS for direct clients.
    """

    def __init__(self, url: str, service_key: str, publishable_key: str):
        self.url = url.rstrip("/")
        self.service_key = service_key
        self.publishable_key = publishable_key
        self._client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Supabase client is not started")
        return self._client

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            return str(payload.get("message") or payload.get("msg") or payload.get("error_description") or payload.get("error") or "Supabase request failed")
        except Exception:
            return "Supabase request failed"

    async def request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        response = await self.client.request(
            method,
            f"{self.url}/rest/v1/{quote(table, safe='/')}",
            params=params,
            json=json,
            headers=self._headers(prefer=prefer),
        )
        if response.status_code >= 400:
            raise SupabaseError(response.status_code, self._detail(response))
        if not response.content:
            return None
        return response.json()

    async def select(self, table: str, *, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self.request("GET", table, params=params) or []

    async def insert(self, table: str, payload: Any, *, upsert: bool = False, on_conflict: str | None = None) -> list[dict[str, Any]]:
        params = {"on_conflict": on_conflict} if on_conflict else None
        prefer = "return=representation"
        if upsert:
            prefer += ",resolution=merge-duplicates"
        return await self.request("POST", table, params=params, json=payload, prefer=prefer) or []

    async def update(self, table: str, payload: dict[str, Any], *, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.request("PATCH", table, params=params, json=payload, prefer="return=representation") or []

    async def delete(self, table: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.request("DELETE", table, params=params, prefer="return=representation") or []

    async def rpc(self, function: str, payload: dict[str, Any]) -> Any:
        return await self.request("POST", f"rpc/{function}", json=payload)

    async def get_user(self, access_token: str) -> dict[str, Any] | None:
        response = await self.client.get(
            f"{self.url}/auth/v1/user",
            headers={"apikey": self.publishable_key, "Authorization": f"Bearer {access_token}"},
        )
        if response.status_code == 401:
            return None
        if response.status_code >= 400:
            raise SupabaseError(response.status_code, self._detail(response))
        return response.json()
