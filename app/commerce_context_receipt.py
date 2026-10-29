"""Owner-scoped confirmation lookup for account-bound sessions, before or after payment."""
import re

from app.commerce_context_payments import ContextCheckoutPayments


class ContextReceiptError(ValueError):
    pass


async def context_checkout_receipt_order(db, session_id, profiles, user, guest_session):
    if (not isinstance(session_id, str)
            or not re.fullmatch(r'cs_(test|live)_[A-Za-z0-9_]{1,240}', session_id)):
        return None
    user_id = user.get('id') if isinstance(user, dict) else None
    if user_id is None and (not isinstance(guest_session, str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', guest_session)):
        return None
    is_test = session_id.startswith('cs_test_')
    matching = []
    for profile in profiles:
        if (profile.context.mode == 'sandbox') is not is_test:
            continue
        rows = await db.select('commerce_payment_sessions', params={
            'session_id': 'eq.' + session_id, 'stripe_account_id': 'eq.' + profile.context.stripe_account_id,
            'stripe_profile_ref': 'eq.' + profile.reference,
            'is_test': 'eq.true' if is_test else 'eq.false', 'limit': 2})
        if not rows:
            continue
        if (len(rows) != 1 or rows[0].get('session_id') != session_id
                or rows[0].get('stripe_account_id') != profile.context.stripe_account_id
                or rows[0].get('stripe_profile_ref') != profile.reference
                or rows[0].get('is_test') is not is_test):
            raise ContextReceiptError('Ambiguous checkout receipt')
        try:
            attempt, order = await ContextCheckoutPayments(db, profile).context(rows[0]['attempt_id'])
            if (attempt.get('session_id') != session_id
                    or order.get('stripe_session_id') not in (None, session_id)
                    or order.get('user_id') != user_id
                    or order.get('guest_session_id') != (None if user_id is not None else guest_session)):
                continue
            quotes = await db.select('commerce_quotes', params={'id': 'eq.' + order['commerce_quote_id'], 'limit': 2})
            if (len(quotes) != 1 or quotes[0].get('id') != order['commerce_quote_id']
                    or quotes[0].get('owner_user_id') != user_id
                    or quotes[0].get('owner_guest_session') != order.get('guest_session_id')):
                continue
            matching.append(order)
        except (ValueError, KeyError, TypeError):
            return None
    # No account guess when the same owner has an ambiguous provider identity.
    if len(matching) > 1:
        raise ContextReceiptError('Ambiguous checkout receipt')
    return matching[0] if matching else None
