from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import server
from app.compatibility import check_compatibility
from app.schemas import VehicleSelection
from app.vehicle_catalog import matches_verified_vehicle


def vehicle(**overrides):
    return VehicleSelection(**{
        'brand_slug': 'mercedes-benz', 'model': 'Classe A', 'chassis': 'W177',
        'year': 2020, 'body_type': 'Berline', 'trim': 'AMG Line', **overrides,
    })


def rule(**overrides):
    return {'brand_slug': 'mercedes-benz', 'model': 'Classe A', 'chassis': 'W177',
            'year_from': 2018, 'year_to': 2022, 'body_types': ['Berline'],
            'required_trim': ['AMG Line'], 'is_verified': True, **overrides}


def product(**overrides):
    return {'id': 'fixture', 'slug': 'fixture', 'sku': 'FIXTURE', 'name': 'Fixture',
            'subtitle': '', 'category_slug': 'exterior', 'status': 'draft', 'featured': False,
            'stock': 0, 'price': 199, 'price_cents': 19900, 'compatible_brands': ['mercedes-benz'],
            'is_verified': True, 'compatibilities': [rule()], **overrides}


@pytest.mark.parametrize('overrides', [
    {'is_verified': False}, {'compatibilities': []},
    {'compatibilities': [rule(is_verified=False)]},
    {'compatibilities': [rule(chassis='W205', generation='W205', model='Classe C')]},
    {'compatibilities': [rule(chassis=None, generation='W205')]},
    {'compatibilities': [rule(chassis=None, generation=None)]},
    {'compatibilities': [rule(model=None)]},
    {'compatibilities': [rule(year_to=2019)]},
    {'compatibilities': [rule(year_from=2021)]},
    {'compatibilities': [rule(body_types=['Break'])]},
    {'compatibilities': [rule(required_trim=['Progressive'])]},
    {'compatibilities': [rule(excluded_trims=['AMG Line'])]},
])
def test_unverified_or_contradictory_products_are_not_personalized(overrides):
    assert not matches_verified_vehicle(product(**overrides), vehicle())


def test_one_rule_must_match_all_fields_not_a_union_of_incompatible_rules():
    item = product(compatibilities=[rule(model='Classe C'), rule(chassis='W205'),
                                   rule(year_to=2019), rule(body_types=['Break'])])
    assert not matches_verified_vehicle(item, vehicle())


def test_matching_is_exact_normalized_and_generation_alias_is_supported():
    item = product(compatibilities=[rule(chassis=None, generation=' w177 ', model=' classe a ')])
    assert matches_verified_vehicle(item, vehicle())
    assert not matches_verified_vehicle(product(compatibilities=[rule(chassis='W177 AMG')]), vehicle())


def test_unknown_required_details_are_not_labeled_verified_vehicle():
    assert not matches_verified_vehicle(product(), vehicle(year=None, body_type=None, trim=None))
    assert matches_verified_vehicle(product(), vehicle())
    assert not matches_verified_vehicle(product(compatibilities=[rule(camera_compatible=False)]), vehicle(has_camera=True))
    assert not matches_verified_vehicle(product(compatibilities=[rule(parking_sensor_compatible=False)]), vehicle(has_parking_sensors=True))


@pytest.mark.parametrize('selection', [
    {'year': None}, {'body_type': None}, {'trim': None},
    {'has_camera': True}, {'has_parking_sensors': True},
])
def test_strict_candidates_and_final_fitment_have_the_same_unknown_gates(selection):
    assert not matches_verified_vehicle(product(), vehicle(**selection))


@pytest.mark.parametrize('overrides', [
    {'notes': 'WITHOUT ACC only'}, {'year_from': None}, {'year_to': None},
    {'facelift': 'pre-lci'}, {'camera_compatible': False},
    {'parking_sensor_compatible': True},
])
def test_unresolved_rule_conditions_do_not_enter_verified_vehicle_scope(overrides):
    assert not matches_verified_vehicle(product(compatibilities=[rule(**overrides)]), vehicle())


def test_single_generation_alias_is_not_a_grouped_chassis_authorization():
    item = product(compatibilities=[rule(chassis=None, generation='W177 / V177')])
    assert not matches_verified_vehicle(item, vehicle(chassis='W177 / V177'))


@pytest.mark.parametrize('separator', ['/', ',', ';', '|', '+', '&', 'et', 'ou', 'and', 'OR'])
@pytest.mark.parametrize('location', ['chassis', 'generation'])
def test_grouped_identifiers_never_confirm_in_either_path(separator, location):
    grouped = f'W177 {separator} V177'
    overrides = {'chassis': grouped} if location == 'chassis' else {'chassis': None, 'generation': grouped}
    item = product(compatibilities=[rule(**overrides)])
    original = deepcopy(item)
    for selected_chassis in (grouped, 'W177'):
        selection = vehicle(chassis=selected_chassis)
        assert check_compatibility(item, selection)['status'] != 'compatible'
        assert not matches_verified_vehicle(item, selection)
    assert item == original


@pytest.mark.parametrize('chassis', ['W177', '9YA', '992.1', 'MQB-A0', 'KAND-A', 'SANDERO'])
def test_precise_alias_and_chassis_have_identical_confirmation_semantics(chassis):
    selection = vehicle(chassis=chassis)
    for overrides in ({'chassis': chassis}, {'chassis': None, 'generation': f' {chassis.lower()} '}):
        item = product(compatibilities=[rule(**overrides)])
        original = deepcopy(item)
        assert check_compatibility(item, selection)['status'] == 'compatible'
        assert matches_verified_vehicle(item, selection)
        assert item == original


@pytest.mark.parametrize('overrides', [
    {'chassis': None, 'generation': 'W177', 'model': None},
    {'chassis': None, 'generation': 'W177', 'brand_slug': None},
    {'chassis': None, 'generation': None},
    {'chassis': 'W177', 'notes': 'WITHOUT ACC only'},
])
def test_alias_normalization_does_not_bypass_missing_evidence_or_manual_conditions(overrides):
    item = product(compatibilities=[rule(**overrides)])
    selection = vehicle()
    assert check_compatibility(item, selection)['status'] != 'compatible'
    assert not matches_verified_vehicle(item, selection)


def test_confirmed_explicit_equipment_and_phase_are_accepted_without_mutation():
    item = product(compatibilities=[rule(facelift='pre-lci', camera_compatible=False)])
    original = deepcopy(item)
    assert matches_verified_vehicle(item, vehicle(facelift='pre-lci', has_camera=False))
    assert not matches_verified_vehicle(item, vehicle(facelift='lci', has_camera=False))
    assert item == original


def mock_catalog(monkeypatch, products):
    monkeypatch.setattr(server.catalog, 'product_rows', AsyncMock(return_value=[]))
    monkeypatch.setattr(server.catalog, 'hydrate_products', AsyncMock(return_value=deepcopy(products)))


def test_strict_api_filters_before_pagination_and_preserves_general_demo_shop(monkeypatch):
    previews = [product(id='legacy', is_verified=False, compatibilities=[]),
                product(id='w205', compatibilities=[rule(chassis='W205')])]
    matches = [product(id=f'w177-{index}') for index in range(13)]
    mock_catalog(monkeypatch, previews + matches)
    client = TestClient(server.app)
    params = {'preview': True, 'brand': 'mercedes-benz', 'model': 'Classe A', 'chassis': 'W177',
              'year': 2020, 'body_type': 'Berline', 'trim': 'AMG Line',
              'strict_vehicle': True, 'limit': 12, 'page': 2, 'category': 'performance'}
    response = client.get('/api/products', params=params)
    assert response.status_code == 200
    data = response.json()
    assert data['fitment_scope'] == 'verified_vehicle'
    assert data['total'] == 13 and data['pages'] == 2
    assert [item['id'] for item in data['items']] == ['w177-12']
    general = client.get('/api/products', params={'preview': True, 'brand': 'mercedes-benz', 'limit': 100}).json()
    assert general['total'] == 15
    assert 'fitment_scope' not in general


def test_strict_api_does_not_present_missing_required_details_as_verified(monkeypatch):
    mock_catalog(monkeypatch, [product()])
    response = TestClient(server.app).get('/api/products', params={
        'preview': True, 'strict_vehicle': True, 'brand': 'mercedes-benz',
        'model': 'Classe A', 'chassis': 'W177', 'year': 2020,
    })
    assert response.status_code == 200
    assert response.json()['items'] == []


def test_w177_api_does_not_suggest_w205_or_unqualified_demo_references(monkeypatch):
    mock_catalog(monkeypatch, [product(is_verified=False, compatibilities=[]),
                              product(compatibilities=[rule(chassis='W205')])])
    response = TestClient(server.app).get('/api/products', params={
        'preview': True, 'strict_vehicle': True, 'brand': 'mercedes-benz', 'model': 'Classe A',
        'chassis': 'W177', 'year': 2020, 'trim': 'AMG Line', 'has_camera': False,
    })
    assert response.status_code == 200
    assert response.json() == {'items': [], 'total': 0, 'page': 1, 'limit': 24,
                               'pages': 0, 'fitment_scope': 'verified_vehicle'}


@pytest.mark.parametrize('params', [{}, {'brand': 'mercedes-benz'},
    {'brand': 'INVALID', 'model': 'Classe A', 'chassis': 'W177'},
    {'brand': 'mercedes-benz', 'model': ' ', 'chassis': 'W177'}])
def test_strict_api_requires_a_valid_precise_vehicle(monkeypatch, params):
    mock_catalog(monkeypatch, [product()])
    response = TestClient(server.app).get('/api/products', params={**params, 'strict_vehicle': True})
    assert response.status_code == 422
