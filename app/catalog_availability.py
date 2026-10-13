"""Purchase availability is computed by the server, never stored as fake stock."""
from app.config import Settings


def purchase_availability(product: dict, settings: Settings) -> dict:
    test_purchase = settings.test_catalog_available and product.get('status') == 'draft'
    maximum = 20 if test_purchase else min(20, max(0, product.get('stock', 0)))
    available = test_purchase or (product.get('status') == 'active' and maximum > 0)
    return {**product, 'test_purchase': test_purchase,
            'purchase_available': available, 'max_order_quantity': maximum if available else 0}


def purchasable(product: dict, settings: Settings, quantity: int = 1) -> bool:
    view = purchase_availability(product, settings)
    return view['purchase_available'] and 1 <= quantity <= view['max_order_quantity']
