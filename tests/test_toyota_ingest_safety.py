"""Tests for Toyota ingest safety around partial fetches."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

if "requests" not in sys.modules:
    sys.modules["requests"] = ModuleType("requests")

from vehicle_inventory.makes.toyota.ingest import _ingest_single_model_streaming


def test_streaming_ingest_skips_mark_inactive_on_partial_fetch():
    db = MagicMock()
    client = MagicMock()
    fetch_result = MagicMock()
    fetch_result.partial = True
    fetch_result.last_page_fetched = 2
    fetch_result.total_pages = 10
    fetch_result.fetch_error = "timeout"
    client.fetch_all_pages.return_value = fetch_result

    settings = MagicMock()
    settings.zip_code = "95132"
    settings.distance = 500
    settings.page_size = 250
    settings.lead_id = "lead"
    settings.interior_media = False

    model = MagicMock()
    model.model_code = "camry"

    with patch(
        "vehicle_inventory.makes.toyota.ingest.refresh_series_latest_runs",
        return_value=1,
    ) as refresh:
        _ingest_single_model_streaming(
            client=client,
            settings=settings,
            model=model,
            queried_at="2026-01-01T00:00:00+00:00",
            db=db,
        )

    db.mark_inactive_not_seen.assert_not_called()
    refresh.assert_called_once_with(db.conn, force=True)
    db.commit.assert_called_once()
