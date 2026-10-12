import asyncio
import httpx
import pytest
from scripts.check_deploy import check, origin


@pytest.mark.parametrize('url', ['http://remote.invalid', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?token=secret'])
def test_diagnostic_urls_cannot_contain_credentials_or_path(url):
    with pytest.raises(ValueError): origin(url)


def test_diagnostics_only_read_or_preflight_without_authentication():
    def handler(request):
        assert request.method in {'GET', 'OPTIONS'} and 'authorization' not in request.headers
        headers = {'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'",
                   'Strict-Transport-Security':'max-age=31536000', 'Cache-Control':'no-store'}
        if request.method == 'OPTIONS':
            if request.headers['origin'] == 'https://site.example': headers['Access-Control-Allow-Origin'] = 'https://site.example'
            return httpx.Response(200, headers=headers)
        if request.url.path.endswith('/admin/verify'): return httpx.Response(401, headers=headers)
        if request.url.path.endswith('/health'): data = {'status':'ok'}
        elif request.url.path.endswith('/site-config'): data = {'stripe_mode':'test'}
        else: data = {}
        return httpx.Response(200, json=data, headers=headers)
    result = asyncio.run(check('https://site.example','https://api.example',transport=httpx.MockTransport(handler)))
    assert all(row['passed'] for row in result)
