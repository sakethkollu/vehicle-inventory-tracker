"""Mazda inventory location / stage mapping from search + detail APIs."""

from __future__ import annotations

from typing import Optional, Tuple

# From Mazda inventory search Filters.VehicleLocation
MAZDA_VEHICLE_LOCATION_LABELS = {
    "01": "In Transit",
    "02": "At Dealership",
}


def _normalize_code(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.isdigit() and len(raw) == 1:
        return f"0{raw}"
    return raw


def resolve_mazda_allocation_stage(
    *,
    vehicle_location: object = None,
    detail_location: object = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Return (allocation_stage_code, allocation_stage_label) for Mazda vehicles."""
    code = _normalize_code(vehicle_location)
    if not code and isinstance(detail_location, dict):
        code = _normalize_code(detail_location.get("Code"))
    if not code:
        return None, None
    label = MAZDA_VEHICLE_LOCATION_LABELS.get(code, code)
    return code, label
