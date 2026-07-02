"""Make registry: one MySQL database per make, shared app deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List
from urllib.parse import urlparse, urlunparse

from vehicle_inventory.makes.base import MakeAdapter

DEFAULT_MAKE_SLUG = "toyota"


@dataclass(frozen=True)
class MakeProfile:
    slug: str
    display_name: str
    database_url: str
    ingest_adapter: str
    inventory_origin: str
    waf_env_var: str = ""

    @property
    def redis_prefix(self) -> str:
        return f"vit:{self.slug}"


def _swap_database_url(base_url: str, database_name: str) -> str:
    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(path=f"/{database_name}"))


def _build_registry() -> Dict[str, MakeProfile]:
    base_url = os.environ.get("DATABASE_URL", "").strip()
    if not base_url:
        return {}

    toyota_url = os.environ.get("TOYOTA_DATABASE_URL", "").strip() or base_url
    mazda_url = os.environ.get("MAZDA_DATABASE_URL", "").strip()
    if not mazda_url:
        mazda_db = os.environ.get("MAZDA_DATABASE", "mazda_inventory").strip() or "mazda_inventory"
        mazda_url = _swap_database_url(base_url, mazda_db)

    return {
        "toyota": MakeProfile(
            slug="toyota",
            display_name="Toyota",
            database_url=toyota_url,
            ingest_adapter="toyota",
            inventory_origin="https://www.toyota.com/",
            waf_env_var="TOYOTA_WAF_TOKEN",
        ),
        "mazda": MakeProfile(
            slug="mazda",
            display_name="Mazda",
            database_url=mazda_url,
            ingest_adapter="mazda",
            inventory_origin="https://www.mazdausa.com/",
            waf_env_var="MAZDA_SESSION_COOKIE",
        ),
    }


_REGISTRY: Dict[str, MakeProfile] | None = None
_ADAPTER_CACHE: Dict[str, MakeAdapter] | None = None


def _registry() -> Dict[str, MakeProfile]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def _adapters() -> Dict[str, MakeAdapter]:
    global _ADAPTER_CACHE
    if _ADAPTER_CACHE is None:
        from vehicle_inventory.makes.mazda.adapter import MazdaAdapter
        from vehicle_inventory.makes.toyota.adapter import ToyotaAdapter

        _ADAPTER_CACHE = {
            "toyota": ToyotaAdapter(),
            "mazda": MazdaAdapter(),
        }
    return _ADAPTER_CACHE


def list_makes() -> List[MakeProfile]:
    return list(_registry().values())


def get_make_profile(slug: str) -> MakeProfile:
    profile = _registry().get((slug or "").strip().lower())
    if profile is None:
        raise KeyError(f"Unknown make: {slug!r}")
    return profile


def get_make_adapter(slug: str) -> MakeAdapter:
    profile = get_make_profile(slug)
    adapter = _adapters().get(profile.ingest_adapter)
    if adapter is None:
        raise KeyError(f"No ingest adapter registered for make: {slug!r}")
    return adapter


def get_default_make_slug() -> str:
    configured = os.environ.get("DEFAULT_MAKE", DEFAULT_MAKE_SLUG).strip().lower()
    if configured in _registry():
        return configured
    return DEFAULT_MAKE_SLUG


def resolve_database_url(make_slug: str) -> str:
    return get_make_profile(make_slug).database_url


def all_image_host_suffixes() -> tuple[str, ...]:
    suffixes: list[str] = []
    for adapter in _adapters().values():
        suffixes.extend(adapter.image_host_suffixes())
    return tuple(dict.fromkeys(suffixes))
