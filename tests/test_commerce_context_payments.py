"""Service tests with in-memory RPC responses and patched provider operations.

These execute the actual Python service, not PostgreSQL/Stripe or signed HTTP.
They do not certify a commercially approved product, live account or shipment.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_context_payments import (
    ContextCheckoutPayments, ContextCustomerCheckout, hosted_context_url,
)
from app.commerce_customer_checkout import CustomerCheckoutError
from app.commerce_stripe_gateway import AuthenticatedStripeGateway
from app.commerce_webhook_profiles import StripeWebhookProfile
from app.supabase_rest import SupabaseError
from tests.test_commerce_checkout_params import snapshot  # noqa: F401


ACCOUNT = 'acct_SyntheticContextMerchant'
GUEST = 'synthetic_context_checkout_guest'
USER = '10000000-0000-4000-8000-000000000011'
AUTH_SESSION = '10000000-0000-4000-8000-000000000012'
OWNER = {'p_user_id': None, 'p_guest_session': GUEST, 'p_auth_session_id': None}
ORIGIN = 'https://shop.example.com'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def wired(snapshot, request):
    mode = getattr(request, 'param', 'production')
    c = deepcopy(snapshot)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=40)
    is_test = mode == 'sandbox'
    profile = StripeWebhookProfile('merchant-' + mode, CheckoutServerContext(mode, ACCOUNT),
                                  'whsec_synthetic_context_fixture')
    c['profile'] = profile
    c['owner'] = dict(OWNER)
    c['cart'] = {'id': str(uuid4()), 'user_id': None, 'guest_session_id': GUEST}
    # quote_expires_at is an enrichment returned by the preparation transaction,
    # NOT an orders column and must not spoil comparison with the actual row.
    c['order'].pop('quote_expires_at')
    c['order'].update(cart_id=c['cart']['id'], user_id=None, guest_session_id=GUEST,
        order_number='TY-CONTEXT-SYNTHETIC', refunded_amount_cents=0, is_test=is_test,
        stripe_account_id=ACCOUNT, stripe_profile_ref=profile.reference)
    c['attempt'].update(state='drafting', is_test=is_test, stripe_account_id=ACCOUNT,
        stripe_profile_ref=profile.reference, params=None, first_requested_at=None, session_id=None,
        idempotency_key='context-persisted-key', expires_at=int(deadline.timestamp()),
        quote_expires_at=deadline.isoformat())
    c['quote'] = {'id': c['order']['commerce_quote_id'], 'cart_id': c['cart']['id'],
        'owner_user_id': None, 'owner_guest_session': GUEST,
        'expires_at': deadline.isoformat(), 'mode': mode}
    sid = ('cs_test_' if is_test else 'cs_live_') + 'ContextSyntheticSession'
    c['session'] = {'id': sid, 'object': 'checkout.session', 'mode': 'payment', 'livemode': not is_test,
        'metadata': {'order_id': c['order']['id'], 'quote_id': c['quote']['id'],
                     'attempt_id': c['attempt']['id']},
        'client_reference_id': c['order']['id'], 'expires_at': int(deadline.timestamp()),
        'currency': 'eur', 'amount_total': 10500, 'amount_subtotal': 10000,
        'total_details': {'amount_discount': 0, 'amount_shipping': 500, 'amount_tax': 0},
        'automatic_tax': {'enabled': False}, 'discounts': [], 'status': 'open', 'payment_status': 'unpaid',
        'payment_intent': None, 'url': 'https://checkout.stripe.com/c/pay/' + sid + '#synthetic',
        'shipping_details': {'address': deepcopy(c['order']['shipping_address'])}}

    async def select(table, *, params=None):
        if table == 'commerce_quotes':
            return [] if c['quote'] is None else [deepcopy(c['quote'])]
        if table == 'carts':
            return deepcopy(c.get('cart_rows', [c['cart']]))
        if table == 'orders':
            return deepcopy(c.get('order_rows', [c['order']]))
        if table == 'commerce_checkout_attempts':
            return deepcopy(c.get('attempt_rows', [c['attempt']]))
        raise AssertionError(table)

    async def rpc(name, payload):
        if name == 'is_auth_session_active':
            return c.get('auth_active', True)
        assert payload.get('p_stripe_account_id') == ACCOUNT
        assert payload.get('p_profile_ref') == profile.reference
        if name in ('commerce_prepare_context_checkout', 'commerce_store_context_checkout_params',
                    'commerce_claim_context_checkout', 'commerce_context_checkout_unknown'):
            assert {key: payload[key] for key in OWNER} == c['owner']
            assert 'p_actor' not in payload
        if name == 'commerce_prepare_context_checkout':
            assert payload['p_quote_id'] == c['order']['commerce_quote_id']
            assert payload['p_frontend_origin'] == ORIGIN
            assert payload['p_is_test'] is is_test
            result = {'attempt': deepcopy(c['attempt']),
                'order': {**deepcopy(c['order']), 'quote_expires_at': c['quote']['expires_at']},
                'items': deepcopy(c['items'])}
            if 'prepare_change' in c:
                c['prepare_change'](result)
            return result
        if name == 'commerce_store_context_checkout_params':
            c['attempt'].update(state='ready', params=deepcopy(payload['p_params']))
            return deepcopy(c['attempt'])
        if name == 'commerce_claim_context_checkout':
            if c['attempt']['state'] != 'ready':
                raise SupabaseError(409, 'PRIVATE durable claim conflict')
            c['attempt'].update(state='creating', first_requested_at=datetime.now(timezone.utc).isoformat())
            result = deepcopy(c['attempt'])
            if 'claim_change' in c:
                c['claim_change'](result)
            return result
        if name == 'commerce_bind_context_session':
            assert c['attempt']['session_id'] is None
            # DB preserves the claimed/unknown lifecycle; binding is not paid
            # truth and does not manufacture a terminal attempt state.
            c['attempt'].update(session_id=payload['p_session_id'])
            return deepcopy(c['attempt'])
        if name == 'commerce_context_checkout_unknown':
            if c.get('unknown_write_fails'):
                raise SupabaseError(503, 'PRIVATE unavailable')
            c['attempt']['state'] = 'unknown'
            return deepcopy(c['attempt'])
        if name == 'commerce_settle_context_checkout':
            c['settled_payload'] = deepcopy(payload)
            return {'received': True, 'is_test': is_test,
                    'held': payload['p_destination_matches'] is not True}
        if name in ('commerce_record_context_event', 'commerce_record_context_refund'):
            c['receipt_payload'] = deepcopy(payload)
            return {'received': True, 'requires_reconciliation': True, 'is_test': is_test}
        raise AssertionError(name)

    db = SimpleNamespace(select=AsyncMock(side_effect=select), rpc=AsyncMock(side_effect=rpc))
    gateway = AuthenticatedStripeGateway('_'.join(('rk', 'test' if is_test else 'live',
        'synthetic_not_a_credential')), profile.context)
    gateway.authenticate = AsyncMock(return_value=profile.context)
    gateway.create = AsyncMock(side_effect=lambda *_: deepcopy(c['session']))
    gateway.retrieve = AsyncMock(side_effect=lambda *_: deepcopy(c['session']))
    return c, db, gateway, ContextCustomerCheckout(db, profile)


async def start(wired, **changes):
    c, _, gateway, service = wired
    user = {'id': USER} if c['owner']['p_user_id'] is not None else None
    args = {'quote_id': c['order']['commerce_quote_id'], 'request_key': str(uuid4()),
        'cart': deepcopy(c['cart']), 'user': user,
        'guest_session': c['owner']['p_guest_session'], 'owner': deepcopy(c['owner']),
        'gateway': gateway, 'origin': ORIGIN, 'allowed_countries': ('FR',)}
    return await service.start(**{**args, **changes})


def rpc_names(db):
    return [call.args[0] for call in db.rpc.await_args_list]


@pytest.mark.anyio
@pytest.mark.parametrize('wired', ['sandbox', 'production'], indirect=True)
async def test_full_context_service_prepares_claims_binds_and_reads_exact_session(wired):
    c, db, gateway, _ = wired
    result = await start(wired)
    assert result == {'order_id': c['order']['id'], 'order_number': 'TY-CONTEXT-SYNTHETIC',
        'quote_id': c['quote']['id'], 'session_id': c['session']['id'],
        'is_test': c['order']['is_test'], 'status': 'open', 'url': c['session']['url']}
    assert rpc_names(db) == ['commerce_prepare_context_checkout', 'commerce_store_context_checkout_params',
        'commerce_claim_context_checkout', 'commerce_bind_context_session']
    gateway.authenticate.assert_awaited_once_with(for_create=True)
    gateway.create.assert_awaited_once_with(c['attempt']['params'], 'context-persisted-key')
    gateway.retrieve.assert_awaited_once_with(c['session']['id'])
    assert c['order']['payment_status'] == 'unpaid'
    assert not any('settle' in name or 'refund' in name or 'supplier' in name for name in rpc_names(db))


@pytest.mark.anyio
async def test_repeat_http_token_does_not_claim_or_create_another_session(wired):
    _, db, gateway, _ = wired
    first = await start(wired)
    second = await start(wired)
    assert first == second
    gateway.create.assert_awaited_once()
    assert gateway.retrieve.await_count == 2
    assert rpc_names(db).count('commerce_claim_context_checkout') == 1


@pytest.mark.anyio
@pytest.mark.parametrize('state', ['creating', 'unknown', 'cancelled'])
async def test_unbound_nonready_attempt_never_recreated(wired, state):
    c, db, gateway, _ = wired
    c['attempt']['state'] = state
    with pytest.raises(ValueError):
        await start(wired)
    gateway.authenticate.assert_not_awaited()
    gateway.create.assert_not_awaited()
    gateway.retrieve.assert_not_awaited()
    assert 'commerce_claim_context_checkout' not in rpc_names(db)


@pytest.mark.anyio
async def test_timeout_preserves_unknown_key_and_prohibits_second_post(wired):
    c, db, gateway, _ = wired
    gateway.create.side_effect = TimeoutError('PRIVATE provider timeout')
    with pytest.raises(Exception):
        await start(wired)
    assert c['attempt']['state'] == 'unknown'
    assert c['attempt']['idempotency_key'] == 'context-persisted-key'
    assert rpc_names(db)[-1] == 'commerce_context_checkout_unknown'
    assert not any('cancel' in name for name in rpc_names(db))
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
async def test_unknown_write_failure_retains_creating_no_new_post(wired):
    c, _, gateway, _ = wired
    c['unknown_write_fails'] = True
    gateway.create.side_effect = TimeoutError('PRIVATE response lost')
    with pytest.raises(Exception):
        await start(wired)
    assert c['attempt']['state'] == 'creating'
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
async def test_authentication_failure_precedes_claim_and_creation(wired):
    _, db, gateway, _ = wired
    gateway.authenticate.side_effect = ValueError('safe_authentication_failure')
    with pytest.raises(ValueError):
        await start(wired)
    assert 'commerce_claim_context_checkout' not in rpc_names(db)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
async def test_provider_paid_read_never_settles_without_signed_callback(wired):
    c, db, gateway, _ = wired
    await start(wired)
    c['session'].update(status='complete', payment_status='paid', payment_intent='pi_ContextSynthetic')
    result = await start(wired)
    assert result['status'] == 'awaiting_webhook' and result['url'] is None
    assert c['order']['payment_status'] == 'unpaid'
    gateway.create.assert_awaited_once()
    assert 'commerce_settle_context_checkout' not in rpc_names(db)


@pytest.mark.anyio
@pytest.mark.parametrize('explicit_context', [False, True])
async def test_signed_event_with_different_destination_marks_settlement_for_hold(wired, explicit_context):
    c, db, _, service = wired
    await start(wired)
    c['session'].update(status='complete', payment_status='paid', payment_intent='pi_ContextSynthetic')
    c['session']['shipping_details']['address']['line1'] = 'Different delivery address'
    event = {'id': 'evt_ContextSynthetic', 'type': 'checkout.session.async_payment_succeeded',
        'livemode': not c['order']['is_test'], 'data': {'object': deepcopy(c['session'])}}
    if explicit_context:
        event['context'] = ACCOUNT
    result = await service.accept_signed_event(event)
    assert result['held'] is True
    assert c['settled_payload']['p_destination_matches'] is False
    assert c['settled_payload']['p_stripe_account_id'] == ACCOUNT
    assert c['settled_payload']['p_profile_ref'] == c['profile'].reference
    assert rpc_names(db)[-1] == 'commerce_settle_context_checkout'


@pytest.mark.anyio
async def test_unpaid_completed_event_cannot_settle(wired):
    c, db, _, service = wired
    await start(wired)
    event = {'id': 'evt_ContextSyntheticUnpaid', 'type': 'checkout.session.completed',
        'livemode': not c['order']['is_test'], 'data': {'object': deepcopy(c['session'])}}
    result = await service.accept_signed_event(event)
    assert result['awaiting_payment'] is True
    assert 'commerce_settle_context_checkout' not in rpc_names(db)


@pytest.mark.anyio
@pytest.mark.parametrize('change', [{'livemode': False}, {'account': ACCOUNT},
    {'context': 'acct_ForeignMerchant'}, {'context': None}, {'context': ''},
    {'context': False}, {'context': [ACCOUNT]}, {'context': ACCOUNT + '/other'}])
async def test_webhook_mode_or_delegation_refused_before_database(wired, change):
    c, db, _, service = wired
    event = {'id': 'evt_ContextSynthetic', 'type': 'checkout.session.completed', 'livemode': True,
        'data': {'object': deepcopy(c['session'])}, **change}
    with pytest.raises(ValueError):
        await service.accept_signed_event(event)
    db.select.assert_not_awaited()
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('row,key,value', [
    ('attempt', 'stripe_account_id', 'acct_OtherMerchant'),
    ('order', 'stripe_account_id', 'acct_OtherMerchant'),
    ('attempt', 'stripe_profile_ref', 'other-profile'),
    ('order', 'stripe_profile_ref', 'other-profile'),
    ('attempt', 'is_test', True), ('order', 'is_test', True),
])
async def test_context_snapshot_conflict_never_creates(wired, row, key, value):
    c, _, gateway, _ = wired
    c[row][key] = value
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
async def test_bound_session_still_rejects_wrong_gateway_context(wired):
    c, _, gateway, _ = wired
    await start(wired)
    wrong = AuthenticatedStripeGateway('_'.join(('rk', 'live', 'synthetic_not_a_credential')),
                                      CheckoutServerContext('production', 'acct_OtherMerchant'))
    wrong.retrieve = AsyncMock(return_value=deepcopy(c['session']))
    wrong.create = AsyncMock()
    with pytest.raises(ValueError):
        await start(wired, gateway=wrong)
    wrong.retrieve.assert_not_awaited()
    wrong.create.assert_not_awaited()
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize('key,value', [('id', str(uuid4())), ('order_id', str(uuid4())),
    ('commerce_quote_id', str(uuid4())), ('stripe_account_id', 'acct_OtherMerchant'),
    ('stripe_profile_ref', 'other-profile'), ('is_test', True),
    ('params', {'replaced': 'unexpected'}), ('idempotency_key', 'rotated-key'),
    ('state', 'ready'), ('session_id', 'cs_live_UnexpectedBoundSession')])
async def test_durable_claim_mismatch_prevents_post(wired, key, value):
    c, _, gateway, _ = wired
    c['claim_change'] = lambda result: result.update({key: value})
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('key,value', [('id', str(uuid4())), ('cart_id', str(uuid4())),
    ('commerce_quote_id', str(uuid4())), ('guest_session_id', 'different_context_guest')])
async def test_prepared_order_must_match_persisted_identity_and_owner(wired, key, value):
    c, _, gateway, _ = wired
    c['prepare_change'] = lambda result: result['order'].update({key: value})
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_quote_does_not_prepare_or_call_provider(wired):
    c, db, gateway, _ = wired
    c['quote'] = None
    with pytest.raises(CustomerCheckoutError):
        await start(wired)
    db.rpc.assert_not_awaited()
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('phase', ['before_prepare', 'after_provider'])
async def test_verified_user_session_revocation_never_exposes_payment_url(wired, phase):
    c, _, gateway, _ = wired
    c['owner'] = {'p_user_id': USER, 'p_guest_session': None, 'p_auth_session_id': AUTH_SESSION}
    c['cart'].update(user_id=USER, guest_session_id=None)
    c['order'].update(user_id=USER, guest_session_id=None)
    c['quote'].update(owner_user_id=USER, owner_guest_session=None)
    if phase == 'before_prepare':
        c['auth_active'] = False
    else:
        def response(*args):
            c['auth_active'] = False
            return deepcopy(c['session'])
        gateway.retrieve.side_effect = response
    with pytest.raises(CustomerCheckoutError) as caught:
        await start(wired)
    assert caught.value.status_code == 401
    if phase == 'before_prepare':
        gateway.create.assert_not_awaited()
    else:
        gateway.create.assert_awaited_once()


@pytest.mark.anyio
async def test_financial_state_race_after_provider_read_never_exposes_url(wired):
    c, _, gateway, _ = wired
    def response(*args):
        c['order'].update(payment_status='refunded', status='refunded', refunded_amount_cents=10500)
        return deepcopy(c['session'])
    gateway.retrieve.side_effect = response
    with pytest.raises(CustomerCheckoutError):
        await start(wired)


@pytest.mark.anyio
async def test_paid_order_returns_without_another_provider_call(wired):
    c, _, gateway, _ = wired
    c['order'].update(status='paid', payment_status='paid')
    result = await start(wired)
    assert result['status'] == 'paid' and result['url'] is None
    gateway.authenticate.assert_not_awaited()
    gateway.create.assert_not_awaited()
    gateway.retrieve.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('mutation', [
    {'amount_total': 1}, {'livemode': False}, {'currency': 'usd'},
    {'id': 'cs_live_OtherSession'}, {'metadata': {}}, {'url': 'https://evil.example/checkout'},
])
async def test_bound_provider_conflict_never_returns_url(wired, mutation):
    c, _, gateway, _ = wired
    await start(wired)
    c['session'].update(mutation)
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_awaited_once()


@pytest.mark.parametrize('bad', [None, {}, 'profile'])
def test_server_profile_cannot_be_client_json(bad):
    with pytest.raises(ValueError):
        ContextCheckoutPayments(object(), bad)


@pytest.mark.parametrize('url', [
    'http://checkout.stripe.com/c/pay/cs_live_Synthetic',
    'https://checkout.stripe.com.evil.test/c/pay/cs_live_Synthetic',
    'https://user@checkout.stripe.com/c/pay/cs_live_Synthetic',
    'https://checkout.stripe.com:444/c/pay/cs_live_Synthetic',
    'https://checkout.stripe.com/c/pay/cs_live_Other',
    'https://checkout.stripe.com/c/pay/cs_test_Synthetic',
    'https://checkout.stripe.com\\evil.test/c/pay/cs_live_Synthetic',
    'https://checkout.stripe.com/c/pay/cs_live_Synthetic\n', None,
])
def test_hosted_context_url_binds_provider_origin_and_live_identity(url):
    with pytest.raises(CustomerCheckoutError):
        hosted_context_url(url, 'cs_live_Synthetic', is_test=False)


def test_hosted_url_preserves_stripe_fragment_without_new_destination():
    value = 'https://checkout.stripe.com:443/c/pay/cs_live_Synthetic#original_fragment'
    assert hosted_context_url(value, 'cs_live_Synthetic', is_test=False) == value


@pytest.mark.anyio
@pytest.mark.parametrize('field,value', [('discount_amount_cents', 50), ('promotion_id', str(uuid4())),
    ('total_cents', 10501), ('tax_amount_cents', 1751), ('currency', 'USD')])
async def test_financial_snapshot_changed_after_preparation_cannot_create(wired, field, value):
    c, db, gateway, _ = wired
    original = db.rpc.side_effect
    async def rpc(name, payload):
        result = await original(name, payload)
        if name == 'commerce_prepare_context_checkout':
            # The source row changes after the preparation snapshot was read.
            c['order'][field] = value
        return result
    db.rpc.side_effect = rpc
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
async def test_bind_failure_preserves_unknown_not_recreated(wired):
    c, db, gateway, _ = wired
    original = db.rpc.side_effect
    async def rpc(name, payload):
        if name == 'commerce_bind_context_session':
            raise SupabaseError(503, 'PRIVATE bind failure')
        return await original(name, payload)
    db.rpc.side_effect = rpc
    with pytest.raises(Exception):
        await start(wired)
    assert c['attempt']['state'] == 'unknown' and c['attempt']['session_id'] is None
    assert 'commerce_context_checkout_unknown' in rpc_names(db)
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
async def test_paid_webhook_during_provider_read_returns_paid_without_second_payment(wired):
    c, _, gateway, _ = wired
    def response(*args):
        c['order'].update(status='paid', payment_status='paid')
        return deepcopy(c['session'])
    gateway.retrieve.side_effect = response
    result = await start(wired)
    assert result['status'] == 'paid' and result['url'] is None
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize('kind,object_type,prefix', [
    ('checkout.session.expired', 'checkout.session', 'cs_live_'),
    ('checkout.session.async_payment_failed', 'checkout.session', 'cs_live_'),
    ('payment_intent.payment_failed', 'payment_intent', 'pi_'),
])
async def test_negative_payment_receipt_records_only_identity_for_review(wired, kind, object_type, prefix):
    c, db, gateway, service = wired
    event = {'id': 'evt_ContextReceipt', 'type': kind, 'livemode': True,
        'data': {'object': {'id': prefix + 'ContextReceipt', 'object': object_type,
                            'private_email': 'private@example.test'}}}
    result = await service.accept_signed_event(event)
    assert result['requires_reconciliation'] is True
    assert rpc_names(db) == ['commerce_record_context_event']
    assert c['receipt_payload'] == {'p_event_id': 'evt_ContextReceipt', 'p_event_type': kind,
        'p_object_id': prefix + 'ContextReceipt', 'p_is_test': False,
        'p_stripe_account_id': ACCOUNT, 'p_profile_ref': c['profile'].reference}
    db.select.assert_not_awaited()
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('kind,obj', [
    ('checkout.session.expired', {'id': 'cs_test_WrongMode', 'object': 'checkout.session'}),
    ('checkout.session.async_payment_failed', {'id': 'cs_live_Valid', 'object': 'payment_intent'}),
    ('payment_intent.payment_failed', {'id': 'pi_Valid', 'object': 'charge'}),
    ('refund.updated', {'id': 're_Valid', 'object': 'checkout.session'}),
    ('charge.refunded', {'id': 'ch_Valid', 'object': 'refund'}),
])
async def test_receipt_wrong_mode_or_object_kind_never_recorded(wired, kind, obj):
    _, db, _, service = wired
    event = {'id': 'evt_ContextReceipt', 'type': kind, 'livemode': True,
             'data': {'object': obj}}
    with pytest.raises(ValueError):
        await service.accept_signed_event(event)
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('intent', ['pi_ExactSynthetic',
    {'id': 'pi_ExactSynthetic', 'object': 'payment_intent', 'livemode': True}])
async def test_refund_receipt_passes_exact_signed_financial_observation_without_customer_data(wired, intent):
    c, db, _, service = wired
    event = {'object': 'event', 'id': 'evt_ContextRefundIdentity', 'type': 'refund.updated', 'livemode': True, 'created': 1700000000,
        'data': {'object': {'id': 're_ExactSynthetic', 'object': 'refund', 'payment_intent': intent,
                            'amount': 9876, 'status': 'pending', 'currency': 'eur',
                            'private_email': 'private@example.test'}}}
    await service.accept_signed_event(event)
    assert rpc_names(db) == ['commerce_record_context_refund']
    assert c['receipt_payload']['p_event']['payment_intent_id'] == 'pi_ExactSynthetic'
    assert c['receipt_payload']['p_event']['amount_cents'] == 9876
    assert c['receipt_payload']['p_event']['refund_status'] == 'pending'
    assert 'private@example.test' not in str(c['receipt_payload'])
    db.select.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('intent', [True, 'pi_unsafe\n', {}, {'id': 'pi_Valid', 'object': 'charge'},
    {'id': 'pi_Valid', 'object': 'payment_intent', 'livemode': False}])
async def test_refund_wrong_or_expanded_cross_mode_identity_is_refused(wired, intent):
    _, db, _, service = wired
    event = {'id': 'evt_ContextRefundIdentity', 'type': 'refund.updated', 'livemode': True,
        'data': {'object': {'id': 're_ExactSynthetic', 'object': 'refund', 'payment_intent': intent}}}
    with pytest.raises(ValueError):
        await service.accept_signed_event(event)
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_database_failure_never_acknowledges_paid_webhook(wired):
    c, db, _, service = wired
    await start(wired)
    c['session'].update(status='complete', payment_status='paid', payment_intent='pi_ContextSynthetic')
    original = db.rpc.side_effect
    async def rpc(name, payload):
        if name == 'commerce_settle_context_checkout':
            raise SupabaseError(503, 'PRIVATE settlement failure')
        return await original(name, payload)
    db.rpc.side_effect = rpc
    event = {'id': 'evt_ContextSyntheticPaid', 'type': 'checkout.session.completed', 'livemode': True,
        'data': {'object': deepcopy(c['session'])}}
    with pytest.raises(SupabaseError):
        await service.accept_signed_event(event)
    assert 'settled_payload' not in c


@pytest.mark.anyio
@pytest.mark.parametrize('rows_key', ['order_rows', 'cart_rows'])
async def test_missing_or_ambiguous_owner_rows_never_create(wired, rows_key):
    c, _, gateway, _ = wired
    c[rows_key] = []
    with pytest.raises(ValueError):
        await start(wired)
    gateway.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('rows_key', ['order_rows', 'attempt_rows'])
async def test_duplicate_context_rows_never_settle(wired, rows_key):
    c, db, _, service = wired
    c[rows_key] = [deepcopy(c['order'] if rows_key == 'order_rows' else c['attempt'])] * 2
    event = {'id': 'evt_ContextSyntheticPaid', 'type': 'checkout.session.completed', 'livemode': True,
        'data': {'object': deepcopy(c['session'])}}
    with pytest.raises(ValueError):
        await service.accept_signed_event(event)
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
async def test_late_paid_callback_is_not_blocked_by_local_quote_expiry(wired):
    c, db, gateway, service = wired
    await start(wired)
    expired = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp())
    c['attempt']['expires_at'] = c['session']['expires_at'] = expired
    c['quote']['expires_at'] = datetime.fromtimestamp(expired, timezone.utc).isoformat()
    c['session'].update(status='complete', payment_status='paid', payment_intent='pi_ContextLatePayment')
    event = {'id': 'evt_ContextLatePaid', 'type': 'checkout.session.async_payment_succeeded',
        'livemode': True, 'data': {'object': deepcopy(c['session'])}}
    await service.accept_signed_event(event)
    assert rpc_names(db)[-1] == 'commerce_settle_context_checkout'
    gateway.create.assert_awaited_once()


@pytest.mark.anyio
async def test_signed_callback_snapshot_wrong_profile_never_settles(wired):
    c, db, _, service = wired
    c['attempt']['stripe_profile_ref'] = 'other-receiver'
    event = {'id': 'evt_ContextWrongReceiver', 'type': 'checkout.session.completed',
        'livemode': True, 'data': {'object': deepcopy(c['session'])}}
    with pytest.raises(ValueError):
        await service.accept_signed_event(event)
    db.rpc.assert_not_awaited()
