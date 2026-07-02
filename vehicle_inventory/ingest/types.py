"""Shared ingest request types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class IngestRequest:
    database_url: str
    schema_path: Path
    zip_code: str
    distance: int
    page_size: int
    all_models: bool = False
    model_codes: Optional[List[str]] = None
    extra: Dict[str, Any] | None = None
