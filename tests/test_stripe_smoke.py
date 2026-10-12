from scripts.smoke_stripe import run_http_smoke


def test_real_signed_checkout_lifecycle_creates_and_confirms_only_one_order():
    result = run_http_smoke()
    assert result['order_count'] == result['payment_effects'] == result['event_count'] == 1
    assert result['external_calls'] == 0
