import asyncio

import httpx
import pytest

from app.supabase_rest import SupabaseError, SupabaseRest


@pytest.mark.parametrize("provider_status,expected_status", [(200, None), (429, 429), (400, 503), (503, 503)])
def test_password_recovery_does_not_report_provider_rejection_as_sent(provider_status, expected_status):
    def handler(request):
        assert request.url.path == "/auth/v1/recover"
        assert request.url.params["redirect_to"] == "https://tymotors.vercel.app/reset-password"
        assert request.read() == b'{"email":"owner@example.com"}'
        return httpx.Response(provider_status, json={"msg": "private provider detail"})

    db = SupabaseRest("https://example.supabase.co", "private_fixture", "public_fixture")
    db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def check():
        try:
            if expected_status is None:
                await db.send_password_recovery("owner@example.com", "https://tymotors.vercel.app/reset-password")
            else:
                with pytest.raises(SupabaseError) as caught:
                    await db.send_password_recovery("owner@example.com", "https://tymotors.vercel.app/reset-password")
                assert caught.value.status_code == expected_status
                assert "private provider detail" not in caught.value.detail
        finally:
            await db.close()

    asyncio.run(check())
