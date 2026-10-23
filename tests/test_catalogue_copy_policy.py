from copy import deepcopy
import pytest

from app.catalogue_copy_policy import REVIEW, _validated_changes, reviewed_product_copy


def test_only_eight_reviewed_titles_and_two_descriptions_change_without_prices_or_validation():
    assert len(REVIEW['changes']) == 9
    assert sum('name' in c['fields'] for c in REVIEW['changes']) == 8
    assert sum('description' in c['fields'] for c in REVIEW['changes']) == 2
    assert all(set(c['fields']) <= {'name', 'description'} for c in REVIEW['changes'])
    for change in REVIEW['changes']:
        product = {'id': change['id'], 'slug': change['slug'], 'price': 39, 'is_verified': False,
                   **{field: correction['before'] for field, correction in change['fields'].items()}}
        original = deepcopy(product)
        edited = reviewed_product_copy(product)
        for field, correction in change['fields'].items():
            assert edited[field] == correction['after']
        assert edited['price'] == 39
        assert edited['is_verified'] is False
        assert product == original


def test_later_catalogue_edits_and_different_identities_always_take_priority():
    for change in REVIEW['changes']:
        product = {'id': change['id'], 'slug': change['slug'], 'name': 'Later reviewed name', 'description': 'Later reviewed description'}
        assert reviewed_product_copy(product) is product
        reused_slug = {'id': 'different-product-id', 'slug': change['slug'], **{key: value['before'] for key, value in change['fields'].items()}}
        assert reviewed_product_copy(reused_slug) is reused_slug
    assert 'porsche-911-diffuser-black' not in {c['slug'] for c in REVIEW['changes']}


def test_synthetic_forty_product_catalogue_preserves_non_editorial_data_and_input():
    # CI must not depend on private supplier/audit dossiers. Exact correction
    # identities are public catalogue data; remaining products are synthetic.
    items = [
        {'id': change['id'], 'slug': change['slug'],
         **{field: correction['before'] for field, correction in change['fields'].items()}}
        for change in REVIEW['changes']
    ]
    items.extend({'id': f'fixture-{index}', 'slug': f'unrelated-{index}',
                  'name': 'Unrelated item', 'description': 'Already reviewed'}
                 for index in range(40 - len(items)))
    for item in items:
        item.update(price=99, stock=0, is_verified=False, status='draft',
                    compatibilities=[], delivery_estimate=None, warranty_months=None)
    assert len(items) == 40
    assert len({item['id'] for item in items}) == 40
    assert len({item['slug'] for item in items}) == 40
    changed = []
    for item in items:
        before = deepcopy(item)
        after = reviewed_product_copy(item)
        assert item == before
        assert {key: value for key, value in after.items() if key not in {'name', 'description'}} == {
            key: value for key, value in before.items() if key not in {'name', 'description'}
        }
        if after != before:
            changed.append(item['slug'])
        assert reviewed_product_copy(after) is after
    assert len(changed) == 9


def test_porsche_spoiler_does_not_imply_a_complete_kit_or_reinstate_unsupported_features():
    change = next(c for c in REVIEW['changes'] if c['slug'] == 'porsche-911-rear-spoiler')
    text = change['fields']['description']['after']
    assert not text.startswith('Un ensemble')
    assert 'ne sont pas documentées' in text
    assert 'La compatibilité 991' in text
    assert 'ne constitue pas une preuve de montage' in text


def test_guard_is_field_specific_when_only_one_later_value_has_changed():
    change = next(c for c in REVIEW['changes'] if c['slug'] == 'dashcam-4k-pro')
    product = {'id': change['id'], 'slug': change['slug'],
               'name': 'Later exact-SKU reviewed name',
               'description': change['fields']['description']['before']}
    result = reviewed_product_copy(product)
    assert result['name'] == product['name']
    assert result['description'] == change['fields']['description']['after']


@pytest.mark.parametrize('field', ['price', 'price_cents', 'stock', 'supplier', 'compatibilities',
                                  'is_verified', 'status', 'delivery_estimate', 'warranty_months'])
def test_prohibited_fields_are_rejected_when_loading_a_review(field):
    review = deepcopy(REVIEW)
    review['changes'][0]['fields'][field] = {
        'before': 'old', 'after': 'new', 'reason': 'not authorized', 'proof': ['not enough']}
    with pytest.raises(ValueError, match='cannot change'):
        _validated_changes(review)


def test_duplicate_products_and_missing_proof_are_rejected():
    review = deepcopy(REVIEW)
    review['changes'].append(deepcopy(review['changes'][0]))
    with pytest.raises(ValueError, match='unique'):
        _validated_changes(review)
    review = deepcopy(REVIEW)
    review['changes'][0]['fields']['description']['proof'] = []
    with pytest.raises(ValueError, match='evidence'):
        _validated_changes(review)
