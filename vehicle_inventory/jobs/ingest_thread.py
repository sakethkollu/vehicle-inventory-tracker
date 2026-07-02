"""Background ingest job manager for the web UI."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.ingest.progress import IngestProgress
from vehicle_inventory.ingest.router import build_ingest_request, run_make_dealer_vehicle_refresh, run_make_ingest
from vehicle_inventory.jobs.runs import (
    JobRunStore,
    dealer_vehicle_refresh_params_from_payload,
    ingest_params_from_payload,
    ingest_result_from_progress,
)
from vehicle_inventory.core.logging import get_logger

log = get_logger(__name__)


class IngestJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._progress = IngestProgress()
        self._job_run_id: Optional[int] = None
        self._database_url = ""
        self._make_slug = "toyota"

    def configure(self, database_url: str) -> None:
        with self._lock:
            self._database_url = database_url

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            payload = self._progress.to_dict()
            if self._job_run_id is not None:
                payload["job_run_id"] = self._job_run_id
            return payload

    def start(
        self,
        *,
        make_slug: str,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]] = None,
        all_models: bool = False,
        trigger_source: str = "ui",
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("An ingest job is already running.")
            self._progress = IngestProgress(
                status="running",
                phase="starting",
                percent=0.0,
            )
            self._progress.set_message("Starting ingest...")
            self._make_slug = make_slug
            store = JobRunStore(self._database_url)
            self._job_run_id = store.start(
                "ingest",
                ingest_params_from_payload(
                    payload,
                    all_models=all_models,
                    model_codes=model_codes,
                    make_slug=make_slug,
                ),
                trigger_source=trigger_source,
                message="Starting ingest...",
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(make_slug, payload, model_codes, all_models, self._job_run_id),
                daemon=True,
            )
            self._thread.start()

    def start_dealer_refresh(
        self,
        *,
        make_slug: str,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]] = None,
        all_models: bool = False,
        trigger_source: str = "ui",
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("An ingest job is already running.")
            self._progress = IngestProgress(
                status="running",
                phase="starting",
                percent=0.0,
            )
            self._progress.set_message("Starting dealer vehicle refresh...")
            self._make_slug = make_slug
            store = JobRunStore(self._database_url)
            self._job_run_id = store.start(
                "dealer_vehicle_refresh",
                dealer_vehicle_refresh_params_from_payload(
                    payload,
                    all_models=all_models,
                    model_codes=model_codes,
                    make_slug=make_slug,
                ),
                trigger_source=trigger_source,
                message="Starting dealer vehicle refresh...",
            )
            self._thread = threading.Thread(
                target=self._run_dealer_refresh,
                args=(make_slug, payload, model_codes, all_models, self._job_run_id),
                daemon=True,
            )
            self._thread.start()

    def _update(self, progress: IngestProgress) -> None:
        with self._lock:
            self._progress = progress

    def _run(
        self,
        make_slug: str,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]],
        all_models: bool,
        job_run_id: int,
    ) -> None:
        store = JobRunStore(self._database_url)
        settings = get_settings()
        ingest_payload = dict(payload)
        ingest_payload["all_models"] = all_models
        ingest_payload["model_codes"] = model_codes or []
        request = build_ingest_request(
            make_slug,
            ingest_payload,
            database_url=self._database_url,
            schema_path=settings.schema_path,
        )
        try:
            progress = run_make_ingest(make_slug, request, progress_callback=self._update)
        except Exception as exc:
            with self._lock:
                self._progress.status = "failed"
                self._progress.error = str(exc)
                self._progress.set_message(f"Ingest failed: {exc}")
            try:
                store.finish(
                    job_run_id,
                    "failed",
                    result=ingest_result_from_progress(self._progress),
                    error=str(exc),
                    message=self._progress.message,
                )
            except Exception:
                log.exception("ingest_finish_failed", job_run_id=job_run_id, phase="failed")
            return

        with self._lock:
            self._progress = progress
        try:
            store.finish(
                job_run_id,
                progress.status,
                result=ingest_result_from_progress(progress),
                error=progress.error,
                message=progress.message,
            )
        except Exception:
            log.exception("ingest_finish_failed", job_run_id=job_run_id, phase="completed")

    def _run_dealer_refresh(
        self,
        make_slug: str,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]],
        all_models: bool,
        job_run_id: int,
    ) -> None:
        store = JobRunStore(self._database_url)
        settings = get_settings()
        refresh_payload = dict(payload)
        try:
            progress = run_make_dealer_vehicle_refresh(
                make_slug,
                database_url=self._database_url,
                schema_path=settings.schema_path,
                all_models=all_models,
                model_codes=model_codes or [],
                distance=int(refresh_payload.get("distance") or 1),
                page_size=int(refresh_payload.get("page_size") or 100),
                progress_callback=self._update,
            )
        except Exception as exc:
            with self._lock:
                self._progress.status = "failed"
                self._progress.error = str(exc)
                self._progress.set_message(f"Dealer vehicle refresh failed: {exc}")
            try:
                store.finish(
                    job_run_id,
                    "failed",
                    result=ingest_result_from_progress(self._progress),
                    error=str(exc),
                    message=self._progress.message,
                )
            except Exception:
                log.exception("dealer_refresh_finish_failed", job_run_id=job_run_id, phase="failed")
            return

        with self._lock:
            self._progress = progress
        try:
            store.finish(
                job_run_id,
                progress.status,
                result=ingest_result_from_progress(progress),
                error=progress.error,
                message=progress.message,
            )
        except Exception:
            log.exception("dealer_refresh_finish_failed", job_run_id=job_run_id, phase="completed")


ingest_job_manager = IngestJobManager()
