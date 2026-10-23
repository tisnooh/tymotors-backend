"""The strict catalogue route must not silently discard a supplied facelift."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def phase_client(monkeypatch):
    product = {
        'id': 'phase-fixture', 'slug': 'phase-fixture', 'sku': 'PHASE-FIXTURE',
        'name': 'Fixture', 'subtitle': '', 'category_slug': 'exterior',
        'status': 'draft', 'featured': False, 'stock': 0, 'price': 1,
        'compatible_brands': ['bmw'], 'is_verified': True,
        'compatibilities': [{
            'brand_slug': 'bmw', 'model': 'Série 3', 'chassis': 'F30',
            'year_from': 2013, 'year_to': 2018, 'facelift': 'lci',
            'is_verified': True,
        }],
    }
    monkeypatch.setattr(server.catalog, 'product_rows', AsyncMock(return_value=[]))
    monkeypatch.setattr(server.catalog, 'hydrate_products',
                        AsyncMock(return_value=deepcopy([product])))
    return TestClient(server.app)


@pytest.mark.parametrize('phase,expected', [('lci', 1), ('pre-lci', 0), ('unknown', 0), (None, 0)])
def test_strict_route_transmits_phase_and_keeps_unknown_unconfirmed(phase_client, phase, expected):
    params = dict(preview=True, strict_vehicle=True, brand='bmw', model='Série 3',
                  chassis='F30', year=2016)
    if phase is not None:
        params['facelift'] = phase
    response = phase_client.get('/api/products', params=params)
    assert response.status_code == 200
    assert response.json()['total'] == expected
    assert response.json()['fitment_scope'] == 'verified_vehicle'


def test_strict_route_rejects_unknown_phase_vocabulary(phase_client):
    response = phase_client.get('/api/products', params=dict(
        preview=True, strict_vehicle=True, brand='bmw', model='Série 3',
        chassis='F30', year=2016, facelift='any-phase',
    ))
    assert response.status_code == 422
