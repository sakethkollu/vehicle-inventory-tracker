"""Mazda model/trim display helpers."""

from __future__ import annotations

import re
from typing import Dict, Iterable, Mapping, Optional


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def normalize_mazda_model_code(value: str) -> str:
    """Normalize Mazda labels/codes for catalog matching (``CX-5`` → ``CX5``)."""
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def build_mazda_catalog_code_index(catalog_models: Iterable[Mapping[str, object]]) -> Dict[str, str]:
    """Map normalized Mazda names/codes to canonical catalog ``model_code`` values."""
    index: Dict[str, str] = {}
    for row in catalog_models:
        model_code = str(row.get("model_code") or "").strip()
        if not model_code:
            continue
        keys = {
            model_code,
            str(row.get("series") or ""),
            str(row.get("title") or ""),
            str(row.get("title") or "").replace("MAZDA ", "").replace("Mazda ", ""),
        }
        for key in keys:
            normalized = normalize_mazda_model_code(key)
            compact = _compact(key)
            if normalized:
                index[normalized] = model_code
            if compact:
                index[compact] = model_code
    return index


def resolve_mazda_series_code(
    *,
    carline: str = "",
    model_name: str = "",
    raw: Optional[Mapping[str, object]] = None,
    catalog_index: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve a vehicle's catalog ``model_code`` for ``vehicles.series_code``."""
    raw = raw or {}
    candidates = [
        raw.get("CarlineCode"),
        raw.get("ModelCode"),
        raw.get("VehicleCode"),
        carline,
        model_name,
    ]
    if catalog_index:
        for candidate in candidates:
            normalized = normalize_mazda_model_code(str(candidate or ""))
            if normalized and normalized in catalog_index:
                return catalog_index[normalized]
            compact = _compact(str(candidate or ""))
            if compact and compact in catalog_index:
                return catalog_index[compact]
    for candidate in candidates:
        normalized = normalize_mazda_model_code(str(candidate or ""))
        if normalized:
            return normalized
    return "UNKNOWN"


def compose_mazda_model_marketing_name(
    *,
    marketing_series: str = "",
    model_marketing_name: str = "",
    grade: str = "",
) -> str:
    """Build a filter-friendly model label from series + trim.

    Mazda inventory often stores the same value for series and model; trim lives
    on ``grade``. Concatenate when trim adds information beyond the base name.
    """
    base = (marketing_series or model_marketing_name or "").strip()
    trim = (grade or "").strip()
    if not base:
        return trim
    if not trim:
        return base

    base_key = _compact(base)
    trim_key = _compact(trim)
    if not trim_key or trim_key == base_key:
        return base
    if trim_key in base_key:
        return base
    if base_key in trim_key:
        return trim
    return f"{base} · {trim}"
