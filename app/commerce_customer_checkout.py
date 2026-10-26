"""Customer-owned sandbox bridge over the existing immutable commerce workflow.

Never impersonates an administrator. Six owner-aware RPCs enforce ownership and
the shared cart purchase lock. Provider I/O occurs only after the durable claim.
No live mode, auto retry, settlement, refund, email or supplier transmission.
"""
import base64
from datetime import datetime, timezone
import json
import re
from urllib.parse import urlsplit
from uuid import UUID

from app.commerce_attempt_service import CheckoutAttemptError, CheckoutAttemptService
from app.commerce_checkout_events import CheckoutEventError, validate_checkout_session
from app.commerce_payment_service import CommercePaymentError, CommerceTestPayments, TestStripeGateway
from app.commerce_quote_engine import CartQuoteError
from app.commerce_quote_service import CartQuoteService
from app.supabase_rest import SupabaseError


class CustomerCheckoutError(ValueError):
    def __init__(self, code='checkout_unavailable', status_code=409):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def _uuid(value):
    identity = UUID(str(value))
    if not identity.int:
        raise ValueError
    return str(identity)


def customer_owner(verified_user, authorization, guest_session):
    """Call ONLY after optional_user authenticated this exact Authorization.

    Decoding here is NOT authentication. Supabase already verified this JWT and
    its current Auth session; SQL rechecks that session under the purchase lock.
    The caller must never pass a user object or Authorization from request JSON.
    """
    if verified_user is not None:
        try:
            scheme, token = authorization.split(' ',1)
            if scheme.lower() != 'bearer' or len(token.split('.')) != 3:
                raise ValueError
            segment=token.split('.')[1]
            claims=json.loads(base64.urlsafe_b64decode(segment+'='*(-len(segment)%4)))
            user_id=_uuid(verified_user['id'])
            if _uuid(claims['sub']) != user_id:
                raise ValueError
            return {'p_user_id':user_id,'p_guest_session':None,
                    'p_auth_session_id':_uuid(claims['session_id'])}
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError):
            raise CustomerCheckoutError('authentication_required',401) from None
    if authorization:
        # Invalid authentication must never downgrade to a guest capability.
        raise CustomerCheckoutError('authentication_required',401)
    if not isinstance(guest_session,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',guest_session):
        raise CustomerCheckoutError('guest_session_required',400)
    return {'p_user_id':None,'p_guest_session':guest_session,'p_auth_session_id':None}


class OwnedCheckoutStore:
    """Explicit RPC adapter; None actor is not an admin identity or a bypass.

    Reuses the tested parameter builder/provider adapter, but maps every
    administrative mutation to an owner-authorized customer RPC instead.
    """
    _RPCS={name:'commerce_customer_'+name.removeprefix('commerce_') for name in (
        'commerce_prepare_checkout_attempt','commerce_store_checkout_params',
        'commerce_claim_checkout_attempt','commerce_checkout_unknown','commerce_cancel_checkout_draft')}

    def __init__(self,db,owner):
        self.db,self.owner=db,dict(owner)

    async def select(self,*args,**kwargs):
        return await self.db.select(*args,**kwargs)

    async def rpc(self,name,payload):
        if name=='commerce_bind_test_session':
            # Binding a possibly-created response retains financial truth even
            # after catalogue changes. Session identity is validated before this.
            return await self.db.rpc(name,payload)
        if name not in self._RPCS or payload.get('p_actor') is not None:
            raise CustomerCheckoutError('unsupported_customer_operation')
        return await self.db.rpc(self._RPCS[name],
            {**{k:v for k,v in payload.items() if k!='p_actor'},**self.owner})


def hosted_test_url(value,session_id):
    try:
        parsed=urlsplit(value)
        if (not isinstance(value,str) or any(c.isspace() or ord(c)<32 for c in value)
                or '\\' in value or parsed.scheme!='https' or parsed.hostname!='checkout.stripe.com'
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None,443) or parsed.path!='/c/pay/'+session_id
                or not re.fullmatch(r'cs_test_[A-Za-z0-9_]{1,240}',session_id)):
            raise ValueError
        return value
    except (ValueError,TypeError,AttributeError):
        raise CustomerCheckoutError('checkout_provider_response_requires_review') from None


class CustomerTestCheckout:
    def __init__(self,db,gateway,origin,allowed_countries):
        self.db,self.gateway,self.origin=db,gateway,origin
        self.quotes=CartQuoteService(db,allowed_countries)

    async def _order(self,order_id,quote_id,cart,owner):
        carts=await self.db.select('carts',params={'id':'eq.'+cart['id'],'limit':2})
        if (len(carts)!=1 or carts[0].get('user_id')!=owner['p_user_id']
                or carts[0].get('guest_session_id')!=owner['p_guest_session']):
            raise CustomerCheckoutError()
        if owner['p_user_id'] is not None:
            active=await self.db.rpc('is_auth_session_active',{
                'p_session_id':owner['p_auth_session_id'],'p_user_id':owner['p_user_id']})
            if active is not True:
                raise CustomerCheckoutError('authentication_required',401)
        rows=await self.db.select('orders',params={'id':'eq.'+_uuid(order_id),'limit':2})
        if not isinstance(rows,list) or len(rows)!=1:
            raise CustomerCheckoutError()
        order=rows[0]
        if (order.get('id')!=str(order_id) or order.get('commerce_quote_id')!=str(quote_id)
                or order.get('cart_id')!=cart['id'] or order.get('user_id')!=owner['p_user_id']
                or order.get('guest_session_id')!=owner['p_guest_session']
                or order.get('is_test') is not True):
            raise CustomerCheckoutError()
        return order

    @staticmethod
    def _paid(order):
        if (order.get('status')=='paid' and order.get('payment_status')=='paid'
                and type(order.get('refunded_amount_cents')) is int and order['refunded_amount_cents']==0):
            return {'order_id':order['id'],'order_number':order['order_number'],
                    'quote_id':order['commerce_quote_id'],'status':'paid','is_test':True,'url':None}
        if order.get('status')!='pending' or order.get('payment_status')!='unpaid':
            raise CustomerCheckoutError('checkout_requires_review')
        if order.get('refunded_amount_cents') != 0 or type(order.get('refunded_amount_cents')) is not int:
            raise CustomerCheckoutError('checkout_requires_review')
        return None

    async def start(self,quote_id,request_key,cart,user,guest_session,owner):
        if not isinstance(self.gateway,TestStripeGateway):
            raise CustomerCheckoutError('test_gateway_required')
        try:
            _uuid(request_key)  # Retry token is not the purchase lock authority.
            quote_id=_uuid(quote_id)
            quote=await self.quotes.read(quote_id,cart,user,guest_session)
            if quote is None:
                raise CustomerCheckoutError()
            prepared=await self.db.rpc('commerce_customer_order_from_quote',
                {'p_quote_id':quote_id,**owner})
            if prepared.get('is_test') is not True:
                raise CustomerCheckoutError()
            order=await self._order(prepared['order_id'],quote_id,cart,owner)
            if (paid:=self._paid(order)) is not None:
                return paid
            scoped=OwnedCheckoutStore(self.db,owner)
            attempt=await CheckoutAttemptService(scoped,self.origin).prepare(None,order['id'])
            payments=CommerceTestPayments(scoped,self.gateway)
            context,snapshot=await payments._context(attempt['attempt_id'])
            if (context['order_id']!=order['id'] or context.get('commerce_quote_id')!=quote_id
                    or snapshot!=order):
                raise CustomerCheckoutError()
            if context['session_id'] is None:
                if context['state']!='ready':
                    raise CustomerCheckoutError('checkout_requires_inspection')
                await payments.create_session(None,context['id'])
                context,snapshot=await payments._context(context['id'])
            session=await self.gateway.retrieve(context['session_id'])
            session=(session.to_dict() if hasattr(session,'to_dict') else
                     session.to_dict_recursive() if hasattr(session,'to_dict_recursive') else session)
            intent=session.get('payment_intent')
            if intent is not None and (not isinstance(intent,str) or not re.fullmatch(r'pi_[A-Za-z0-9_]{1,240}',intent)):
                raise CustomerCheckoutError('checkout_provider_response_requires_review')
            observed=validate_checkout_session(session,context,snapshot)
            # A provider read is never a settlement event. Recheck local owner
            # and financial state after the network delay before exposing a URL.
            current=await self._order(order['id'],quote_id,cart,owner)
            if (paid:=self._paid(current)) is not None:
                return paid
            if current!=order:
                raise CustomerCheckoutError('checkout_requires_review')
            if observed['financial_valid']:
                return {'order_id':order['id'],'order_number':order['order_number'],
                        'quote_id':quote_id,'session_id':context['session_id'],
                        'status':'awaiting_webhook','is_test':True,'url':None}
            if session['status']!='open' or session['expires_at']<=datetime.now(timezone.utc).timestamp():
                raise CustomerCheckoutError('checkout_requires_inspection')
            return {'order_id':order['id'],'order_number':order['order_number'],
                    'quote_id':quote_id,'session_id':context['session_id'],
                    'status':'open','is_test':True,
                    'url':hosted_test_url(session.get('url'),context['session_id'])}
        except CustomerCheckoutError:
            raise
        except (CartQuoteError,CheckoutAttemptError,CheckoutEventError,CommercePaymentError,ValueError,KeyError,TypeError):
            raise CustomerCheckoutError() from None
        except SupabaseError:
            raise CustomerCheckoutError() from None
        except Exception:
            # This can follow a remote creation; NEVER cancel or rotate a key.
            raise CustomerCheckoutError('checkout_requires_inspection',502) from None
