from copy import deepcopy

import pytest

from app.compatibility import check_compatibility
from app.schemas import VehicleSelection


def product(**rule_overrides):
    return {"is_verified": True, "compatible_brands": ["bmw"], "compatibilities": [{
        "brand_slug": "bmw", "model": "Série 3", "chassis": "F30",
        "generation": "F30 / F35", "year_from": 2013, "year_to": 2019,
        "is_verified": True, **rule_overrides,
    }]}


def result(item, **selection):
    return check_compatibility(item, VehicleSelection(
        **{"brand_slug": "bmw", "model": "Série 3", "chassis": "F30", "year": 2016, **selection}
    ))["status"]


@pytest.mark.parametrize("rule", [
    {"body_types": ["Berline"]}, {"required_trim": ["M Sport"]},
    {"excluded_trims": ["M3"]}, {"camera_compatible": False},
    {"parking_sensor_compatible": True}, {"facelift": "pre-lci"},
    {"model": None}, {"chassis": None}, {"year_from": None, "year_to": None},
    {"year_from": None}, {"year_to": None},
])
def test_incomplete_required_facts_never_confirm_fitment(rule):
    assert result(product(**rule)) == "confirm"


@pytest.mark.parametrize("rule,selection", [
    ({"body_types": ["Berline"]}, {"body_type": "Touring"}),
    ({"required_trim": ["M Sport"]}, {"trim": "Standard"}),
    ({"excluded_trims": ["M3"]}, {"trim": "M3"}),
    ({"camera_compatible": False}, {"has_camera": True}),
    ({"parking_sensor_compatible": False}, {"has_parking_sensors": True}),
    ({"facelift": "pre-lci"}, {"facelift": "lci"}),
    ({}, {"year": 2012}), ({}, {"chassis": "F31"}),
])
def test_known_exclusions_do_not_match(rule, selection):
    assert result(product(**rule), **selection) == "incompatible"


def test_constraints_must_be_met_on_one_rule():
    item = product(body_types=["Berline"], required_trim=["M Sport"],
                   camera_compatible=False, parking_sensor_compatible=True, facelift="lci")
    assert result(item, body_type="Berline", trim="M Sport", has_camera=False,
                  has_parking_sensors=True, facelift="lci") == "compatible"


def test_known_equipment_with_undocumented_support_needs_confirmation():
    assert result(product(), has_camera=True) == "confirm"
    assert result(product(), has_parking_sensors=True) == "confirm"


def test_grouped_generation_does_not_identify_one_chassis():
    assert result(product(), chassis="F30 / F35") == "confirm"
    assert result(product(), chassis="F35") == "incompatible"


def test_later_verified_rule_wins_over_unverified_candidate():
    item = product(is_verified=False)
    item["compatibilities"].append(deepcopy(product()["compatibilities"][0]))
    assert result(item) == "compatible"


def test_unverified_source_cannot_prove_an_exclusion():
    assert result(product(is_verified=False), year=2012) == "confirm"


def test_no_rule_is_not_a_brand_wide_approval():
    item = {"is_verified": True, "compatible_brands": ["bmw"], "compatibilities": []}
    assert result(item) == "unknown"


def test_draft_product_never_becomes_verified_from_a_rule():
    item = product()
    item["is_verified"] = False
    assert result(item) == "confirm"


@pytest.mark.parametrize("notes", [
    "WITHOUT ACC only", "Pare-chocs M Sport, sorties d'échappement à vérifier",
    "Connecteur d'origine obligatoire", "Montage conforme à la notice fournisseur",
])
def test_free_text_conditions_cannot_be_silently_ignored(notes):
    item = product(notes=notes)
    response = check_compatibility(item, VehicleSelection(
        brand_slug="bmw", model="Série 3", chassis="F30", year=2016,
    ))
    assert response["status"] == "confirm"
    assert "vérification manuelle" in response["reason"]
    assert response["compatibility"]["notes"] == notes


def test_whitespace_notes_are_not_constraints():
    assert result(product(notes="  ")) == "compatible"


@pytest.mark.parametrize("value", ["true", "false", 1])
def test_truthy_verification_values_are_not_verified_booleans(value):
    assert result(product(is_verified=value)) == "confirm"
    item = product()
    item["is_verified"] = value
    assert result(item) == "confirm"


def test_grouped_rule_chassis_cannot_authorize_grouped_vehicle():
    for chassis in ("F30 / F35", "F30,F35", "F30;F35", "F30|F35",
                    "F30 + F35", "F30 & F35", "F30 et F35", "F30 ou F35",
                    "F30 and F35", "F30 OR F35"):
        assert result(product(chassis=chassis), chassis=chassis) == "confirm"
        assert result(product(chassis=chassis), chassis="F30") == "confirm"


def test_precise_generation_alias_is_resolved_by_the_final_checker_without_mutation():
    item = product(chassis=None, generation=" f30 ")
    original = deepcopy(item)
    assert result(item) == "compatible"
    assert item == original


def test_precise_generation_alias_does_not_infer_a_missing_model():
    assert result(product(chassis=None, generation="F30", model=None)) == "confirm"


def test_a_manual_candidate_does_not_hide_a_later_fully_checked_rule():
    item = product(notes="ACC à vérifier manuellement")
    item["compatibilities"].append(deepcopy(product()["compatibilities"][0]))
    assert result(item) == "compatible"
