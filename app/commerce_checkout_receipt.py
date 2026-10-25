"""Read-only order lookup for the existing confirmation page.

Quoted sessions bind before settlement. The browser may return before the signed
webhook writes orders.stripe_session_id. A binding is NOT proof of payment.
The caller MUST authorize the returned order before projecting any customer data.
"""
import re
from uuid import UUID


def _identity(value):
    identity = UUID(str(value))
    if not identity.int:
        raise ValueError
    return str(identity)


async def checkout_receipt_order(db, session_id):
    if not isinstance(session_id, str) or not re.fullmatch(r'cs_(test|live)_[A-Za-z0-9_]{1,240}', session_id):
        return None
    rows = await db.select('orders', params={'select':'*', 'stripe_session_id':'eq.'+session_id, 'limit':2})
    if rows:
        # Preserve legacy behavior, but never choose between ambiguous rows.
        return rows[0] if len(rows)==1 else None
    if not session_id.startswith('cs_test_'):
        return None
    bindings = await db.select('commerce_test_sessions', params={'session_id':'eq.'+session_id,'limit':2})
    if len(bindings)!=1 or bindings[0].get('session_id')!=session_id:
        return None
    try:
        attempt_id = _identity(bindings[0]['attempt_id'])
        attempts = await db.select('commerce_checkout_attempts',params={'id':'eq.'+attempt_id,'limit':2})
        if len(attempts)!=1 or attempts[0].get('id')!=attempt_id or attempts[0].get('is_test') is not True:
            return None
        attempt = attempts[0]
        order_id, quote_id = _identity(attempt['order_id']), _identity(attempt['commerce_quote_id'])
        orders = await db.select('orders',params={'id':'eq.'+order_id,'is_test':'eq.true','limit':2})
        quotes = await db.select('commerce_quotes',params={'id':'eq.'+quote_id,'limit':2})
        if len(orders)!=1 or len(quotes)!=1:
            return None
        order, quote = orders[0], quotes[0]
        if (order.get('id')!=order_id or order.get('is_test') is not True
                or order.get('commerce_quote_id')!=quote_id or quote.get('id')!=quote_id
                or order.get('stripe_session_id') not in (None,session_id)
                or order.get('user_id')!=quote.get('owner_user_id')
                or order.get('guest_session_id')!=quote.get('owner_guest_session')
                or (order.get('user_id') is None)==(order.get('guest_session_id') is None)):
            return None
        return order
    except (KeyError,ValueError,TypeError,AttributeError):
        return None
