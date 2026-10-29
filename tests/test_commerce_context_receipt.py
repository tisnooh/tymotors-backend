"""Read-only owner/profile confirmation, no payment API or status mutation."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.commerce_checkout_mode import CheckoutServerContext
from app.commerce_context_receipt import context_checkout_receipt_order, ContextReceiptError
from app.commerce_webhook_profiles import StripeWebhookProfile

PROFILE = StripeWebhookProfile('production', CheckoutServerContext('production', 'acct_Fixture'), 'whsec_synthetic_fixture')
GUEST = 'synthetic_profile_receipt_owner'
SID = 'cs_live_synthetic_receipt'


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.fixture
def wired():
    oid, aid, qid = [str(uuid4()) for _ in range(3)]
    data = {
        'commerce_payment_sessions': [{'attempt_id': aid, 'session_id': SID, 'is_test': False,
            'stripe_account_id': PROFILE.context.stripe_account_id, 'stripe_profile_ref': PROFILE.reference}],
        'commerce_checkout_attempts': [{'id': aid, 'order_id': oid, 'commerce_quote_id': qid,
            'session_id': SID, 'is_test': False, 'stripe_account_id': PROFILE.context.stripe_account_id,
            'stripe_profile_ref': PROFILE.reference}],
        'orders': [{'id': oid, 'commerce_quote_id': qid, 'stripe_session_id': None, 'is_test': False,
            'user_id': None, 'guest_session_id': GUEST, 'stripe_account_id': PROFILE.context.stripe_account_id,
            'stripe_profile_ref': PROFILE.reference, 'status': 'pending', 'payment_status': 'unpaid'}],
        'commerce_quotes': [{'id': qid, 'owner_user_id': None, 'owner_guest_session': GUEST}]}
    async def select(table, *, params):
        assert params['limit'] == 2
        return deepcopy(data[table])
    return SimpleNamespace(select=AsyncMock(side_effect=select), rpc=AsyncMock()), data


@pytest.mark.anyio
async def test_pending_confirmation_needs_binding_owner_and_profile_not_payment(wired):
    db, data = wired
    before = deepcopy(data)
    result = await context_checkout_receipt_order(db, SID, [PROFILE], None, GUEST)
    assert result == before['orders'][0] and result['payment_status'] == 'unpaid'
    assert result['stripe_session_id'] is None
    assert data == before
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('table,field,value', [
    ('commerce_checkout_attempts', 'id', str(uuid4())),
    ('commerce_checkout_attempts', 'commerce_quote_id', str(uuid4())),
    ('orders', 'id', str(uuid4())), ('orders', 'stripe_account_id', 'acct_Another'),
    ('orders', 'stripe_profile_ref', 'another'), ('orders', 'is_test', True),
    ('orders', 'stripe_session_id', 'cs_live_foreign'), ('orders', 'guest_session_id', 'foreign'),
    ('commerce_quotes', 'id', str(uuid4())), ('commerce_quotes', 'owner_guest_session', 'foreign')])
async def test_inconsistent_frozen_relations_never_expose_receipt(wired, table, field, value):
    db, data = wired
    data[table][0][field] = value
    assert await context_checkout_receipt_order(db, SID, [PROFILE], None, GUEST) is None
    db.rpc.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('sid,guest', [(None, GUEST), ('pi_synthetic', GUEST), (SID, None), (SID, 'short')])
async def test_missing_session_or_owner_never_reads_data(wired, sid, guest):
    db, _ = wired
    assert await context_checkout_receipt_order(db, sid, [PROFILE], None, guest) is None
    db.select.assert_not_awaited()


@pytest.mark.anyio
async def test_no_mode_fallback_or_guest_downgrade_for_authenticated_user(wired):
    db, _ = wired
    sandbox = StripeWebhookProfile('sandbox', CheckoutServerContext('sandbox', 'acct_Fixture'), 'whsec_other_synthetic')
    assert await context_checkout_receipt_order(db, SID, [sandbox], None, GUEST) is None
    db.select.assert_not_awaited()
    assert await context_checkout_receipt_order(db, SID, [PROFILE], {'id': str(uuid4())}, GUEST) is None


@pytest.mark.anyio
async def test_duplicate_bindings_fail_without_selecting_first(wired):
    db, data = wired
    data['commerce_payment_sessions'] *= 2
    with pytest.raises(ContextReceiptError):
        await context_checkout_receipt_order(db, SID, [PROFILE], None, GUEST)
