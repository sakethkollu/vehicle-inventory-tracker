"""Shared ingest progress tracking for all makes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

ProgressCallback = Callable[["IngestProgress"], None]


@dataclass
class IngestProgress:
    status: str = "idle"
    phase: str = ""
    current_model: str = ""
    current_model_title: str = ""
    model_index: int = 0
    total_models: int = 0
    current_page: int = 0
    total_pages: int = 0
    vehicles_fetched: int = 0
    vehicles_persisted: int = 0
    message: str = ""
    percent: float = 0.0
    error: Optional[str] = None
    completed_models: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def set_message(self, message: str) -> None:
        message = (message or "").strip()
        self.message = message
        if not message:
            return
        if self.logs and self.logs[-1] == message:
            return
        self.logs.append(message)
        if len(self.logs) > 300:
            del self.logs[:-300]

    def to_dict(self) -> Dict:
        return asdict(self)


def emit_progress(
    progress: IngestProgress,
    progress_callback: Optional[ProgressCallback],
    *,
    message: Optional[str] = None,
    **fields: object,
) -> None:
    if message is not None:
        progress.set_message(message)
    for key, value in fields.items():
        setattr(progress, key, value)
    if progress_callback:
        progress_callback(progress)
