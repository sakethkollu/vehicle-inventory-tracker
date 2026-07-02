"""Toyota make adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from vehicle_inventory.db import InventoryDb, utc_now
from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback
from vehicle_inventory.ingest.types import IngestRequest
from vehicle_inventory.makes.toyota.client import ToyotaInventoryClient
from vehicle_inventory.makes.toyota.ingest import (
    LiveIngestSettings,
    build_client,
    refresh_waf_token_playwright,
    resolve_waf_token,
    run_live_ingest,
    sync_model_catalog,
)


class ToyotaAdapter:
    slug = "toyota"
    display_name = "Toyota"

    def build_ingest_request(
        self,
        payload: Dict[str, Any],
        *,
        database_url: str,
        schema_path: Path,
    ) -> IngestRequest:
        return IngestRequest(
            database_url=database_url,
            schema_path=schema_path,
            zip_code=str(payload.get("zip_code") or "95132"),
            distance=int(payload.get("distance") or 500),
            page_size=int(payload.get("page_size") or 250),
            all_models=bool(payload.get("all_models")),
            model_codes=payload.get("model_codes"),
            extra={
                "lead_id": str(payload.get("lead_id") or "3807e828-1b31-4efa-962f-7646948b7d4b"),
                "waf_token": resolve_waf_token(str(payload.get("waf_token") or "")),
            },
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
        distance: int = 500,
    ) -> Dict[str, Any]:
        settings = LiveIngestSettings(database_url=database_url, schema_path=schema_path, zip_code=zip_code)
        waf_token = resolve_waf_token()
        client = build_client(
            settings,
            waf_token,
            waf_token_refresh=lambda: refresh_waf_token_playwright(settings),
        )
        db = InventoryDb(database_url=database_url, schema_path=schema_path)
        db.initialize()
        ts = utc_now()
        models = sync_model_catalog(client, db, zip_code, ts)
        return {
            "count": len(models),
            "models": [
                {
                    "model_code": model.model_code,
                    "series": model.series,
                    "title": model.title,
                    "year": model.year,
                    "msrp": model.msrp,
                }
                for model in models
            ],
        }

    def run_ingest(
        self,
        request: IngestRequest,
        *,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> IngestProgress:
        extra = request.extra or {}
        settings = LiveIngestSettings(
            database_url=request.database_url,
            schema_path=request.schema_path,
            zip_code=request.zip_code,
            distance=request.distance,
            page_size=request.page_size,
            model_codes=request.model_codes,
            all_models=request.all_models,
            lead_id=str(extra.get("lead_id") or "3807e828-1b31-4efa-962f-7646948b7d4b"),
            waf_token=str(extra.get("waf_token") or ""),
            stream_to_db=True,
            make_slug=self.slug,
        )
        return run_live_ingest(settings, progress_callback=progress_callback)

    def image_host_suffixes(self) -> tuple[str, ...]:
        return (".toyota.com", ".toyotacertified.com")
