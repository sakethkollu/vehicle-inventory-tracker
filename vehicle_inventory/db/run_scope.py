"""Resolve vehicle_runs rows from each series' latest ingest run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from vehicle_inventory.db.backend import DbConnection, execute_with_retry
from vehicle_inventory.db.sql_compat import ensure_index, table_exists_sql

# Runs that patch inventory for a subset of dealers/VINs — never replace a fuller snapshot.
PARTIAL_RUN_SOURCES = frozenset({"mazda_dealer_zip_refresh"})

_BEST_RUN_PER_SERIES_SQL = """
    SELECT ranked.series_code, ranked.run_id
    FROM (
        SELECT
            v.series_code,
            vr.run_id,
            ROW_NUMBER() OVER (
                PARTITION BY v.series_code
                ORDER BY COUNT(*) DESC, vr.run_id DESC
            ) AS rn
        FROM vehicles v
        INNER JOIN vehicle_runs vr ON vr.vin = v.vin
        {extra_where}
        GROUP BY v.series_code, vr.run_id
    ) ranked
    WHERE ranked.rn = 1
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_partial_run_source(source: Optional[str]) -> bool:
    return (source or "").strip() in PARTIAL_RUN_SOURCES


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
    """Promote a run only when it has at least as many series snapshots as the incumbent."""
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
                WHEN (
                    SELECT COUNT(*)
                    FROM vehicle_runs vr
                    JOIN vehicles v ON v.vin = vr.vin
                    WHERE v.series_code = excluded.series_code
                      AND vr.run_id = excluded.run_id
                ) >= (
                    SELECT COUNT(*)
                    FROM vehicle_runs vr
                    JOIN vehicles v ON v.vin = vr.vin
                    WHERE v.series_code = series_latest_runs.series_code
                      AND vr.run_id = series_latest_runs.run_id
                )
                THEN excluded.run_id
                ELSE series_latest_runs.run_id
            END,
            refreshed_at=CASE
                WHEN (
                    SELECT COUNT(*)
                    FROM vehicle_runs vr
                    JOIN vehicles v ON v.vin = vr.vin
                    WHERE v.series_code = excluded.series_code
                      AND vr.run_id = excluded.run_id
                ) >= (
                    SELECT COUNT(*)
                    FROM vehicle_runs vr
                    JOIN vehicles v ON v.vin = vr.vin
                    WHERE v.series_code = series_latest_runs.series_code
                      AND vr.run_id = series_latest_runs.run_id
                )
                THEN excluded.refreshed_at
                ELSE series_latest_runs.refreshed_at
            END
        """,
        (code, int(run_id), utc_now()),
    )


def snapshot_series_latest_runs(
    conn: DbConnection,
    series_codes: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Return the current latest ``run_id`` per ``series_code``."""
    ensure_series_latest_runs_table(conn)
    if series_codes:
        placeholders = ",".join("?" for _ in series_codes)
        rows = conn.execute(
            f"""
            SELECT series_code, run_id
            FROM series_latest_runs
            WHERE series_code IN ({placeholders})
            """,
            series_codes,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT series_code, run_id FROM series_latest_runs"
        ).fetchall()
    return {str(row["series_code"]): int(row["run_id"]) for row in rows}


def resolve_best_run_ids_by_series(
    conn: DbConnection,
    series_codes: List[str],
    *,
    exclude_run_id: Optional[int] = None,
) -> Dict[str, int]:
    """Pick the fullest historical run per series, optionally excluding one run."""
    codes = [str(code or "").strip() for code in series_codes if str(code or "").strip()]
    if not codes:
        return {}

    placeholders = ",".join("?" for _ in codes)
    extra_where = f"WHERE v.series_code IN ({placeholders})"
    params: List = list(codes)
    if exclude_run_id is not None:
        extra_where += " AND vr.run_id <> ?"
        params.append(int(exclude_run_id))

    rows = conn.execute(
        _BEST_RUN_PER_SERIES_SQL.format(extra_where=extra_where),
        params,
    ).fetchall()
    return {str(row["series_code"]): int(row["run_id"]) for row in rows}


def _copy_series_run_snapshot(
    conn: DbConnection,
    *,
    from_run_id: int,
    to_run_id: int,
    series_code: str,
) -> int:
    """Copy missing ``vehicle_runs``/``vehicle_prices`` rows into a newer run."""
    if from_run_id == to_run_id:
        return 0

    cur = execute_with_retry(
        conn,
        """
        INSERT INTO vehicle_runs (
            run_id, vin, dealer_cd, stock_num, inventory_status, is_pre_sold,
            is_smart_path, is_unlock_price_dealer, distance, inventory_mileage,
            vdp_url, family_json, cab_json, bed_json, mpg_city, mpg_highway, mpg_combined,
            allocation_stage_code, allocation_stage_label, created_at
        )
        SELECT
            ?, vr.vin, vr.dealer_cd, vr.stock_num, vr.inventory_status, vr.is_pre_sold,
            vr.is_smart_path, vr.is_unlock_price_dealer, vr.distance, vr.inventory_mileage,
            vr.vdp_url, vr.family_json, vr.cab_json, vr.bed_json, vr.mpg_city, vr.mpg_highway,
            vr.mpg_combined, vr.allocation_stage_code, vr.allocation_stage_label, vr.created_at
        FROM vehicle_runs vr
        JOIN vehicles v ON v.vin = vr.vin
        LEFT JOIN vehicle_runs existing
            ON existing.run_id = ? AND existing.vin = vr.vin
        WHERE vr.run_id = ?
          AND v.series_code = ?
          AND existing.vin IS NULL
        """,
        (to_run_id, to_run_id, from_run_id, series_code),
    )
    copied = int(cur.rowcount or 0)

    execute_with_retry(
        conn,
        """
        INSERT INTO vehicle_prices (
            run_id, vin, advertized_price, non_sp_advertized_price, total_msrp,
            selling_price, dph, dio_total_msrp, dio_total_dealer_selling_price,
            dealer_cash_applied, base_msrp, created_at
        )
        SELECT
            ?, vp.vin, vp.advertized_price, vp.non_sp_advertized_price, vp.total_msrp,
            vp.selling_price, vp.dph, vp.dio_total_msrp, vp.dio_total_dealer_selling_price,
            vp.dealer_cash_applied, vp.base_msrp, vp.created_at
        FROM vehicle_prices vp
        JOIN vehicles v ON v.vin = vp.vin
        LEFT JOIN vehicle_prices existing
            ON existing.run_id = ? AND existing.vin = vp.vin
        WHERE vp.run_id = ?
          AND v.series_code = ?
          AND existing.vin IS NULL
        """,
        (to_run_id, to_run_id, from_run_id, series_code),
    )
    return copied


def carry_forward_series_snapshots(
    conn: DbConnection,
    *,
    refresh_run_id: int,
    prior_run_ids_by_series: Dict[str, int],
) -> int:
    """Merge prior latest-run snapshots into a partial refresh run."""
    copied = 0
    for series_code, prior_run_id in prior_run_ids_by_series.items():
        copied += _copy_series_run_snapshot(
            conn,
            from_run_id=prior_run_id,
            to_run_id=refresh_run_id,
            series_code=series_code,
        )
    return copied


def carry_forward_from_best_prior_snapshots(
    conn: DbConnection,
    *,
    refresh_run_id: int,
    series_codes: List[str],
) -> int:
    """Carry forward the fullest prior run per series into a partial refresh run."""
    prior_run_ids = resolve_best_run_ids_by_series(
        conn,
        series_codes,
        exclude_run_id=refresh_run_id,
    )
    return carry_forward_series_snapshots(
        conn,
        refresh_run_id=refresh_run_id,
        prior_run_ids_by_series=prior_run_ids,
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
        f"""
        INSERT INTO series_latest_runs (series_code, run_id, refreshed_at)
        SELECT ranked.series_code, ranked.run_id, ?
        FROM (
            SELECT
                v.series_code,
                vr.run_id,
                ROW_NUMBER() OVER (
                    PARTITION BY v.series_code
                    ORDER BY COUNT(*) DESC, vr.run_id DESC
                ) AS rn
            FROM vehicles v
            INNER JOIN vehicle_runs vr ON vr.vin = v.vin
            GROUP BY v.series_code, vr.run_id
        ) ranked
        WHERE ranked.rn = 1
        """,
        (ts,),
    )
    row = conn.execute("SELECT COUNT(*) AS total FROM series_latest_runs").fetchone()
    return int(row["total"]) if row else 0


def repair_series_latest_runs(conn: DbConnection) -> int:
    """Recompute latest-run pointers from historical snapshots."""
    return refresh_series_latest_runs(conn, force=True)


def finalize_ingest_runs(
    conn: DbConnection,
    *,
    run_id: Optional[int] = None,
    series_codes: Optional[List[str]] = None,
    run_source: Optional[str] = None,
) -> int:
    """Finalize ingest: merge partial snapshots, then refresh the latest-run cache."""
    if (
        run_id is not None
        and series_codes
        and is_partial_run_source(run_source)
    ):
        copied = carry_forward_from_best_prior_snapshots(
            conn,
            refresh_run_id=run_id,
            series_codes=series_codes,
        )
        if copied:
            print(
                f"[run_scope] carried forward {copied:,} vehicle snapshot(s) "
                f"into partial run {run_id}",
                flush=True,
            )
    return refresh_series_latest_runs(conn, force=True)


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
