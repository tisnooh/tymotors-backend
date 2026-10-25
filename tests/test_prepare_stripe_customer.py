"""Public sandbox runner contract. No network and no credentials."""
import json
from uuid import uuid4
from unittest.mock import patch

import pytest
from tests.prepare_stripe_sandbox_case import customer_checkout, ORIGIN


class Response:
    def __init__(self, value):
        self.value = json.dumps(value).encode()

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self): return self.value


def test_public_case_has_owner_capability_but_no_admin_or_client_price():
    qid, oid, aid = [str(uuid4()) for _ in range(3)]
    sid = 'cs_test_SYNTHETIC'
    body = {'order_id':oid,'is_test':True,'status':'open',
        'url':'https://checkout.stripe.com/c/pay/'+sid+'#synthetic'}
    with patch('tests.prepare_stripe_sandbox_case.urlopen', return_value=Response(body)) as network, \
         patch('tests.prepare_stripe_sandbox_case.sql', return_value=[{'id':aid,'session_id':sid}]) as database:
        result = customer_checkout(qid, {'X-Session-Id':'synthetic_guest_owner'})
    req = network.call_args.args[0]
    assert req.full_url == ORIGIN+'/api/cart/quote/'+qid+'/checkout'
    assert req.method == 'POST'
    assert req.get_header('Authorization') is None
    assert req.get_header('X-session-id') == 'synthetic_guest_owner'
    assert set(json.loads(req.data)) == {'request_key'}
    assert network.call_args.kwargs['timeout'] == 90
    query, params = database.call_args.args
    assert 'join commerce_test_sessions s on s.attempt_id=a.id' in query
    assert 'a.id,s.session_id' in query
    assert 'a.session_id' not in query
    assert params == [oid]
    assert result['entrypoint'] == 'public_owned_customer_checkout'
    assert result['attempt_id'] == aid
    assert result['payment_completed'] is False


@pytest.mark.parametrize('url', ['https://evil.example/c/pay/cs_test_SYNTHETIC',
    'https://checkout.stripe.com/c/pay/cs_test_OTHER'])
def test_public_case_rejects_unbound_redirect(url):
    body={'order_id':str(uuid4()),'is_test':True,'status':'open','url':url}
    with patch('tests.prepare_stripe_sandbox_case.urlopen', return_value=Response(body)), \
         patch('tests.prepare_stripe_sandbox_case.sql', return_value=[{'id':str(uuid4()),'session_id':'cs_test_SYNTHETIC'}]):
        with pytest.raises(Exception, match='checkout_provider_response_requires_review'):
            customer_checkout(uuid4(), {'X-Session-Id':'synthetic_guest_owner'})


@pytest.mark.parametrize('rows', [[], [
    {'id':str(uuid4()),'session_id':'cs_test_FIRST'},
    {'id':str(uuid4()),'session_id':'cs_test_SECOND'}]])
def test_public_case_refuses_missing_or_ambiguous_session_binding(rows):
    body={'order_id':str(uuid4()),'is_test':True,'status':'open',
        'url':'https://checkout.stripe.com/c/pay/cs_test_SYNTHETIC'}
    with patch('tests.prepare_stripe_sandbox_case.urlopen', return_value=Response(body)), \
         patch('tests.prepare_stripe_sandbox_case.sql', return_value=rows):
        with pytest.raises(AssertionError):
            customer_checkout(uuid4(), {'X-Session-Id':'synthetic_guest_owner'})


def test_null_historical_attempt_column_cannot_be_used_as_provider_binding():
    body={'order_id':str(uuid4()),'is_test':True,'status':'open',
        'url':'https://checkout.stripe.com/c/pay/cs_test_SYNTHETIC'}
    def query(statement, _params):
        # Model the ACTUAL difference between the two persisted sources. The
        # isolated HTTP/SQL probe separately proves it against PGlite.
        return [{'id':str(uuid4()),'session_id':
            'cs_test_SYNTHETIC' if 'join commerce_test_sessions' in statement else None}]
    with patch('tests.prepare_stripe_sandbox_case.urlopen', return_value=Response(body)), \
         patch('tests.prepare_stripe_sandbox_case.sql', side_effect=query):
        assert customer_checkout(uuid4(), {'X-Session-Id':'synthetic_guest_owner'})['session_id'] == 'cs_test_SYNTHETIC'
