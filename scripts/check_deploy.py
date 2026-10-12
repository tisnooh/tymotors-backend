"""Non-mutating HTTP release checks. No keys, login, email or payment requests."""
import asyncio
import json
import os
from urllib.parse import urlsplit
import httpx


def origin(value):
    parsed = urlsplit(value)
    loopback = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise ValueError('Use a plain origin without credentials, path or query')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback):
        raise ValueError('HTTPS is required except localhost')
    return value.rstrip('/')


async def check(frontend, backend, *, transport=None):
    frontend, backend = origin(frontend), origin(backend)
    results = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False, transport=transport) as client:
        async def request(method, url, **kwargs):
            try: return await client.request(method, url, **kwargs)
            except httpx.HTTPError: return None
        front, health, config, admin, cors, untrusted = await asyncio.gather(
            request('GET', frontend), request('GET', backend+'/api/health'),
            request('GET', backend+'/api/site-config'), request('GET', backend+'/api/admin/verify'),
            request('OPTIONS', backend+'/api/create-checkout-session', headers={'Origin': frontend,
                    'Access-Control-Request-Method':'POST', 'Access-Control-Request-Headers':'Content-Type,X-Session-Id'}),
            request('OPTIONS', backend+'/api/create-checkout-session', headers={'Origin': 'https://untrusted.invalid',
                    'Access-Control-Request-Method':'POST'}))
        def add(name, passed): results.append({'check': name, 'passed': bool(passed)})
        def payload(response):
            try: return response.json() if response is not None else {}
            except ValueError: return {}
        add('frontend_http_200', front is not None and front.status_code == 200)
        add('database_health_200', health is not None and health.status_code == 200 and payload(health) == {'status':'ok'})
        data = payload(config)
        add('stripe_test_mode', config is not None and config.status_code == 200 and data.get('stripe_mode') == 'test')
        add('admin_refused_without_auth', admin is not None and admin.status_code == 401)
        add('cors_exact_site_origin', cors is not None and cors.status_code == 200 and cors.headers.get('access-control-allow-origin') == frontend)
        add('cors_untrusted_origin_refused', untrusted is not None and not untrusted.headers.get('access-control-allow-origin'))
        for label, response, url in [('frontend', front, frontend), ('api', health, backend)]:
            headers = response.headers if response is not None else {}
            add(label+'_nosniff', headers.get('x-content-type-options') == 'nosniff')
            add(label+'_frame_denied', headers.get('x-frame-options') == 'DENY')
            add(label+'_csp_present', bool(headers.get('content-security-policy')))
            if url.startswith('https://'): add(label+'_hsts_present', 'max-age=' in headers.get('strict-transport-security',''))
        add('private_response_not_cached', admin is not None and admin.headers.get('cache-control') == 'no-store')
    return results


def main():
    frontend, backend = os.getenv('SITE_URL', ''), os.getenv('CHECK_BACKEND_URL', '')
    if not frontend or not backend:
        print('SITE_URL and CHECK_BACKEND_URL are required; no default hosted domain.')
        return 1
    try: results = asyncio.run(check(frontend, backend))
    except (ValueError, OSError):
        print('Invalid URL or unavailable HTTP check; no credentials/provider errors printed.')
        return 1
    print(json.dumps({'checks': results, 'result': 'passed' if all(r['passed'] for r in results) else 'failed'}))
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__': raise SystemExit(main())
