"""Isolated harness guards: no network or real credentials in these tests."""
from unittest.mock import Mock

import pytest

from tests.run_stripe_sandbox import browser_checkout_binding


def test_browser_binding_waits_without_creating_or_retrying():
    query=Mock(return_value=[])
    assert browser_checkout_binding(query,'synthetic-cart') is None
    query.return_value=[{'order_id':'order','quote_id':'quote','attempt_id':'attempt','session_id':None}]
    assert browser_checkout_binding(query,'synthetic-cart') is None
    query.return_value=[{'order_id':'order','quote_id':'quote','attempt_id':'attempt','session_id':'cs_test_synthetic'}]
    assert browser_checkout_binding(query,'synthetic-cart')['session_id']=='cs_test_synthetic'
    assert all('select' in call.args[0] and call.args[1]==['synthetic-cart'] for call in query.call_args_list)


def test_browser_binding_rejects_duplicate_orders_or_attempts():
    with pytest.raises(RuntimeError,match='Duplicate'):
        browser_checkout_binding(Mock(return_value=[{},{}]),'synthetic-cart')


def test_browser_preparation_seeds_cart_but_never_quote_address_or_payment(monkeypatch):
    from tests import prepare_stripe_sandbox_case as prep
    monkeypatch.setattr(prep,'assert_fixture',lambda:None)
    def query(statement,params=None):
        if "sku='TEST-001'" in statement:return [{'id':'product'}]
        if "name='Fixture supplier'" in statement:return [{'id':'supplier'}]
        if 'product_compatibilities' in statement:
            return [{'id':'fitment','model_name':'Series 3','chassis':'F30','year_from':2012}]
        if 'select cart_id' in statement:return [{'cart_id':'cart'}]
        return []  # Synthetic image rights setup only.
    monkeypatch.setattr(prep,'sql',query)
    monkeypatch.setattr(prep,'save',lambda kind,data:{'id':kind})
    writes=[]
    def request(path,method=None,payload=None,headers=None):
        writes.append((path,payload,headers))
        if path=='/admin/commerce/hypersku/mappings':return {'id':'mapping'}
        if path=='/cart':return {'items':[{'cart_item_id':'line'}]}
        raise AssertionError('No quote or provider operation permitted during browser setup')
    monkeypatch.setattr(prep,'request',request)
    case=prep.prepare(customer=True,browser_cart=True)
    assert case['entrypoint']=='browser_cart' and case['cart_id']=='cart'
    assert not {'order_id','quote_id','attempt_id','session_id'} & set(case)
    assert case['expected_total_cents']==3500 and case['payment_completed'] is False
    assert [path for path,_,_ in writes]==['/admin/commerce/hypersku/mappings','/cart']
    assert writes[-1][2]=={'X-Session-Id':'sandbox_browser_synthetic_guest'}
    assert 'destination' not in writes[-1][1]


def test_browser_fixture_scope_without_importing_mutating_server():
    from tests.stripe_sandbox_browser_scope import BOOTSTRAP_HTML,BOOTSTRAP_JS,sandbox_scope
    def check(path,method='GET',host='127.0.0.1',enabled=True):
        return sandbox_scope(host,path,method,enabled)
    assert check('/qa-stripe-cart',enabled=False)=='disabled'
    assert check('/qa-stripe-cart')=='bootstrap_html'
    assert check('/qa-stripe-cart.js')=='bootstrap_js'
    assert '/qa-stripe-cart.js' in BOOTSTRAP_HTML
    assert 'sandbox_browser_synthetic_guest' in BOOTSTRAP_JS
    assert 'sk_test' not in BOOTSTRAP_JS and 'whsec_' not in BOOTSTRAP_JS
    for path in ('/qa-assets/static/js/main.js','/api/checkout-session/cs_test_synthetic','/support/track'):
        assert check(path)=='forward' and check(path,'POST')=='forbidden'
    assert check('/api/checkout-session/cs_test_synthetic',host='203.0.113.1')=='forbidden'
    assert check('/api/checkout')=='forbidden'
    assert check('/qa-payment-attempt/synthetic','POST')=='forbidden'
    assert check('/qa-stripe-sandbox-status')=='identity'
