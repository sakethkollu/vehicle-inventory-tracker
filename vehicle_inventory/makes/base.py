"""Make adapter contract — implement this to add a new OEM."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Protocol, runtime_checkable

from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback
from vehicle_inventory.ingest.types import IngestRequest


@runtime_checkable
class MakeAdapter(Protocol):
    slug: str
    display_name: str

    def build_ingest_request(self, payload: Dict[str, Any], *, database_url: str, schema_path: Path) -> IngestRequest:
        ...

    def run_ingest(
        self,
        request: IngestRequest,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> IngestProgress:
        ...

    def requires_model_selection(self) -> bool:
        """When True, ingest must have all_models or at least one model_code."""
        ...

    def supports_catalog_sync(self) -> bool:
        ...

    def sync_catalog(
        self,
        *,
        database_url: str,
        schema_path: Path,
        zip_code: str,
        distance: int = 500,
    ) -> Dict[str, Any]:
        ...

    def image_host_suffixes(self) -> tuple[str, ...]:
        ...
