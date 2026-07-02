"""Persisted background job run history and analytics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from vehicle_inventory.db.backend import DbConnection, open_db_connection
from vehicle_inventory.db import utc_now
from vehicle_inventory.db.sql_compat import ensure_index, table_exists_sql

JOB_TYPES = ("ingest", "geocode", "catalog_sync")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled")


def job_status_is_active(status: Optional[str]) -> bool:
    return str(status or "").lower() in {"queued", "running"}


def ensure_job_runs_table(conn: DbConnection) -> None:
    if not conn.execute(table_exists_sql(), ("job_runs",)).fetchone():
        return

    ensure_index(
        conn,
        name="idx_job_runs_type_started",
        table="job_runs",
        columns="job_type, started_at DESC",
    )
    ensure_index(
        conn,
        name="idx_job_runs_started",
        table="job_runs",
        columns="started_at DESC",
    )


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _duration_sec(started_at: str, finished_at: str) -> float:
    start = _parse_iso(started_at)
    end = _parse_iso(finished_at)
    return max(0.0, (end - start).total_seconds())


def _parse_json_field(raw: Any, *, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _normalize_run(row: dict) -> dict:
    payload = dict(row)
    payload["params"] = _parse_json_field(payload.pop("params_json", None), default={})
    payload["result"] = _parse_json_field(payload.pop("result_json", None), default={})
    return payload

@dataclass
class JobRunStore:
    database_url: str

    def _conn(self) -> DbConnection:
        return open_db_connection(self.database_url)

    def start(
        self,
        job_type: str,
        params: Dict[str, Any],
        *,
        trigger_source: str = "ui",
        message: str = "",
        status: str = "running",
    ) -> int:
        if status not in JOB_STATUSES:
            raise ValueError(f"Invalid job status: {status}")
        ensure_job_runs_table(self._conn())
        started_at = utc_now()
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO job_runs (
                    job_type, status, started_at, params_json, message, trigger_source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    job_type,
                    status,
                    started_at,
                    json.dumps(params, separators=(",", ":")),
                    message,
                    trigger_source,
                ),
            )
            conn.commit()
            return int(conn.lastrowid)
        finally:
            conn.close()

    def mark_running(self, job_run_id: int) -> bool:
        conn = self._conn()
        try:
            conn.execute(
                """
                UPDATE job_runs
                SET status = 'running'
                WHERE job_run_id = ? AND status = 'queued'
                """,
                (job_run_id,),
            )
            conn.commit()
            return conn.rowcount > 0
        finally:
            conn.close()

    def finish(
        self,
        job_run_id: int,
        status: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        finished_at = utc_now()
        conn = self._conn()
        try:
            duration_sec = None
            row = conn.execute(
                "SELECT started_at FROM job_runs WHERE job_run_id = ?",
                (job_run_id,),
            ).fetchone()
            if row and row["started_at"]:
                duration_sec = round(_duration_sec(row["started_at"], finished_at), 3)
            conn.execute(
                """
                UPDATE job_runs
                SET status = ?, finished_at = ?, duration_sec = ?,
                    result_json = ?, error = ?, message = COALESCE(?, message)
                WHERE job_run_id = ?
                """,
                (
                    status,
                    finished_at,
                    duration_sec,
                    json.dumps(result, separators=(",", ":")) if result is not None else None,
                    error,
                    message,
                    job_run_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def reconcile_if_stale(
        self,
        job_run_id: int,
        *,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        message: Optional[str] = None,
    ) -> bool:
        """Persist terminal live-worker state when the DB row is still running."""
        if status == "running" or status == "queued":
            return False
        run = self.get(job_run_id)
        if not run or not job_status_is_active(run.get("status")):
            return False
        self.finish(job_run_id, status, result=result, error=error, message=message)
        return True

    def get(self, job_run_id: int) -> Optional[dict]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT * FROM job_runs WHERE job_run_id = ?",
                (job_run_id,),
            ).fetchone()
            return _normalize_run(dict(row)) if row else None
        finally:
            conn.close()

    def list_runs(
        self,
        *,
        job_type: Optional[str] = None,
        limit: int = 50,
        since_days: Optional[int] = None,
    ) -> List[dict]:
        conn = self._conn()
        try:
            clauses: List[str] = []
            params: List[Any] = []
            if job_type:
                clauses.append("job_type = ?")
                params.append(job_type)
            if since_days is not None:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
                clauses.append("started_at >= ?")
                params.append(cutoff)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM job_runs {where} ORDER BY started_at DESC LIMIT ?",
                params,
            ).fetchall()
            return [_normalize_run(dict(row)) for row in rows]
        finally:
            conn.close()

    def list_active_runs(self, *, limit: int = 100) -> List[dict]:
        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM job_runs
                WHERE status IN ('queued', 'running')
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [_normalize_run(dict(row)) for row in rows]
        finally:
            conn.close()

    def list_running_runs(self, *, limit: int = 100) -> List[dict]:
        return self.list_active_runs(limit=limit)

    def summary(self, *, since_days: int = 30) -> Dict[str, dict]:
        runs = self.list_runs(since_days=since_days, limit=500)
        summary: Dict[str, dict] = {}
        for run in runs:
            job_type = run["job_type"]
            bucket = summary.setdefault(
                job_type,
                {"count": 0, "completed": 0, "failed": 0, "total_duration_sec": 0.0},
            )
            bucket["count"] += 1
            if run["status"] == "completed":
                bucket["completed"] += 1
            elif run["status"] == "failed":
                bucket["failed"] += 1
            if run.get("duration_sec") is not None:
                bucket["total_duration_sec"] += float(run["duration_sec"])
        for stats in summary.values():
            if stats["completed"]:
                stats["avg_duration_sec"] = round(
                    stats["total_duration_sec"] / stats["completed"], 2
                )
            else:
                stats["avg_duration_sec"] = None
        return summary


def dealer_vehicle_refresh_params_from_payload(
    payload: dict,
    *,
    all_models: bool,
    model_codes,
    make_slug: str,
) -> dict:
    return {
        "distance": int(payload.get("distance") or 1),
        "page_size": int(payload.get("page_size") or 100),
        "all_models": all_models,
        "model_codes": model_codes or [],
        "make": make_slug,
    }


def ingest_params_from_payload(payload: dict, *, all_models: bool, model_codes, make_slug: str) -> dict:
    nationwide_raw = payload.get("nationwide")
    nationwide = True if nationwide_raw is None else bool(nationwide_raw)
    return {
        "zip_code": str(payload.get("zip_code") or ""),
        "distance": int(payload.get("distance") or 0),
        "page_size": int(payload.get("page_size") or 0),
        "all_models": all_models,
        "model_codes": model_codes or [],
        "make": make_slug,
        "nationwide": nationwide if make_slug == "mazda" else None,
        **({"lead_id": payload["lead_id"]} if payload.get("lead_id") else {}),
    }


def ingest_params_from_settings(settings, *, all_models: bool, model_codes) -> dict:
    return {
        "zip_code": settings.zip_code,
        "distance": settings.distance,
        "page_size": settings.page_size,
        "all_models": all_models,
        "model_codes": model_codes or [],
        "series_code": settings.series_code,
        "make": getattr(settings, "make_slug", "toyota"),
    }


def geocode_params(
    *,
    limit: Optional[int],
    delay_sec: float,
    force: bool,
    workers: int,
) -> dict:
    return {
        "limit": limit,
        "delay_sec": delay_sec,
        "force": force,
        "workers": workers,
    }


def ingest_result_from_progress(progress) -> dict:
    return progress.to_dict()


def geocode_result_from_progress(progress, result: Optional[dict]) -> dict:
    payload = progress.to_dict() if hasattr(progress, "to_dict") else dict(progress)
    if result:
        payload["result"] = result
    return payload


def live_progress_result(live: dict) -> dict:
    payload = dict(live)
    payload.pop("job_run_id", None)
    return payload


def reconcile_live_job_run(store: JobRunStore, live: dict) -> bool:
    job_run_id = live.get("job_run_id")
    status = live.get("status")
    if not job_run_id or status in (None, "idle", "running", "queued"):
        return False
    return store.reconcile_if_stale(
        int(job_run_id),
        status=str(status),
        result=live_progress_result(live),
        error=live.get("error"),
        message=live.get("message"),
    )


RQ_JOB_PREFIX = {
    "ingest": "ingest",
    "geocode": "geocode",
    "dealer_vehicle_refresh": "dealer-refresh",
}


def _run_age_sec(run: dict, now: Optional[datetime] = None) -> float:
    started = run.get("started_at")
    if not started:
        return 0.0
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - _parse_iso(str(started))).total_seconds())


def _rq_job_error(rq_job) -> str:
    exc_info = getattr(rq_job, "exc_info", None)
    if exc_info:
        lines = str(exc_info).strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                return stripped[:2000]
    return "Worker job failed."


def reconcile_rq_stale_runs(
    store: JobRunStore,
    redis_url: str,
    *,
    stale_after_sec: int = 300,
) -> int:
    """Close DB rows still marked running when the RQ job already finished or vanished."""
    if not redis_url:
        return 0

    from redis import Redis
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    conn = Redis.from_url(redis_url)
    now = datetime.now(timezone.utc)
    repaired = 0

    for run in store.list_running_runs():
        prefix = RQ_JOB_PREFIX.get(str(run.get("job_type") or ""))
        if not prefix:
            continue
        job_run_id = int(run["job_run_id"])
        params = run.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        make_slug = str(params.get("make") or "toyota")
        rq_id = f"{make_slug}-{prefix}-{job_run_id}"

        try:
            rq_job = Job.fetch(rq_id, connection=conn)
        except NoSuchJobError:
            if _run_age_sec(run, now) >= stale_after_sec:
                if store.reconcile_if_stale(
                    job_run_id,
                    status="failed",
                    error="No worker queue record found for this job run.",
                    message="Reconciled stale running job (missing queue record).",
                ):
                    repaired += 1
            continue

        if rq_job.is_finished:
            result = rq_job.result if isinstance(rq_job.result, dict) else {}
            terminal_status = str(result.get("status") or "completed")
            if terminal_status in {"running", "queued"}:
                terminal_status = "completed"
            if store.reconcile_if_stale(
                job_run_id,
                status=terminal_status,
                result=result or None,
                error=result.get("error"),
                message=result.get("message") or f"Reconciled from worker queue ({terminal_status}).",
            ):
                repaired += 1
        elif rq_job.is_failed:
            result = rq_job.result if isinstance(rq_job.result, dict) else None
            if store.reconcile_if_stale(
                job_run_id,
                status="failed",
                result=result,
                error=_rq_job_error(rq_job),
                message="Reconciled from worker queue (failed).",
            ):
                repaired += 1
        elif rq_job.is_started and str(run.get("status") or "") == "queued":
            store.mark_running(job_run_id)

    return repaired
