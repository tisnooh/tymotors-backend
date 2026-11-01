import asyncio

import httpx
import pytest

from app.supabase_rest import SupabaseError, SupabaseRest


@pytest.mark.parametrize(
    'provider_status,provider_body,expected_status',
    [
        (200, {'access_token': 'access-fixture', 'refresh_token': 'refresh-fixture'}, None),
        (400, {'error_code': 'invalid_credentials'}, 401),
        (401, {'message': 'Invalid API key'}, 503),
        (429, {'message': 'rate limited'}, 429),
    ],
)
def test_password_login_distinguishes_credentials_from_invalid_server_key(provider_status, provider_body, expected_status):
    def handler(request):
        assert request.url.path == '/auth/v1/token'
        assert request.url.params['grant_type'] == 'password'
        assert request.headers['apikey'] == 'public-fixture'
        assert request.read() == b'{"email":"owner@example.com","password":"password-fixture"}'
        return httpx.Response(provider_status, json=provider_body)

    db = SupabaseRest('https://example.supabase.co', 'server-fixture', 'public-fixture')
    db._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def check():
        try:
            if expected_status is None:
                assert await db.sign_in_password('owner@example.com', 'password-fixture') == provider_body
            else:
                with pytest.raises(SupabaseError) as caught:
                    await db.sign_in_password('owner@example.com', 'password-fixture')
                assert caught.value.status_code == expected_status
                assert 'Invalid API key' not in caught.value.detail
        finally:
            await db.close()

    asyncio.run(check())
