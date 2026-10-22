"""Allow-listed public/legal configuration; no fictitious business identity."""
import os
from app.product_image_policy import permitted_image
LEGAL_FIELDS = ('company_name', 'legal_form', 'siret', 'registration', 'address', 'contact_email', 'contact_phone', 'vat_mention', 'publication_director', 'mediator_name', 'mediator_url', 'mediator_address', 'hosting_details', 'returns_address')
def legal_configuration():
    return {key: os.getenv('LEGAL_'+key.upper(), '').strip() for key in LEGAL_FIELDS}
def legal_ready(config=None):
    value = config if config is not None else legal_configuration()
    return all(value.get(key) for key in ('company_name','siret','address','contact_email','contact_phone','vat_mention','mediator_name','mediator_url','hosting_details','returns_address'))
def public_site_configuration(settings):
    legal = legal_configuration()
    return {'site_url': settings.frontend_url, 'stripe_mode': settings.stripe_mode, 'test_catalog_available': settings.test_catalog_available, 'legal': legal, 'legal_ready': legal_ready(legal), 'shipping_rate_cents': settings.shipping_rate_cents, 'free_shipping_threshold_cents': settings.free_shipping_threshold_cents, 'shipping_countries': list(settings.shipping_countries)}
def order_document(order, items):
    # This is deliberately NOT a fiscal invoice. Legal placeholders alone cannot
    # replace immutable invoice numbering, tax calculation and legal review.
    presented_items = [{**item, 'image_url': permitted_image(item.get('image_url'))} for item in items]
    return {'document_type':'order_summary', 'invoice_issued':False, 'notice':'Récapitulatif de commande — ne constitue pas une facture fiscale', 'issuer':legal_configuration(), 'legal_ready':legal_ready(), 'order_number':order['order_number'], 'created_at':order['created_at'], 'currency':order['currency'], 'customer_name':order.get('customer_name'), 'billing_address':order.get('billing_address') or {}, 'items':presented_items, 'subtotal_cents':order['subtotal_cents'], 'shipping_amount_cents':order['shipping_amount_cents'], 'tax_amount_cents':order['tax_amount_cents'], 'total_cents':order['total_cents']}
