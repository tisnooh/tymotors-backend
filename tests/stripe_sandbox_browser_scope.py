"""Pure policy for the opt-in loopback sandbox harness, never deployed."""
BOOTSTRAP_HTML=('<!doctype html><title>Isolated Stripe cart QA</title>'
    '<h1>Synthetic local cart only</h1><script src="/qa-stripe-cart.js"></script>')
BOOTSTRAP_JS=("localStorage.setItem('ty_session_id','sandbox_browser_synthetic_guest');"
    "location.replace('/cart');")


def sandbox_scope(host,path,method,browser_enabled):
    if host not in ('127.0.0.1','::1'):return 'forbidden'
    if path=='/qa-stripe-sandbox-status' and method=='GET':return 'identity'
    if path in ('/qa-stripe-cart','/qa-stripe-cart.js') and method=='GET':
        if not browser_enabled:return 'disabled'
        return 'bootstrap_html' if path=='/qa-stripe-cart' else 'bootstrap_js'
    browser_read=method=='GET' and (path.startswith('/qa-assets/')
        or path.startswith('/api/checkout-session/')
        or path in ('/api/brands','/api/categories','/api/settings','/support/track'))
    allowed=(path=='/api/cart' or path.startswith('/api/cart/')
        or path.startswith('/api/admin/commerce/') or path.startswith('/qa-stripe-payment/')
        or path in ('/api/stripe/webhook','/api/order-tracking','/order-success','/cart')
        or browser_read)
    return 'forward' if allowed else 'forbidden'
