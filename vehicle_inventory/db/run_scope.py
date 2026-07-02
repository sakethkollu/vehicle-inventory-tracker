"""Resolve vehicle_runs rows from each series' latest ingest run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from vehicle_inventory.db.backend import DbConnection, commit_with_retry, execute_with_retry
from vehicle_inventory.db.sql_compat import ensure_index, table_exists_sql


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_series_latest_runs_table(conn: DbConnection) -> None:
    if conn.execute(table_exists_sql(), ("series_latest_runs",)).fetchone():
        return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS series_latest_runs (
            series_code VARCHAR(64) PRIMARY KEY,
            run_id INT NOT NULL,
            refreshed_at VARCHAR(64) NOT NULL
        )
        """
    )
    ensure_index(
        conn,
        name="idx_series_latest_runs_run_id",
        table="series_latest_runs",
        columns="run_id",
    )


def pin_series_latest_run(conn: DbConnection, series_code: str, run_id: int) -> None:
    """Point inventory queries at ``run_id`` for one series as ingest pages land."""
    code = str(series_code or "").strip()
    if not code:
        return
    ensure_series_latest_runs_table(conn)
    execute_with_retry(
        conn,
        """
        INSERT INTO series_latest_runs (series_code, run_id, refreshed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(series_code) DO UPDATE SET
            run_id=CASE
                WHEN excluded.run_id >= series_latest_runs.run_id THEN excluded.run_id
                ELSE series_latest_runs.run_id
            END,
            refreshed_at=CASE
                WHEN excluded.run_id >= series_latest_runs.run_id THEN excluded.refreshed_at
                ELSE series_latest_runs.refreshed_at
            END
        """,
        (code, int(run_id), utc_now()),
    )


def refresh_series_latest_runs(conn: DbConnection, *, force: bool = False) -> int:
    """Rebuild the per-series latest run cache used by inventory/filter queries."""
    ensure_series_latest_runs_table(conn)
    if not force:
        row = conn.execute("SELECT COUNT(*) AS total FROM series_latest_runs").fetchone()
        if row and int(row["total"]) > 0:
            return int(row["total"])

    ts = utc_now()
    execute_with_retry(conn, "DELETE FROM series_latest_runs")
    execute_with_retry(
        conn,
        """
        INSERT INTO series_latest_runs (series_code, run_id, refreshed_at)
        SELECT v.series_code, MAX(vr.run_id), ?
        FROM vehicles v
        JOIN vehicle_runs vr ON vr.vin = v.vin
        GROUP BY v.series_code
        """,
        (ts,),
    )
    row = conn.execute("SELECT COUNT(*) AS total FROM series_latest_runs").fetchone()
    return int(row["total"]) if row else 0


def vehicle_runs_latest_join(series_codes: Optional[List[str]] = None) -> Tuple[str, List]:
    params: List = []
    join = """
        JOIN vehicle_runs vr ON vr.vin = v.vin
        JOIN series_latest_runs slr
            ON slr.series_code = v.series_code
            AND slr.run_id = vr.run_id
    """
    if series_codes:
        placeholders = ",".join("?" for _ in series_codes)
        join += f" AND v.series_code IN ({placeholders})"
        params.extend(series_codes)
    return join, params
