"""Prepare ONE explicitly synthetic order and REAL Stripe sandbox session.

Requires tests.serve_stripe_sandbox_fixture on 127.0.0.1:8765 and the disposable
SQL bridge on 127.0.0.1:8766, managed by the operator. No server/account is
started here; no API key or webhook secret is read. No payment is submitted.
The returned checkout URL must be exercised separately using sandbox test data,
then the actual signed event and database state must be checked by the operator.

Run: python -m tests.prepare_stripe_sandbox_case
Retry the SAME attempt without creating another order:
python -m tests.prepare_stripe_sandbox_case --attempt UUID
An ambiguous/unbound remote call is never retried with a new key by this tool.
"""
import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from tests.commerce_http_probe import ADMIN, HEADERS, eq, request, save, sql
import tests.commerce_http_probe as probe

ORIGIN = 'http://127.0.0.1:8765'


def assert_fixture():
    if probe.API != ORIGIN + '/api' or probe.SQL != 'http://127.0.0.1:8766/query':
        raise RuntimeError('literal_loopback_endpoints_required')
    with urlopen(ORIGIN + '/qa-stripe-sandbox-status', timeout=15) as response:
        status = json.load(response)
    if status.get('fixture') != 'real_stripe_sandbox_disposable_database' or status.get('is_test') is not True:
        raise RuntimeError('real_sandbox_fixture_required')


def checkout(attempt_id):
    attempt_id = str(UUID(str(attempt_id)))
    req = Request(ORIGIN + '/qa-stripe-payment/' + attempt_id, method='POST', headers=HEADERS)
    with urlopen(req, timeout=90) as response:
        result = json.load(response)
    eq(result['attempt_id'], attempt_id)
    eq(result['is_test'], True)
    eq(result['provider_transport'], 'real_stripe_sdk')
    eq(result['payment_completed'], False)
    if not result.get('session_id', '').startswith('cs_test_'):
        raise RuntimeError('sandbox_session_id_required')
    # The server checks the full origin/path; this client is not a redirector.
    if not result.get('checkout_url', '').startswith('https://checkout.stripe.com/'):
        raise RuntimeError('stripe_hosted_checkout_required')
    return result


def prepare():
    assert_fixture()
    marker = uuid4().hex[:10]
    label = 'SANDBOX-SYNTHETIC-' + marker
    products = sql("select id from products where sku='TEST-001' and status='active'")
    if len(products) != 1:
        raise RuntimeError('disposable_product_fixture_required')
    product = products[0]['id']
    supplier = sql("select id from suppliers where name='Fixture supplier' order by id limit 1")[0]['id']
    rule = sql("select * from product_compatibilities where product_id=$1 and verification_state='verified' order by id", [product])[0]
    # Changes ONLY the synthetic TEST-001 in the in-memory disposable database,
    # never a catalogue image/file, hosted record, or asserted genuine licence.
    sql("update product_images set url='https://cdn.example.com/isolated-fixture.webp' where product_id=$1", [product])
    sql("""insert into commerce_image_permissions
        (product_id,image_url,state,evidence_ref,commercial_use,derivatives_use,
         product_match_confirmed,marks_clearance,countries,valid_until,verified_by,verified_at)
        values($1,'https://cdn.example.com/isolated-fixture.webp','verified',
         'SYNTHETIC GRANT ONLY NOT A REAL LICENCE',true,true,true,'not_present',
         array['FR'],now()+interval '1 year',$2,now())
        on conflict(product_id,image_url) do nothing""", [product, ADMIN])
    actor = save('agent', {'profile_id': ADMIN, 'name': 'Synthetic sandbox agent',
        'role': 'orders', 'is_active': True})
    variant = save('variant', {'product_id': product, 'sku': label,
        'name': 'Synthetic sandbox product', 'price_cents': 3000, 'stock': 3,
        'status': 'active', 'is_verified': True, 'requires_vehicle': True,
        'evidence_ref': 'SYNTHETIC NOT A REAL VERIFIED PRODUCT', 'compatibility_ids': [rule['id']]})
    offer = save('offer', {'variant_id': variant['id'], 'supplier_id': supplier,
        'supplier_sku': 'SOURCE-' + label, 'supplier_variant': 'Synthetic exact black',
        'url': 'https://supplier.example.test/' + label,
        'verification_state': 'verified', 'evidence_ref': 'SYNTHETIC NOT REAL SUPPLIER TERMS',
        'is_primary': True, 'availability': 'available', 'available_quantity': 3,
        'valid_until': '2099-01-01T00:00:00Z', 'unit_cost_cents': 1000,
        'recoverable_tax_cents': 0, 'currency': 'EUR', 'preparation_days_min': 1,
        'preparation_days_max': 2, 'responsible_agent_id': actor['id']})
    rate = save('shipping_rate', {'offer_id': offer['id'], 'country': 'FR',
        'mode': 'tracked', 'max_quantity': 3, 'shipping_cost_cents': 200,
        'shipping_recoverable_tax_cents': 0, 'customer_shipping_cents': 500,
        'goods_tax_bps': 0, 'shipping_tax_bps': 0, 'agent_fee_cents': 0,
        'import_duty_cents': 0, 'nonrecoverable_tax_cents': 0, 'other_cost_cents': 0,
        'verification_state': 'verified', 'evidence_ref': 'SYNTHETIC NOT REAL SHIPPING TERMS',
        'valid_until': '2099-01-01T00:00:00Z', 'delivery_days_min': 3, 'delivery_days_max': 5})
    mapping = request('/admin/commerce/hypersku/mappings', 'POST', {'data': {
        'offer_id': offer['id'], 'shipping_rate_id': rate['id'], 'is_test': True,
        'state': 'verified', 'hypersku_product_ref': 'SYNTHETIC-PRODUCT-' + label,
        'hypersku_variant_ref': 'SYNTHETIC-VARIANT-' + label,
        'equivalence_evidence_ref': 'SYNTHETIC NOT A REAL HYPERSKU EQUIVALENCE',
        'provider_quote_ref': 'SYNTHETIC NOT A REAL HYPERSKU QUOTE',
        'valid_until': '2098-01-01T00:00:00Z'}}, HEADERS)
    vehicle = {'brand_slug': 'bmw', 'model': rule['model_name'], 'chassis': rule['chassis'],
        'year': rule['year_from'], 'facelift': 'pre-lci', 'body_type': 'sedan'}
    guest = {'X-Session-Id': 'sandbox_' + label}
    request('/cart', 'POST', {'product_id': product, 'variant_id': variant['id'],
        'quantity': 1, 'selected_vehicle': vehicle}, guest)
    quote = request('/cart/quote', 'POST', {'request_key': str(uuid4()), 'mode': 'tracked',
        'destination': {'name': 'Synthetic recipient', 'line1': '1 Synthetic street',
            'city': 'Paris', 'country': 'FR', 'postal_code': '75001'}}, guest)
    order = request('/admin/commerce/quotes/' + quote['quote_id'] + '/prepare-test-order',
        'POST', headers=HEADERS)
    attempt = request('/admin/commerce/orders/' + order['order_id'] + '/checkout-attempt',
        'POST', headers=HEADERS)
    plan = request('/admin/commerce/orders/' + order['order_id'] + '/fulfillment-plan', headers=HEADERS)
    eq(len(plan['tasks']), 1)
    eq(plan['tasks'][0]['supplier_sku'], 'SOURCE-' + label)
    eq(plan['tasks'][0]['agent_id'], actor['id'])
    eq(plan['tasks'][0]['shipping_cost_cents'], 200)
    result = checkout(attempt['attempt_id'])
    # Remote session creation is not a payment. There must still be no paid task.
    eq(sql('select payment_status from orders where id=$1', [order['order_id']])[0]['payment_status'], 'unpaid')
    eq(sql('select count(*)::integer n from commerce_test_tasks where order_id=$1', [order['order_id']])[0]['n'], 0)
    return {**result, 'scope': 'synthetic_order_real_sandbox_session_not_payment_completion',
        'sku': label, 'product_id': product, 'variant_id': variant['id'],
        'supplier_id': supplier, 'supplier_offer_id': offer['id'], 'shipping_rate_id': rate['id'],
        'agent_id': actor['id'], 'hypersku_mapping_id': mapping['id'],
        'hypersku_mapping_scope': 'SYNTHETIC_NOT_REAL_HYPERSKU_CONNECTION',
        'quote_id': quote['quote_id'], 'vehicle': vehicle,
        'expected_total_cents': 3500, 'currency': 'EUR',
        'next_required_proof': 'complete_hosted_sandbox_checkout_then_verify_real_signed_webhook_and_database'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=UUID, help='Inspect/reuse one existing synthetic sandbox attempt')
    args = parser.parse_args()
    try:
        if args.attempt:
            assert_fixture()
            result = checkout(args.attempt)
        else:
            result = prepare()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        # Preserve ambiguous state and print no HTTP/SDK exception bodies.
        diagnostic = {'status': 'BLOCKED', 'error_type': type(error).__name__,
            'action': 'inspect_existing_attempt_before_any_retry_no_auto_cancel_or_new_charge'}
        if isinstance(error, HTTPError):
            diagnostic.update(http_status=error.code, path=urlsplit(error.url).path)
            try:
                detail = json.load(error).get('detail', {})
                if isinstance(detail, dict):
                    diagnostic['provider_diagnostic'] = {k: v for k, v in detail.items()
                        if k in ('code', 'error_type', 'provider_code', 'provider_param', 'business_code')}
            except (ValueError, TypeError): pass
        print(json.dumps(diagnostic))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
