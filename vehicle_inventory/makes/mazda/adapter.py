"""Mazda make adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Optional

from vehicle_inventory.db import InventoryDb, utc_now
from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback
from vehicle_inventory.ingest.types import IngestRequest
from vehicle_inventory.makes.mazda.client import MazdaClientConfig, MazdaInventoryClient
from vehicle_inventory.makes.mazda.ingest import (
    MazdaDealerRefreshSettings,
    MazdaIngestSettings,
    run_mazda_dealer_vehicle_refresh,
    run_mazda_ingest,
    sync_model_catalog,
    sync_nationwide_dealers,
)
from vehicle_inventory.makes.mazda.dealers import mazda_discovery_seed_zips
from vehicle_inventory.makes.mazda.session import resolve_mazda_cookies


class MazdaAdapter:
    slug = "mazda"
    display_name = "Mazda"

    def build_ingest_request(
        self,
        payload: Dict[str, Any],
        *,
        database_url: str,
        schema_path: Path,
    ) -> IngestRequest:
        model_codes = payload.get("model_codes")
        if isinstance(model_codes, list):
            model_codes = [str(code).strip() for code in model_codes if str(code).strip()]
        else:
            model_codes = None
        all_models = bool(payload.get("all_models"))
        nationwide_raw = payload.get("nationwide")
        nationwide = False if nationwide_raw is None else bool(nationwide_raw)
        return IngestRequest(
            database_url=database_url,
            schema_path=schema_path,
            zip_code=str(payload.get("zip_code") or "95101"),
            distance=int(payload.get("distance") or 50),
            page_size=int(payload.get("page_size") or 100),
            all_models=all_models,
            model_codes=model_codes,
            extra={"nationwide": nationwide},
        )

    def requires_model_selection(self) -> bool:
        return True

    def supports_catalog_sync(self) -> bool:
        return True

    def sync_catalog(
        self,
        *,
        database_url: str,
        schema_path: Path,
        zip_code: str,
        distance: int = 50,
        nationwide: bool = True,
    ) -> Dict[str, Any]:
        db = InventoryDb(database_url=database_url, schema_path=schema_path)
        db.initialize()
        ts = utc_now()
        client = MazdaInventoryClient(
            MazdaClientConfig(
                cookies=resolve_mazda_cookies(),
                page_size=1,
            )
        )
        scope = "nationwide" if nationwide else "in dealer radius"
        try:
            models = sync_model_catalog(
                client,
                db,
                zip_code=zip_code,
                distance=distance,
                ts=ts,
                nationwide=nationwide,
            )
        finally:
            db.close()
        return {
            "count": len(models),
            "dealer_scope": scope,
            "models": [
                {
                    "model_code": model.model_code,
                    "series": model.series,
                    "title": model.title,
                    "year": model.year,
                    "image": model.image,
                    "top_label": (
                        f"{model.inventory_count:,} {scope}"
                        if model.inventory_count is not None
                        else None
                    ),
                }
                for model in models
            ],
        }

    def sync_dealers(
        self,
        *,
        database_url: str,
        schema_path: Path,
    ) -> Dict[str, Any]:
        db = InventoryDb(database_url=database_url, schema_path=schema_path)
        db.initialize()
        ts = utc_now()
        client = MazdaInventoryClient(MazdaClientConfig(cookies=resolve_mazda_cookies()))
        try:
            dealers = sync_nationwide_dealers(client, db, ts=ts)
        finally:
            db.close()
        return {
            "count": len(dealers),
            "seed_zips": len(mazda_discovery_seed_zips()),
            "dealers": [
                {
                    "dealer_id": dealer.dealer_id,
                    "name": dealer.name,
                    "city": dealer.city,
                    "state": dealer.state,
                    "zip_code": dealer.zip_code,
                }
                for dealer in dealers
            ],
        }

    def run_ingest(
        self,
        request: IngestRequest,
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> IngestProgress:
        settings = MazdaIngestSettings(
            database_url=request.database_url,
            schema_path=request.schema_path,
            zip_code=request.zip_code,
            distance=request.distance,
            page_size=request.page_size,
            model_codes=request.model_codes,
            all_models=request.all_models,
            nationwide=bool((request.extra or {}).get("nationwide", True)),
        )
        return run_mazda_ingest(settings, progress_callback=progress_callback)

    def refresh_dealer_vehicles(
        self,
        *,
        database_url: str,
        schema_path: Path,
        all_models: bool = False,
        model_codes: Optional[list[str]] = None,
        distance: int = 1,
        page_size: int = 100,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> IngestProgress:
        settings = MazdaDealerRefreshSettings(
            database_url=database_url,
            schema_path=schema_path,
            distance=distance,
            page_size=page_size,
            model_codes=model_codes,
            all_models=all_models,
        )
        return run_mazda_dealer_vehicle_refresh(settings, progress_callback=progress_callback)

    def image_host_suffixes(self) -> tuple[str, ...]:
        return (".mazdausa.com",)
