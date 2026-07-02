"""Dispatch ingest and catalog operations to the registered make adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional

from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback
from vehicle_inventory.ingest.types import IngestRequest
from vehicle_inventory.makes.registry import get_make_adapter


def run_make_ingest(
    make_slug: str,
    request: IngestRequest,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> IngestProgress:
    return get_make_adapter(make_slug).run_ingest(request, progress_callback=progress_callback)


def sync_make_catalog(
    make_slug: str,
    *,
    database_url: str,
    schema_path,
    zip_code: str,
    distance: Optional[int] = None,
    nationwide: Optional[bool] = None,
) -> Dict[str, Any]:
    adapter = get_make_adapter(make_slug)
    if not adapter.supports_catalog_sync():
        raise RuntimeError(f"Catalog sync is not supported for {adapter.display_name}.")
    kwargs: Dict[str, Any] = {
        "database_url": database_url,
        "schema_path": schema_path,
        "zip_code": zip_code,
    }
    if distance is not None:
        kwargs["distance"] = distance
    if nationwide is not None:
        kwargs["nationwide"] = nationwide
    return adapter.sync_catalog(**kwargs)


def build_ingest_request(make_slug: str, payload: Dict[str, Any], *, database_url: str, schema_path) -> IngestRequest:
    return get_make_adapter(make_slug).build_ingest_request(
        payload,
        database_url=database_url,
        schema_path=schema_path,
    )


def run_make_dealer_vehicle_refresh(
    make_slug: str,
    *,
    database_url: str,
    schema_path,
    all_models: bool,
    model_codes: Optional[list[str]],
    distance: int = 1,
    page_size: int = 100,
    progress_callback: Optional[ProgressCallback] = None,
) -> IngestProgress:
    adapter = get_make_adapter(make_slug)
    refresh = getattr(adapter, "refresh_dealer_vehicles", None)
    if not callable(refresh):
        raise RuntimeError(f"Dealer vehicle refresh is not supported for {adapter.display_name}.")
    return refresh(
        database_url=database_url,
        schema_path=schema_path,
        all_models=all_models,
        model_codes=model_codes,
        distance=distance,
        page_size=page_size,
        progress_callback=progress_callback,
    )
