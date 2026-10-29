"""Real installed Stripe SDK + intercepted HTTP only: NOT a Stripe sandbox E2E.

Every key, account, session and provider response below is synthetic. The mock
transport cannot reach Stripe or charge anything, including production cases.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from urllib.parse import parse_qs

import httpx
import pytest
import stripe

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_checkout_params import build_checkout_params
from app.commerce_stripe_gateway import AuthenticatedStripeGateway, StripeGatewayError
from tests.test_commerce_checkout_params import snapshot  # noqa: F401


ACCOUNT = 'acct_SyntheticMerchant'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def context(mode='sandbox'):
    return CheckoutServerContext(mode, ACCOUNT)


def credential(mode='sandbox', prefix='rk'):
    # Construct a deliberately fake fixture, not a usable credential.
    return '_'.join((prefix, 'test' if mode == 'sandbox' else 'live', 'synthetic_not_a_credential'))


def session(mode='sandbox', **updates):
    result = {'id': ('cs_test_' if mode == 'sandbox' else 'cs_live_') + 'SyntheticSession',
              'object': 'checkout.session', 'mode': 'payment', 'livemode': mode == 'production',
              'status': 'open', 'payment_status': 'unpaid'}
    result.update(updates)
    return result


@asynccontextmanager
async def gateway(handler, *, mode='sandbox', key=None):
    transport = stripe.HTTPXClient(timeout=1)
    await transport._client_async.aclose()
    transport._client_async = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield AuthenticatedStripeGateway(key or credential(mode), context(mode), http_client=transport)
    finally:
        await transport.close_async()


@pytest.mark.parametrize('value', [None, {}, {'mode': 'sandbox', 'stripe_account_id': ACCOUNT},
                                 CheckoutServerContext('test', ACCOUNT),
                                 CheckoutServerContext('production', 'acct_'),
                                 CheckoutServerContext('sandbox', None)])
def test_invalid_server_context_before_any_sdk(value, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('SDK must not be constructed')
    monkeypatch.setattr(stripe, 'StripeClient', forbidden)
    with pytest.raises(StripeGatewayError, match='stripe_server_context_required'):
        AuthenticatedStripeGateway(credential(), value)


@pytest.mark.parametrize('mode,key', [
    ('sandbox', credential('production')), ('production', credential()),
    ('production', credential('production', 'rkcs')), ('production', ''),
    ('sandbox', 'random'), ('sandbox', 'rk_test_'), ('production', None),
    ('sandbox', credential() + '\n'), ('sandbox', credential() + 'é'),
])
def test_mismatched_keys_rejected_before_any_sdk(mode, key, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('SDK must not be constructed')
    monkeypatch.setattr(stripe, 'StripeClient', forbidden)
    with pytest.raises(StripeGatewayError, match='stripe_credentials_mode_mismatch'):
        AuthenticatedStripeGateway(key, context(mode))


@pytest.mark.anyio
@pytest.mark.parametrize('mode,prefix', [('sandbox', 'rk'), ('sandbox', 'sk'), ('sandbox', 'rkcs'),
                                        ('production', 'rk'), ('production', 'sk')])
async def test_real_sdk_authenticates_current_account_and_exact_frozen_post(snapshot, mode, prefix):
    requests = []
    params = build_checkout_params(**snapshot)
    before = deepcopy(params)
    def handler(request):
        requests.append(request)
        assert request.url.host == 'api.stripe.com'
        assert 'Stripe-Account' not in request.headers and 'Stripe-Context' not in request.headers
        assert request.headers['Authorization'] == 'Bearer ' + credential(mode, prefix)
        if request.method == 'GET' and request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT,
                                           'charges_enabled': True})
        assert request.method == 'POST' and request.url.path == '/v1/checkout/sessions'
        assert request.headers['Idempotency-Key'] == 'persisted:key:unchanged'
        form = parse_qs(request.content.decode())
        assert form['mode'] == ['payment']
        assert form['metadata[order_id]'] == [params['metadata']['order_id']]
        assert form['line_items[0][price_data][unit_amount]'] == ['5000']
        assert not any('transfer' in key or 'on_behalf_of' in key for key in form)
        return httpx.Response(200, json=session(mode))
    async with gateway(handler, mode=mode, key=credential(mode, prefix)) as adapter:
        assert await adapter.create(params, 'persisted:key:unchanged') == session(mode)
        assert adapter.server_context == context(mode)
    assert [(r.method, r.url.path) for r in requests] == [
        ('GET', '/v1/account'), ('POST', '/v1/checkout/sessions')]
    assert params == before


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['sandbox', 'production'])
async def test_mismatched_authenticated_account_never_creates(snapshot, mode):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'object': 'account', 'id': 'acct_OtherMerchant',
                                       'charges_enabled': True,
                                       'metadata': {'account': ACCOUNT}})
    async with gateway(handler, mode=mode) as adapter:
        with pytest.raises(StripeGatewayError, match='stripe_account_mismatch') as raised:
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
        assert raised.value.provider_request_started is False
    assert len(requests) == 1 and requests[0].url.path == '/v1/account'


@pytest.mark.anyio
@pytest.mark.parametrize('enabled', [False, None, 1, 'true', [], {}])
async def test_new_production_creation_requires_strict_charges_enabled(snapshot, enabled):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT,
                                       'charges_enabled': enabled})
    async with gateway(handler, mode='production') as adapter:
        with pytest.raises(StripeGatewayError, match='stripe_account_charges_unavailable'):
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
    assert len(requests) == 1


@pytest.mark.anyio
async def test_account_livemode_is_not_invented_or_trusted():
    def handler(request):
        return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT,
                                       'charges_enabled': True, 'livemode': False})
    async with gateway(handler, mode='production') as adapter:
        assert await adapter.authenticate(for_create=True) == context('production')


@pytest.mark.anyio
@pytest.mark.parametrize('status', [401, 403, 429, 500])
async def test_authentication_error_is_sanitized_with_no_post_or_retry(snapshot, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': {'message': 'PRIVATE_ERROR_CONTENT',
                                                    'type': 'api_error'}})
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError) as raised:
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
        assert str(raised.value) == 'stripe_account_authentication_failed'
        assert raised.value.provider_request_started is False
        assert raised.value.__suppress_context__ is True
    assert len(requests) == 1 and requests[0].method == 'GET'


@pytest.mark.anyio
@pytest.mark.parametrize('failure', ['timeout', '500', '409'])
async def test_ambiguous_creation_never_retries_or_rotates_key(snapshot, failure):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        assert request.headers['Idempotency-Key'] == 'persisted-key'
        if failure == 'timeout':
            raise httpx.ReadTimeout('PRIVATE_ERROR_CONTENT', request=request)
        return httpx.Response(int(failure), json={'error': {'type': 'api_error',
                                                          'message': 'PRIVATE_ERROR_CONTENT'}})
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError) as raised:
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
        assert str(raised.value) == 'stripe_creation_requires_inspection'
        assert raised.value.provider_request_started is True
    assert [r.method for r in requests] == ['GET', 'POST']


@pytest.mark.anyio
@pytest.mark.parametrize('change', [
    {'livemode': True}, {'livemode': None}, {'livemode': 0}, {'id': 'cs_live_Other'},
    {'id': 'cs_test_'}, {'object': 'account'}, {'mode': 'subscription'},
])
async def test_invalid_creation_response_requires_review(snapshot, change):
    def handler(request):
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        return httpx.Response(200, json=session(**change))
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError, match='stripe_session_response_requires_review') as raised:
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
        assert raised.value.provider_request_started is True


@pytest.mark.anyio
async def test_read_existing_live_session_is_allowed_after_charges_disabled():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT, 'charges_enabled': False})
        return httpx.Response(200, json=session('production'))
    async with gateway(handler, mode='production') as adapter:
        assert await adapter.retrieve('cs_live_SyntheticSession') == session('production')
    assert [(r.method, r.url.path) for r in requests] == [
        ('GET', '/v1/account'), ('GET', '/v1/checkout/sessions/cs_live_SyntheticSession')]


@pytest.mark.anyio
@pytest.mark.parametrize('mode,bad_id', [('sandbox', 'cs_live_SyntheticSession'),
                                        ('production', 'cs_test_SyntheticSession'),
                                        ('production', 'cs_live_a/b'), ('sandbox', None)])
async def test_wrong_session_id_refused_before_network(mode, bad_id):
    def forbidden(request):
        raise AssertionError('No network expected')
    async with gateway(forbidden, mode=mode) as adapter:
        with pytest.raises(StripeGatewayError, match='stripe_session_mode_mismatch'):
            await adapter.retrieve(bad_id)


@pytest.mark.anyio
async def test_retrieve_identity_cannot_be_substituted():
    def handler(request):
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        return httpx.Response(200, json=session(id='cs_test_DifferentSession'))
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError, match='stripe_session_response_requires_review'):
            await adapter.retrieve('cs_test_SyntheticSession')


@pytest.mark.anyio
async def test_account_is_rechecked_on_every_operation(snapshot):
    auth_count = 0
    requests = []
    def handler(request):
        nonlocal auth_count
        requests.append(request)
        if request.url.path == '/v1/account':
            auth_count += 1
            return httpx.Response(200, json={'object': 'account',
                'id': ACCOUNT if auth_count == 1 else 'acct_ChangedMerchant'})
        return httpx.Response(200, json=session())
    async with gateway(handler) as adapter:
        await adapter.authenticate()
        with pytest.raises(StripeGatewayError, match='stripe_account_mismatch'):
            await adapter.create(build_checkout_params(**snapshot), 'same-key')
    assert len(requests) == 2 and all(r.method == 'GET' for r in requests)


@pytest.mark.anyio
@pytest.mark.parametrize('key', [None, '', 1, 'a' * 256, 'key with spaces', 'key\n', 'clé'])
async def test_invalid_persisted_key_before_network(snapshot, key):
    def forbidden(request):
        raise AssertionError('No network expected')
    async with gateway(forbidden) as adapter:
        with pytest.raises(StripeGatewayError, match='invalid_stripe_idempotency_key'):
            await adapter.create(build_checkout_params(**snapshot), key)


@pytest.mark.anyio
@pytest.mark.parametrize('injection', [
    {'api_key': 'never'}, {'stripe_account': 'acct_Other'}, {'payment_method_types': ['card']},
    {'payment_intent_data': {'metadata': {}, 'transfer_data': {'destination': 'acct_Other'}}},
    {'payment_intent_data': {'metadata': {}, 'on_behalf_of': 'acct_Other'}},
    {'payment_intent_data': {'metadata': {}, 'application_fee_amount': 100}},
    {'payment_intent_data': None}, {'mode': 'subscription'},
])
async def test_delegation_or_sdk_param_injection_before_network(snapshot, injection):
    def forbidden(request):
        raise AssertionError('No network expected')
    params = {**build_checkout_params(**snapshot), **injection}
    async with gateway(forbidden) as adapter:
        with pytest.raises(StripeGatewayError, match='invalid_stripe_checkout_params'):
            await adapter.create(params, 'persisted-key')


@pytest.mark.anyio
async def test_input_frozen_before_authentication_await(snapshot):
    params = build_checkout_params(**snapshot)
    order_id = params['metadata']['order_id']
    def handler(request):
        if request.url.path == '/v1/account':
            params['metadata']['order_id'] = 'MUTATED_WHILE_AUTHENTICATING'
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        form = parse_qs(request.content.decode())
        assert form['metadata[order_id]'] == [order_id]
        return httpx.Response(200, json=session())
    async with gateway(handler) as adapter:
        await adapter.create(params, 'persisted-key')


@pytest.mark.anyio
async def test_explicit_same_key_calls_do_not_generate_or_change_idempotency(snapshot):
    """Caller/DB must limit POSTs; adapter preserves the key if called again."""
    posts = []
    def handler(request):
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        posts.append((request.headers['Idempotency-Key'], request.content))
        return httpx.Response(200, json=session())
    async with gateway(handler) as adapter:
        first = await adapter.create(build_checkout_params(**snapshot), 'same-persisted-key')
        second = await adapter.create(build_checkout_params(**snapshot), 'same-persisted-key')
    assert first == second
    assert len(posts) == 2 and posts[0] == posts[1]


@pytest.mark.anyio
@pytest.mark.parametrize('scope', [None, 0, 1, 'true', [], {}])
async def test_non_boolean_authentication_scope_refused_before_network(scope):
    def forbidden(request):
        raise AssertionError('No network expected')
    async with gateway(forbidden) as adapter:
        with pytest.raises(StripeGatewayError, match='invalid_stripe_authentication_scope'):
            await adapter.authenticate(for_create=scope)


@pytest.mark.anyio
@pytest.mark.parametrize('response', [[], None, {'id': ACCOUNT},
                                      {'object': 'customer', 'id': ACCOUNT}])
async def test_malformed_account_response_before_creation(snapshot, response):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError) as raised:
            await adapter.create(build_checkout_params(**snapshot), 'persisted-key')
        assert raised.value.code in {'stripe_account_authentication_failed', 'stripe_account_mismatch'}
        assert raised.value.provider_request_started is False
    assert len(requests) == 1 and requests[0].method == 'GET'


@pytest.mark.anyio
async def test_retrieve_errors_are_sanitized_and_never_create():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == '/v1/account':
            return httpx.Response(200, json={'object': 'account', 'id': ACCOUNT})
        return httpx.Response(403, json={'error': {'type': 'api_error', 'message': 'PRIVATE_READ_ERROR'}})
    async with gateway(handler) as adapter:
        with pytest.raises(StripeGatewayError) as raised:
            await adapter.retrieve('cs_test_SyntheticSession')
        assert str(raised.value) == 'stripe_session_read_failed'
    assert [r.method for r in requests] == ['GET', 'GET']
