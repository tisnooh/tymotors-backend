from __future__ import annotations

from typing import Any

from app.schemas import VehicleSelection


def _n(value: str | None) -> str:
    return (value or "").strip().casefold()


def check_compatibility(product: dict[str, Any], vehicle: VehicleSelection) -> dict[str, Any]:
    rules = product.get("compatibilities") or []
    if not rules:
        legacy = _n(vehicle.brand_slug) in {_n(v) for v in product.get("compatible_brands", [])}
        return {
            "status": "unknown" if legacy else "incompatible",
            "reason": "Compatibilité détaillée manquante" if legacy else "Marque non prévue pour ce produit",
        }
    brand_rules = [rule for rule in rules if _n(rule.get("brand_slug")) == _n(vehicle.brand_slug)]
    if not brand_rules:
        return {"status": "incompatible", "reason": "Marque non compatible"}
    incomplete = not vehicle.model or not vehicle.chassis or vehicle.year is None
    for rule in brand_rules:
        if rule.get("model") and vehicle.model and _n(rule["model"]) != _n(vehicle.model): continue
        if rule.get("chassis") and vehicle.chassis and _n(vehicle.chassis) not in {_n(rule.get("chassis")), _n(rule.get("generation"))}: continue
        if vehicle.year is not None and rule.get("year_from") and vehicle.year < rule["year_from"]: continue
        if vehicle.year is not None and rule.get("year_to") and vehicle.year > rule["year_to"]: continue
        if vehicle.body_type and rule.get("body_types") and _n(vehicle.body_type) not in {_n(v) for v in rule["body_types"]}: continue
        if vehicle.trim and _n(vehicle.trim) in {_n(v) for v in rule.get("excluded_trims", [])}: continue
        if rule.get("required_trim") and (not vehicle.trim or _n(vehicle.trim) not in {_n(v) for v in rule["required_trim"]}): continue
        if vehicle.has_camera and rule.get("camera_compatible") is False: continue
        if vehicle.has_parking_sensors and rule.get("parking_sensor_compatible") is False: continue
        if incomplete or not product.get("is_verified") or not rule.get("is_verified"):
            return {"status": "confirm", "reason": "Compatibilité à faire confirmer par TYMotors", "compatibility": rule}
        return {"status": "compatible", "reason": rule.get("notes") or "Véhicule conforme aux critères vérifiés", "compatibility": rule}
    return {"status": "incompatible", "reason": "Le véhicule sélectionné ne correspond pas aux critères du produit"}
