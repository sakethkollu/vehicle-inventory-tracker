"""Mazda exterior color hex resolution (from mazdausa.com vehicle pages)."""

from __future__ import annotations

import re
from typing import Optional

# Slug -> hex (no leading #), scraped from Mazda vehicle configurator pages.
MAZDA_EXTERIOR_COLOR_HEX: dict[str, str] = {
    "aero_gray": "F4F4F4",
    "artisan_red": "8F1D26",
    "ceramic_metallic": "acb0b2",
    "deep_crystal": "273754",
    "ingot_blue_metallic": "4d7fa6",
    "jet_black": "101312",
    "machine_gray": "4f535b",
    "melting_copper_metallic": "323337",
    "platinum_quartz": "b2b0a1",
    "polymetal_gray": "747d81",
    "rhodium_white_premium": "FFFFFF",
    "snowflake_white_pearl": "FFFFFF",
    "snowflake_white_pearl_mica": "FFFFFF",
    "soul_red": "890000",
    "wind_chill_pearl": "FFFFFF",
    "zircon_sand_metallic": "b2b0a1",
}

# Inventory marketing names that do not slug-match configurator keys exactly.
MAZDA_EXTERIOR_COLOR_ALIASES: dict[str, str] = {
    "rhodium_white_metallic": "rhodium_white_premium",
    "rhodium_white": "rhodium_white_premium",
    "soul_red_crystal_metallic": "soul_red",
    "soul_red_crystal": "soul_red",
    "deep_crystal_blue_mica": "deep_crystal",
    "deep_crystal_blue": "deep_crystal",
    "navy_blue_mica": "deep_crystal",
    "polymetal_gray_metallic": "polymetal_gray",
    "machine_gray_metallic": "machine_gray",
    "jet_black_mica": "jet_black",
    "zircon_sand_metallic": "zircon_sand_metallic",
    "wind_chill_pearl_metallic": "wind_chill_pearl",
    "snowflake_white_pearl_mica": "snowflake_white_pearl_mica",
}


def _normalize_color_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower())
    return slug.strip("_")


def is_interior_swatch_url(url: object) -> bool:
    value = str(url or "").strip().lower()
    if not value:
        return False
    return "interior-swatches" in value or "interiorswatch" in value


def resolve_exterior_color_hex(name: object, code: object = None) -> Optional[str]:
    """Map a Mazda exterior color name/code to a display hex value."""
    del code  # reserved for future code-based lookup
    slug = _normalize_color_slug(str(name or ""))
    if not slug:
        return None

    candidates = [slug]
    alias = MAZDA_EXTERIOR_COLOR_ALIASES.get(slug)
    if alias:
        candidates.insert(0, alias)

    for suffix in ("_crystal_metallic", "_crystal", "_metallic", "_pearl_mica", "_pearl", "_mica", "_premium"):
        if slug.endswith(suffix):
            candidates.append(slug[: -len(suffix)])

    seen: set[str] = set()
    ordered = [item for item in candidates if item and not (item in seen or seen.add(item))]

    for candidate in ordered:
        if candidate in MAZDA_EXTERIOR_COLOR_HEX:
            return MAZDA_EXTERIOR_COLOR_HEX[candidate]

    for key in sorted(MAZDA_EXTERIOR_COLOR_HEX, key=len, reverse=True):
        for candidate in ordered:
            if candidate == key or candidate.startswith(f"{key}_") or key.startswith(f"{candidate}_"):
                return MAZDA_EXTERIOR_COLOR_HEX[key]

    return None
