"""Mazda media URL classification helpers."""

from __future__ import annotations

import re
from typing import Dict


_MAZDA_360_PATTERN = re.compile(
    r"/i360-|/e360-|/360/|360-interior|360-exterior|interior-statics/.+/i360-",
    re.IGNORECASE,
)


def is_mazda_360_image(href: str) -> bool:
    """Return True for Mazda interior/exterior 360 panorama strip assets."""
    lower = str(href or "").strip().lower()
    if not lower:
        return False
    if _MAZDA_360_PATTERN.search(lower):
        return True
    filename = lower.rsplit("/", 1)[-1]
    return filename.startswith("i360-") or filename.startswith("e360-")


def normalize_mazda_media_href(href: str) -> str:
    href = str(href or "").strip()
    if not href:
        return ""
    if href.startswith("/"):
        return f"https://www.mazdausa.com{href}"
    return href.replace("https://www.mazdausa.com:443", "https://www.mazdausa.com")


def classify_mazda_media(href: str, *, image_tag: str = "", media_type: str = "") -> Dict[str, str]:
    """Map Mazda CDN paths to inventory media types used by the UI and PDF export."""
    href = normalize_mazda_media_href(href)
    lower = href.lower()
    tag = str(image_tag or "").strip()
    existing = str(media_type or "").strip().lower()

    if is_mazda_360_image(href):
        payload: Dict[str, str] = {"href": href, "type": "interior360", "imageTag": "360 Interior"}
        return payload

    if existing in {"carjellyimage", "exterior", "interior", "interior360"}:
        resolved_type = "interior" if existing == "interior360" else existing
    elif "interior" in lower:
        resolved_type = "interior"
    elif any(token in lower for token in ("profile-jellies", "34-jellies", "jellies", "jelly", "carjelly")):
        resolved_type = "carjellyimage"
    elif "exterior" in lower:
        resolved_type = "exterior"
    else:
        resolved_type = "exterior"

    payload = {"href": href, "type": resolved_type}
    if tag and tag.lower() != "vehicle":
        payload["imageTag"] = tag
    elif resolved_type == "interior":
        payload["imageTag"] = "Interior"
    elif resolved_type == "carjellyimage":
        payload["imageTag"] = "Exterior"
    return payload


def enrich_mazda_media_row(row: Dict[str, object]) -> Dict[str, object]:
    """Normalize and reclassify a stored Mazda media row for API responses."""
    href = normalize_mazda_media_href(str(row.get("href") or ""))
    classified = classify_mazda_media(
        href,
        image_tag=str(row.get("image_tag") or ""),
        media_type=str(row.get("media_type") or ""),
    )
    enriched = dict(row)
    enriched["href"] = classified["href"]
    enriched["media_type"] = classified["type"]
    if classified.get("imageTag"):
        enriched["image_tag"] = classified["imageTag"]
    return enriched
