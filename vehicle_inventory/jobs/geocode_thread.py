"""Background dealer geocoding job manager."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.geo.dealer_geo import dealer_geo_stats, geocode_all_dealers
from vehicle_inventory.jobs.runs import (
    JobRunStore,
    geocode_params,
    geocode_result_from_progress,
)


@dataclass
class GeocodeProgress:
    status: str = "idle"
    phase: str = "idle"
    message: str = ""
    processed: int = 0
    total: int = 0
    geocoded: int = 0
    failed: int = 0
    remaining: int = 0
    error: Optional[str] = None
    current_dealer_cd: Optional[str] = None
    job_run_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "phase": self.phase,
            "message": self.message,
            "processed": self.processed,
            "total": self.total,
            "geocoded": self.geocoded,
            "failed": self.failed,
            "remaining": self.remaining,
            "error": self.error,
            "current_dealer_cd": self.current_dealer_cd,
            "job_run_id": self.job_run_id,
        }


class GeocodeJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._progress = GeocodeProgress()
        self._database_url = ""
        self._limit: Optional[int] = None
        self._delay_sec = 1.1
        self._force = False
        self._workers = 8
        self._trigger_source = "ui"

    def configure(self, database_url: str) -> None:
        with self._lock:
            self._database_url = database_url

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            return self._progress.to_dict()

    def cancel(self) -> bool:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return False
            self._cancel.set()
            self._progress.message = "Cancelling dealer geocoding..."
            return True

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def start(
        self,
        *,
        limit: Optional[int] = None,
        delay_sec: float = 1.1,
        force: bool = False,
        workers: int = 8,
        trigger_source: str = "ui",
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("A dealer geocoding job is already running.")
            self._limit = limit
            self._delay_sec = delay_sec
            self._force = force
            self._workers = max(1, int(workers))
            self._trigger_source = trigger_source
            self._cancel.clear()
            store = JobRunStore(self._database_url)
            job_run_id = store.start(
                "geocode",
                geocode_params(
                    limit=limit,
                    delay_sec=delay_sec,
                    force=force,
                    workers=self._workers,
                ),
                trigger_source=trigger_source,
                message="Starting dealer geocoding...",
            )
            self._progress = GeocodeProgress(
                status="running",
                phase="geocoding",
                message="Starting dealer geocoding...",
                job_run_id=job_run_id,
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(job_run_id,),
                daemon=True,
            )
            self._thread.start()

    def _update(self, done: int, total: int, dealer_cd: str) -> None:
        with self._lock:
            self._progress.processed = done
            self._progress.total = total
            self._progress.current_dealer_cd = dealer_cd
            self._progress.message = f"Geocoding dealers ({done}/{total}): {dealer_cd}"

    def _run(self, job_run_id: int) -> None:
        store = JobRunStore(self._database_url)
        conn = open_db_connection(self._database_url)
        result = None
        try:
            result = geocode_all_dealers(
                conn,
                limit=self._limit,
                delay_sec=self._delay_sec,
                progress_callback=self._update,
                force=self._force,
                workers=self._workers,
                should_cancel=self.is_cancelled,
            )
            with self._lock:
                if self._cancel.is_set():
                    self._progress.status = "cancelled"
                    self._progress.phase = "cancelled"
                    self._progress.message = "Dealer geocoding cancelled."
                    store.finish(
                        job_run_id,
                        "cancelled",
                        result=geocode_result_from_progress(self._progress, result),
                        message=self._progress.message,
                    )
                    return
                self._progress.status = "completed"
                self._progress.phase = "done"
                self._progress.processed = int(result.get("processed", 0))
                self._progress.total = int(result.get("processed", 0))
                self._progress.geocoded = int(result.get("batch_geocoded", 0))
                self._progress.failed = int(result.get("batch_failed", 0))
                self._progress.remaining = int(result.get("remaining", 0))
                self._progress.message = (
                    f"Geocoded {result.get('batch_geocoded', 0)} dealer(s) this run; "
                    f"{result.get('remaining', 0)} remaining."
                )
                store.finish(
                    job_run_id,
                    "completed",
                    result=geocode_result_from_progress(self._progress, result),
                    message=self._progress.message,
                )
        except Exception as exc:
            with self._lock:
                self._progress.status = "failed"
                self._progress.phase = "failed"
                self._progress.error = str(exc)
                self._progress.message = f"Dealer geocoding failed: {exc}"
            store.finish(
                job_run_id,
                "failed",
                result=geocode_result_from_progress(self._progress, result),
                error=str(exc),
                message=self._progress.message,
            )
        finally:
            conn.close()


geocode_job_manager = GeocodeJobManager()


def maybe_start_geocode_job(database_url: str, *, delay_sec: float = 1.1) -> bool:
    """Start background geocoding when dealers remain and no job is running."""
    from vehicle_inventory.jobs.service import get_job_service

    jobs = get_job_service()
    if jobs.geocode_is_running():
        return False
    conn = open_db_connection(database_url)
    try:
        stats = dealer_geo_stats(conn)
    finally:
        conn.close()
    if int(stats.get("remaining", 0)) <= 0:
        return False
    jobs.start_geocode(limit=None, delay_sec=delay_sec, trigger_source="auto")
    return True
