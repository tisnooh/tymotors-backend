from __future__ import annotations

import re
from typing import Any

from app.schemas import VehicleSelection


_GROUPED_CHASSIS = re.compile(r"[/,;|+&]|\b(?:et|ou|and|or)\b", re.IGNORECASE)


def _n(value: str | None) -> str:
    return (value or "").strip().casefold()


def _precise_chassis(value: str | None) -> bool:
    """A grouped generation is not an identified vehicle chassis."""
    normalized = _n(value)
    return bool(normalized) and _GROUPED_CHASSIS.search(normalized) is None


def _normalized_rule_chassis(rule: dict[str, Any]) -> dict[str, Any]:
    """Resolve only a precise documented generation alias, without mutation."""
    normalized = dict(rule)
    if not _n(normalized.get("chassis")) and _precise_chassis(normalized.get("generation")):
        normalized["chassis"] = normalized["generation"]
    return normalized


def check_compatibility(product: dict[str, Any], vehicle: VehicleSelection) -> dict[str, Any]:
    """Never turn a brand, incomplete selection or unverified source into fitment proof."""
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
    confirmation = None
    for original_rule in brand_rules:
        rule = _normalized_rule_chassis(original_rule)
        incomplete = not _n(vehicle.model) or not _precise_chassis(vehicle.chassis) or vehicle.year is None
        # A brand-only rule must never authorize every model of that brand.
        incomplete = incomplete or not _n(rule.get("model")) or not _precise_chassis(rule.get("chassis"))
        if rule.get("model") and vehicle.model and _n(rule["model"]) != _n(vehicle.model): continue
        if _precise_chassis(rule.get("chassis")) and vehicle.chassis and _n(vehicle.chassis) != _n(rule["chassis"]):
            if _n(vehicle.chassis) == _n(rule.get("generation")):
                # A grouped generation (F30 / F35) does not identify one chassis.
                incomplete = True
            else:
                continue
        # An open-ended historical listing cannot authorize undemonstrated years.
        if rule.get("year_from") is None or rule.get("year_to") is None: incomplete = True
        if vehicle.year is not None and rule.get("year_from") is not None and vehicle.year < rule["year_from"]: continue
        if vehicle.year is not None and rule.get("year_to") is not None and vehicle.year > rule["year_to"]: continue
        if rule.get("body_types"):
            if not _n(vehicle.body_type): incomplete = True
            elif _n(vehicle.body_type) not in {_n(v) for v in rule["body_types"]}: continue
        if rule.get("required_trim") or rule.get("excluded_trims"):
            if not _n(vehicle.trim): incomplete = True
            elif _n(vehicle.trim) in {_n(v) for v in rule.get("excluded_trims", [])}: continue
            elif rule.get("required_trim") and _n(vehicle.trim) not in {_n(v) for v in rule["required_trim"]}: continue
        if rule.get("facelift") in {"pre-lci", "lci"}:
            if vehicle.facelift in {None, "unknown"}: incomplete = True
            elif vehicle.facelift != rule["facelift"]: continue
        equipment_mismatch = False
        for selected, supported in (
            (vehicle.has_camera, rule.get("camera_compatible")),
            (vehicle.has_parking_sensors, rule.get("parking_sensor_compatible")),
        ):
            if selected is True and supported is False: equipment_mismatch = True
            elif selected is True and supported is None: incomplete = True
            elif selected is None and supported is not None: incomplete = True
        if equipment_mismatch: continue
        # Notes can contain essential constraints (ACC, exhaust, connector, etc.)
        # that the persisted schema cannot evaluate. Do not interpret prose as
        # executable fitment evidence, even on an otherwise verified rule.
        manual_conditions = bool(_n(rule.get("notes")))
        if incomplete or manual_conditions or product.get("is_verified") is not True or rule.get("is_verified") is not True:
            reason = ("Compatibilité à faire confirmer par TYMotors : les conditions de montage en notes nécessitent une vérification manuelle"
                      if manual_conditions else
                      "Compatibilité à faire confirmer par TYMotors : référence, véhicule ou équipements insuffisamment documentés")
            confirmation = {"status": "confirm", "reason": reason, "compatibility": rule}
            continue
        return {"status": "compatible", "reason": rule.get("notes") or "Véhicule conforme aux critères vérifiés", "compatibility": rule}
    if confirmation:
        return confirmation
    if any(rule.get("is_verified") is not True for rule in brand_rules):
        return {"status": "confirm", "reason": "Aucun montage vérifié ne permet de conclure pour ce véhicule. Référence et variante à confirmer par TYMotors."}
    return {"status": "incompatible", "reason": "Le véhicule sélectionné ne correspond pas aux critères du produit"}
