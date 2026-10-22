import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.product_image_policy import image_usage_denied, permitted_image, SCP_PUBLIC_IDS
from app.schemas import ProductInput
from app.store import CatalogStore
from app.services.email_templates import _order_summary

ROOT = Path(__file__).parents[2]
DENIED = 'https://res.cloudinary.com/dwsyixjux/image/upload/v1787842804/tymotors/products/hvtqoa2mfv40mn2gy1ww.png'
ALLOWED = 'https://example.com/authorized-replacement.webp'


@pytest.mark.parametrize('source', [
    DENIED, DENIED + '?v=1', DENIED + '#preview',
    DENIED.replace('/upload/', '/upload/c_scale,w_40/').replace('.png', '.webp'),
    'https://res.cloudinary.com/dwsyixjux/image/upload/v1/tymotors/products/o5ylil1cryn4uertnc89.webp',
    'https://RES.CLOUDINARY.COM/dwsyixjux/image/upload/v1/tymotors/products/ckvfckn89wcdd9fzaegj.jpg',
    'https://scpautomotive.co.uk/cdn/shop/files/BMW.jpg?width=100',
    'https://www.scpautomotive.co.uk/cdn/shop/files/BMW.jpg',
    'https://cdn.shopify.com/s/files/1/0/BMW-LED-Door-Projector-_Pair_-BMW-Logo-SCP-Automotive-90141840_200x.jpg',
])
def test_denied_assets_and_known_variants_are_never_presented(source):
    assert image_usage_denied(source)
    assert permitted_image(source) is None


@pytest.mark.skipif(not (ROOT / 'frontend/src/data/productPhotoRestrictions.json').exists(),
                    reason='Frontend is a separate repository; cross-repository parity requires both checkouts')
def test_server_and_client_restriction_registries_agree():
    client = json.loads((ROOT / 'frontend/src/data/productPhotoRestrictions.json').read_text(encoding='utf-8'))
    assert set(client['restrictions'][0]['cloudinaryPublicIds']) == SCP_PUBLIC_IDS
    for source in client['restrictions'][0]['images']:
        assert image_usage_denied(source)
    assert permitted_image(ALLOWED) == ALLOWED
    assert permitted_image(None) is None


@pytest.mark.parametrize('status', ['draft', 'active', 'archived'])
def test_product_input_rejects_reintroducing_declined_photos(status):
    with pytest.raises(ValidationError, match='Image use denied'):
        ProductInput.model_validate(dict(
            slug='projecteur-bmw', sku='TEST-BMW', name='Projecteur BMW',
            description='Description de contrôle suffisamment longue.',
            price=39, category_slug='technology', images=[DENIED], status=status,
        ))


@pytest.mark.parametrize('admin', [False, True])
def test_catalogue_hydration_filters_both_photo_fields_without_mutating_evidence(admin):
    photos = [{'product_id': 'one', 'url': DENIED}, {'product_id': 'one', 'url': ALLOWED}]
    before = deepcopy(photos)

    class FakeDb:
        async def select(self, table, **_kwargs):
            return {'categories': [{'id': 'cat', 'slug': 'technology'}],
                    'product_images': photos}.get(table, [])

    row = {'id': 'one', 'slug': 'bmw-logo-door-projectors', 'sku': 'TEST',
           'name': 'Projecteurs BMW', 'category_id': 'cat', 'price_cents': 3900}
    result = asyncio.run(CatalogStore(FakeDb()).hydrate_products([row], include_admin=admin))[0]
    assert result['images'] == [ALLOWED]
    assert result['image_records'] == [photos[1]]
    assert photos == before


def test_historical_order_email_omits_denied_picture_without_changing_order():
    items = [{'product_name': 'Projecteur', 'quantity': 1, 'unit_amount_cents': 3900, 'image_url': DENIED}]
    before = deepcopy(items)
    html, _ = _order_summary({'currency': 'EUR'}, items)
    assert DENIED not in html
    assert '<img' not in html
    assert items == before


def test_historical_order_document_omits_declined_image_without_rewriting_snapshot():
    from app.site_config import order_document
    order = dict(order_number='QA-ONLY', created_at='2026-10-22', currency='EUR',
                 subtotal_cents=3900, shipping_amount_cents=0, tax_amount_cents=0, total_cents=3900)
    items = [{'product_name': 'Projecteur', 'image_url': DENIED}, {'image_url': ALLOWED}]
    before = deepcopy(items)
    document = order_document(order, items)
    assert document['items'][0]['image_url'] is None
    assert document['items'][1]['image_url'] == ALLOWED
    assert items == before


def test_reimport_of_known_denied_binary_is_rejected_before_any_cloud_upload(monkeypatch):
    import server
    import hashlib
    import app.product_image_policy as policy
    from fastapi import HTTPException
    from app.product_image_policy import image_bytes_usage_denied
    # Synthetic bytes registered as denied for this isolated test. Do not commit
    # a refused supplier photo or depend on ignored local research archives.
    content = b'\x89PNG\r\n\x1a\n' + b'synthetic-local-policy-fixture'
    monkeypatch.setattr(policy, 'DENIED_IMAGE_HASHES', frozenset({hashlib.sha256(content).hexdigest()}))
    assert image_bytes_usage_denied(content)
    called = []
    monkeypatch.setattr(server.cloudinary.uploader, 'upload', lambda *args, **kwargs: called.append(True))

    class FakeUpload:
        content_type = 'image/png'

        async def read(self, size):
            return content[:size]

    with pytest.raises(HTTPException) as failure:
        asyncio.run(server.upload_image(file=FakeUpload(), admin={'id': 'local-test-admin'}))
    assert failure.value.status_code == 422
    assert called == []
    assert not image_bytes_usage_denied(b'unrelated-new-image-content')


def test_old_gallery_generator_skips_denied_input_before_reading_the_photo():
    # Exercise its pure selector without requiring the optional Pillow editor.
    import ast
    script = (Path(__file__).parents[1] / 'scripts/build_catalogue_context_gallery.py').read_text(encoding='utf-8')
    selector = next(node for node in ast.parse(script).body if isinstance(node, ast.FunctionDef) and node.name == 'publishable_slugs')
    namespace = {'image_usage_denied': image_usage_denied}
    exec(compile(ast.Module(body=[selector], type_ignores=[]), '<gallery-selector>', 'exec'), namespace)
    manifest = {'images': [{'product_slug': 'denied', 'delivery_url': DENIED},
                           {'product_slug': 'permitted', 'delivery_url': ALLOWED}]}
    assert namespace['publishable_slugs'](manifest) == ['permitted']
