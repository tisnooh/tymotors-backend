"""Conservative catalogue candidates, not a purchase/fitment authorization."""
from typing import Any

from app.compatibility import check_compatibility
from app.schemas import VehicleSelection


def _normal(value: str | None) -> str:
    return (value or "").strip().casefold()


def matches_verified_vehicle(product: dict[str, Any], vehicle: VehicleSelection) -> bool:
    """Only return products the fitment checker can actually confirm.

    This strict endpoint must not label candidates with missing requirements as
    verified_vehicle. Free-text conditions remain a manual confirmation gate.
    """
    if product.get("is_verified") is not True or not all(
        _normal(value) for value in (vehicle.brand_slug, vehicle.model, vehicle.chassis)
    ):
        return False
    for rule in product.get("compatibilities") or []:
        result = check_compatibility({**product, "compatibilities": [rule]}, vehicle)
        if result["status"] == "compatible":
            return True
    return False
