"""Same-origin proxy for OEM CDN images (avoids browser CORS limits)."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional, Tuple
from urllib.parse import urlparse


from vehicle_inventory.makes.mazda.media import normalize_mazda_media_href
from vehicle_inventory.makes.registry import all_image_host_suffixes

ALLOWED_IMAGE_SUFFIXES = all_image_host_suffixes()


def normalize_image_proxy_url(url: str) -> str:
    """Canonicalize OEM image URLs before proxy fetch."""
    normalized = str(url or "").strip()
    if not normalized:
        return ""
    if "mazdausa.com" in normalized.lower():
        return normalize_mazda_media_href(normalized)
    return normalized


def is_allowed_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return any(host == suffix[1:] or host.endswith(suffix) for suffix in ALLOWED_IMAGE_SUFFIXES)


def _referer_for_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.endswith(".mazdausa.com") or host == "mazdausa.com":
        return "https://www.mazdausa.com/"
    return "https://www.toyota.com/"


def fetch_proxied_image(url: str, *, timeout: float = 20.0) -> Tuple[bytes, str]:
    url = normalize_image_proxy_url(url)
    if not url:
        raise ValueError("Image URL is empty.")
    if not is_allowed_image_url(url):
        raise ValueError("Image URL host is not allowed.")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; vehicle-inventory-tracker/1.0)",
            "Accept": "image/*,*/*;q=0.8",
            "Referer": _referer_for_url(url),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type") or guess_content_type(url)
            return data, content_type
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Upstream image request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Upstream image request failed: {exc.reason}") from exc


def guess_content_type(url: str) -> str:
    lower = url.lower()
    if ".png" in lower:
        return "image/png"
    if ".jpg" in lower or ".jpeg" in lower:
        return "image/jpeg"
    if ".webp" in lower:
        return "image/webp"
    if ".gif" in lower:
        return "image/gif"
    if "fmt=png" in lower or "png-alpha" in lower:
        return "image/png"
    return "application/octet-stream"
