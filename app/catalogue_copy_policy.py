"""Conservative local copy overlay; never validates a product or writes catalogue data.

An exact product UUID, slug and previous field value are required. Later edits
take priority, and fields outside editorial names/descriptions are prohibited.
"""
import json
from pathlib import Path

REVIEW = json.loads((Path(__file__).parent / 'data/catalogue_copy_review_20261022.json').read_text(encoding='utf-8'))
ALLOWED_FIELDS = frozenset({'name', 'description'})


def _validated_changes(review: dict) -> dict:
    changes = {}
    product_ids = set()
    for change in review['changes']:
        slug, product_id = change['slug'], change['id']
        if not slug or not product_id or slug in changes or product_id in product_ids:
            raise ValueError('Editorial review requires unique product UUIDs and slugs')
        if not change['fields'] or not set(change['fields']) <= ALLOWED_FIELDS:
            raise ValueError('Editorial corrections cannot change price, procurement or validation')
        for correction in change['fields'].values():
            if (not isinstance(correction.get('before'), str)
                    or not isinstance(correction.get('after'), str)
                    or not correction['after'].strip()
                    or not correction.get('reason') or not correction.get('proof')):
                raise ValueError('Editorial corrections require text, reason and evidence')
        changes[slug] = change
        product_ids.add(product_id)
    return changes


CHANGES = _validated_changes(REVIEW)


def reviewed_product_copy(product: dict) -> dict:
    change = CHANGES.get(product.get('slug'))
    if not change or product.get('id') != change['id']:
        return product
    result = product
    for field, correction in change['fields'].items():
        if product.get(field) == correction['before']:
            if result is product:
                result = dict(product)
            result[field] = correction['after']
    return result
