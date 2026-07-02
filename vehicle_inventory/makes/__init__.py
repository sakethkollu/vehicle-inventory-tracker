"""OEM / make registry and adapters."""

from vehicle_inventory.makes.registry import (
    MakeProfile,
    all_image_host_suffixes,
    get_default_make_slug,
    get_make_adapter,
    get_make_profile,
    list_makes,
    resolve_database_url,
)

__all__ = [
    "MakeProfile",
    "all_image_host_suffixes",
    "get_default_make_slug",
    "get_make_adapter",
    "get_make_profile",
    "list_makes",
    "resolve_database_url",
]
