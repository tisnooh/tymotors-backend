import asyncio
from functools import wraps
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas import CartItemInput, CartUpdateInput, ProductCompatibility, ProductInput
from app.store import CatalogStore

PRODUCT = '10000000-0000-4000-8000-000000000010'
RULE = '10000000-0000-4000-8000-000000000011'
OTHER = '10000000-0000-4000-8000-000000000012'
ACTOR = '10000000-0000-4000-8000-000000000001'
STAMP = '2026-10-23T12:00:00Z'


def run_async(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return wrapped


def fixture():
    external = ProductCompatibility(brand_slug='bmw', model='Series 3', chassis='F30',
                                    generation='F30', is_verified=True).model_dump(mode='json')
    raw = dict(id=RULE, product_id=PRODUCT, brand_id=OTHER, vehicle_model_id=None,
               generation_id=None, model_name='Series 3', chassis='F30', generation_name='F30',
               year_from=None, year_to=None, body_types=[], facelift='unknown', required_trims=[],
               excluded_trims=[], camera_compatible=None, parking_sensor_compatible=None,
               notes=None, verification_state='verified', verified_by=ACTOR, verified_at=STAMP,
               created_at=STAMP, updated_at=STAMP)
    payload = dict(slug='fixture-product', sku='FIXTURE', name='Edited title',
                   description='Description changed without modifying fitment.', price=10,
                   category_slug='exterior', compatibilities=[external])
    current = dict(id=PRODUCT, compatibilities=[dict(external, id=RULE)])
    db = type('DB', (), {})()
    db.select = AsyncMock(return_value=[raw])
    db.rpc = AsyncMock(return_value=PRODUCT)
    store = CatalogStore(db)
    store._category_id = AsyncMock(return_value=OTHER)
    store._brand_id = AsyncMock(return_value=OTHER)
    store._vehicle_ids = AsyncMock(return_value=(None, None))
    store.product_by = AsyncMock(return_value=current)
    return store, db, payload, raw, current


@run_async
@pytest.mark.parametrize('send_id', [False, True])
async def test_unchanged_rules_preserve_id_raw_foreign_keys_and_evidence(send_id):
    store, db, payload, raw, _ = fixture()
    if send_id:
        payload['compatibilities'][0]['id'] = RULE
    await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                     product_id=PRODUCT, expected_updated_at=STAMP)
    rpc = db.rpc.call_args.args[1]
    assert rpc['p_rules'] == [raw]
    assert rpc['p_expected'] == STAMP
    assert rpc['p_base']['name'] == 'Edited title'
    store._brand_id.assert_not_awaited()
    store._vehicle_ids.assert_not_awaited()


@run_async
async def test_changed_rule_with_explicit_id_keeps_identity_and_requests_update():
    store, db, payload, _, _ = fixture()
    payload['compatibilities'][0].update(id=RULE, notes='Updated verified fitting restriction')
    await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                     product_id=PRODUCT, expected_updated_at=STAMP)
    rule = db.rpc.call_args.args[1]['p_rules'][0]
    assert rule['id'] == RULE
    assert rule['notes'] == 'Updated verified fitting restriction'
    assert rule['verified_by'] == ACTOR
    store._brand_id.assert_awaited_once()


@run_async
async def test_changed_legacy_rule_is_not_arbitrarily_reassigned():
    store, db, payload, _, _ = fixture()
    payload['compatibilities'][0]['chassis'] = 'F31'
    await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                     product_id=PRODUCT, expected_updated_at=STAMP)
    assert 'id' not in db.rpc.call_args.args[1]['p_rules'][0]


@run_async
async def test_foreign_rule_id_is_rejected_before_rpc():
    store, db, payload, _, _ = fixture()
    payload['compatibilities'][0]['id'] = OTHER
    with pytest.raises(ValueError, match='does not belong'):
        await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                         product_id=PRODUCT, expected_updated_at=STAMP)
    db.rpc.assert_not_awaited()


@run_async
async def test_duplicate_rule_id_is_rejected():
    store, db, payload, _, _ = fixture()
    payload['compatibilities'] *= 2
    with pytest.raises(ValueError, match='Duplicate compatibility ID'):
        await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                         product_id=PRODUCT, expected_updated_at=STAMP)
    db.rpc.assert_not_awaited()


@run_async
async def test_ambiguous_identical_legacy_rules_require_explicit_identity():
    store, db, payload, raw, current = fixture()
    current['compatibilities'].append(dict(current['compatibilities'][0], id=OTHER))
    db.select.return_value = [raw, dict(raw, id=OTHER)]
    with pytest.raises(ValueError, match='Ambiguous legacy compatibility'):
        await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR,
                                         product_id=PRODUCT, expected_updated_at=STAMP)
    db.rpc.assert_not_awaited()


@run_async
async def test_create_cannot_claim_existing_rule_identity():
    store, db, payload, _, _ = fixture()
    payload['compatibilities'][0]['id'] = RULE
    with pytest.raises(ValueError, match='does not belong'):
        await store.write_product_atomic(ProductInput.model_validate(payload), actor=ACTOR)
    db.rpc.assert_not_awaited()


@run_async
async def test_nonatomic_existing_product_path_is_disabled():
    store, db, payload, _, _ = fixture()
    with pytest.raises(ValueError, match='atomic product writer'):
        await store.write_product(ProductInput.model_validate(payload), product_id=PRODUCT)
    db.select.assert_not_awaited()


def test_identity_schema_is_uuid_and_legacy_cart_payloads_still_work():
    assert CartItemInput(product_id=PRODUCT).variant_id is None
    assert CartUpdateInput(product_id=PRODUCT, quantity=1).cart_item_id is None
    assert str(CartItemInput(product_id=PRODUCT, variant_id=RULE).variant_id) == RULE
    assert str(CartUpdateInput(product_id=PRODUCT, cart_item_id=RULE, quantity=1).cart_item_id) == RULE
    with pytest.raises(ValidationError):
        ProductCompatibility(brand_slug='bmw', id='not-a-uuid')
