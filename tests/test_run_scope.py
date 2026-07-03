"""Tests for per-series latest run resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from vehicle_inventory.db.run_scope import (
    finalize_ingest_runs,
    is_partial_run_source,
    refresh_series_latest_runs,
)


class _FakeCursor:
    def __init__(self, rowcount: int = 0, fetchone_result=None, fetchall_result=None):
        self.rowcount = rowcount
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result


class _RecordingConn:
    def __init__(self):
        self.statements: list[tuple[str, tuple | None]] = []
        self._count = 1
        self._table_exists = True

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        self.statements.append((normalized, params))
        if "information_schema.tables" in normalized.lower():
            return _FakeCursor(
                fetchone_result=_FakeRow({"name": "series_latest_runs"})
                if self._table_exists
                else None
            )
        if "COUNT(*) AS total FROM series_latest_runs" in normalized:
            return _FakeCursor(fetchone_result=_FakeRow({"total": self._count}))
        if "SELECT ranked.series_code, ranked.run_id" in normalized:
            return _FakeCursor(
                fetchall_result=[
                    _FakeRow({"series_code": "CX50H", "run_id": 100}),
                ]
            )
        return _FakeCursor(rowcount=3)


class _FakeRow:
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]


def test_is_partial_run_source():
    assert is_partial_run_source("mazda_dealer_zip_refresh")
    assert not is_partial_run_source("mazda_rest")
    assert not is_partial_run_source(None)


def test_refresh_series_latest_runs_prefers_largest_snapshot():
    conn = _RecordingConn()
    refresh_series_latest_runs(conn, force=True)

    insert_sql = next(
        sql for sql, _ in conn.statements if "INSERT INTO series_latest_runs" in sql
    )
    assert "ROW_NUMBER() OVER" in insert_sql
    assert "ORDER BY COUNT(*) DESC, vr.run_id DESC" in insert_sql
    assert "MAX(vr.run_id)" not in insert_sql


def test_refresh_series_latest_runs_skips_when_cache_populated():
    conn = _RecordingConn()
    conn._count = 5
    total = refresh_series_latest_runs(conn, force=False)
    assert total == 5
    assert not any("DELETE FROM series_latest_runs" in sql for sql, _ in conn.statements)


def test_finalize_ingest_runs_merges_partial_snapshots_before_refresh():
    conn = _RecordingConn()
    with patch(
        "vehicle_inventory.db.run_scope.carry_forward_from_best_prior_snapshots",
        return_value=12,
    ) as carry_forward, patch(
        "vehicle_inventory.db.run_scope.refresh_series_latest_runs",
        return_value=4,
    ) as refresh:
        total = finalize_ingest_runs(
            conn,
            run_id=200,
            series_codes=["CX50H"],
            run_source="mazda_dealer_zip_refresh",
        )

    carry_forward.assert_called_once_with(
        conn,
        refresh_run_id=200,
        series_codes=["CX50H"],
    )
    refresh.assert_called_once_with(conn, force=True)
    assert total == 4


def test_finalize_ingest_runs_skips_merge_for_full_ingest():
    conn = _RecordingConn()
    with patch(
        "vehicle_inventory.db.run_scope.carry_forward_from_best_prior_snapshots",
    ) as carry_forward, patch(
        "vehicle_inventory.db.run_scope.refresh_series_latest_runs",
        return_value=3,
    ):
        finalize_ingest_runs(
            conn,
            run_id=200,
            series_codes=["CX50H"],
            run_source="mazda_rest",
        )

    carry_forward.assert_not_called()


def test_pin_series_latest_run_requires_fuller_snapshot():
    from vehicle_inventory.db.run_scope import pin_series_latest_run

    conn = MagicMock()
    pin_series_latest_run(conn, "CX50H", 200)
    sql = conn.execute.call_args[0][0]
    assert "SELECT COUNT(*)" in sql
    assert ">= (" in sql
