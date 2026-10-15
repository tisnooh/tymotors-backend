"""Conservative catalogue candidates, not a purchase/fitment authorization."""
from typing import Any

from app.schemas import VehicleSelection


def _normal(value: str | None) -> str:
    return (value or "").strip().casefold()


def matches_verified_vehicle(product: dict[str, Any], vehicle: VehicleSelection) -> bool:
    """All known criteria must match ONE verified, generation-specific rule.

    Unknown optional vehicle details may leave a candidate to confirm later.
    Missing product/rule verification never becomes a personalized suggestion.
    """
    if product.get("is_verified") is not True or not all(
        _normal(value) for value in (vehicle.brand_slug, vehicle.model, vehicle.chassis)
    ):
        return False
    for rule in product.get("compatibilities") or []:
        if rule.get("is_verified") is not True:
            continue
        if _normal(rule.get("brand_slug")) != _normal(vehicle.brand_slug):
            continue
        if _normal(rule.get("model")) != _normal(vehicle.model):
            continue
        if _normal(vehicle.chassis) not in {
            _normal(rule.get("chassis")), _normal(rule.get("generation"))
        }:
            continue
        if vehicle.year is not None:
            if rule.get("year_from") is not None and vehicle.year < rule["year_from"]:
                continue
            if rule.get("year_to") is not None and vehicle.year > rule["year_to"]:
                continue
        if vehicle.body_type and rule.get("body_types") and _normal(vehicle.body_type) not in {
            _normal(value) for value in rule["body_types"]
        }:
            continue
        if vehicle.trim:
            if _normal(vehicle.trim) in {_normal(value) for value in rule.get("excluded_trims", [])}:
                continue
            if rule.get("required_trim") and _normal(vehicle.trim) not in {
                _normal(value) for value in rule["required_trim"]
            }:
                continue
        if vehicle.has_camera is True and rule.get("camera_compatible") is False:
            continue
        if vehicle.has_parking_sensors is True and rule.get("parking_sensor_compatible") is False:
            continue
        return True
    return False
