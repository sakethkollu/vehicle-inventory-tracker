"""Redis-backed and in-process job orchestration."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from vehicle_inventory.core.config import Settings, get_settings
from vehicle_inventory.jobs.geocode_thread import GeocodeJobManager, GeocodeProgress
from vehicle_inventory.jobs.ingest_thread import IngestJobManager
from vehicle_inventory.ingest.progress import IngestProgress
from vehicle_inventory.jobs.runs import JobRunStore, job_status_is_active
from vehicle_inventory.core.logging import get_logger
from vehicle_inventory.jobs.rq_maintenance import prepare_job_enqueue
from vehicle_inventory.makes.registry import MakeProfile, get_default_make_slug, get_make_profile

log = get_logger(__name__)

INGEST_JOB_TIMEOUT_SEC = 4 * 3600
GEOCODE_JOB_TIMEOUT_SEC = 4 * 3600


def _ingest_payload(payload: dict, *, schema_path: Path) -> dict:
    result = dict(payload)
    result["schema_path"] = str(schema_path)
    return result


class JobService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        make_profile: Optional[MakeProfile] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.make = make_profile or get_make_profile(get_default_make_slug())
        self.database_url = self.make.database_url
        self._live_ingest_key = f"{self.make.redis_prefix}:job:live:ingest"
        self._live_geocode_key = f"{self.make.redis_prefix}:job:live:geocode"
        self._cancel_geocode_key = f"{self.make.redis_prefix}:job:cancel:geocode"
        self._ingest_thread = IngestJobManager()
        self._geocode_thread = GeocodeJobManager()
        self._configure_thread_backends()
        self._redis = None
        self._queue = None
        if self.settings.use_redis_jobs:
            self._init_redis()

    def _configure_thread_backends(self) -> None:
        self._ingest_thread.configure(self.database_url)
        self._geocode_thread.configure(self.database_url)

    def _init_redis(self) -> None:
        from redis import Redis
        from rq import Queue

        self._redis = Redis.from_url(self.settings.redis_url)
        self._queue = Queue(
            "ingest",
            connection=self._redis,
            default_timeout=INGEST_JOB_TIMEOUT_SEC,
        )
        self._geocode_queue = Queue(
            "geocode",
            connection=self._redis,
            default_timeout=GEOCODE_JOB_TIMEOUT_SEC,
        )
        self._default_queue = Queue("default", connection=self._redis)

    def _store(self) -> JobRunStore:
        return JobRunStore(self.database_url)

    def _set_live(self, key: str, payload: dict) -> None:
        if self._redis is None:
            return
        self._redis.set(key, json.dumps(payload), ex=86400)

    def _get_live(self, key: str) -> dict:
        if self._redis is None:
            return {}
        raw = self._redis.get(key)
        if not raw:
            return {"status": "idle"}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "idle"}

    def ingest_status(self) -> dict:
        if self.settings.use_redis_jobs:
            return self._get_live(self._live_ingest_key)
        return self._ingest_thread.status()

    def geocode_status(self) -> dict:
        if self.settings.use_redis_jobs:
            return self._get_live(self._live_geocode_key)
        return self._geocode_thread.status()

    def ingest_is_running(self) -> bool:
        return job_status_is_active(self.ingest_status().get("status"))

    def geocode_is_running(self) -> bool:
        return job_status_is_active(self.geocode_status().get("status"))

    def _enqueue(
        self,
        queue,
        func_path: str,
        *args,
        job_id: str,
        timeout: int,
    ):
        prepare_job_enqueue(queue, job_id)
        job = queue.enqueue(
            func_path,
            *args,
            job_id=job_id,
            timeout=timeout,
        )
        log.info(
            "rq_job_enqueued",
            queue=queue.name,
            job_id=job.id,
            status=job.get_status(refresh=False),
        )
        return job

    def start_ingest(
        self,
        *,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]] = None,
        all_models: bool = False,
        trigger_source: str = "ui",
    ) -> dict:
        if self.settings.use_redis_jobs:
            store = self._store()
            from vehicle_inventory.jobs.runs import ingest_params_from_payload

            ingest_payload = dict(payload)
            params = ingest_params_from_payload(
                ingest_payload,
                all_models=all_models,
                model_codes=model_codes,
                make_slug=self.make.slug,
            )
            job_run_id = store.start(
                "ingest",
                params,
                trigger_source=trigger_source,
                message="Queued ingest job...",
                status="queued",
            )
            self._set_live(
                self._live_ingest_key,
                {
                    "status": "queued",
                    "phase": "queued",
                    "message": f"Queued ingest near ZIP {params['zip_code']} ({params['distance']} mi)...",
                    "job_run_id": job_run_id,
                    "job_type": "ingest",
                    "zip_code": params["zip_code"],
                    "distance": params["distance"],
                    "nationwide": params.get("nationwide"),
                    "percent": 0.0,
                    "make": self.make.slug,
                },
            )
            self._enqueue(
                self._queue,
                "vehicle_inventory.jobs.worker_tasks.run_ingest_task",
                job_run_id,
                self.make.slug,
                self.database_url,
                _ingest_payload(ingest_payload, schema_path=self.settings.schema_path),
                all_models,
                model_codes,
                job_id=f"{self.make.slug}-ingest-{job_run_id}",
                timeout=INGEST_JOB_TIMEOUT_SEC,
            )
            return self.ingest_status()
        self._ingest_thread.start(
            make_slug=self.make.slug,
            payload=payload,
            model_codes=model_codes,
            all_models=all_models,
            trigger_source=trigger_source,
        )
        return self._ingest_thread.status()

    def start_dealer_vehicle_refresh(
        self,
        *,
        payload: Dict[str, Any],
        model_codes: Optional[List[str]] = None,
        all_models: bool = False,
        trigger_source: str = "ui",
    ) -> dict:
        if self.make.slug != "mazda":
            raise RuntimeError("Dealer vehicle refresh is only supported for Mazda.")
        if self.settings.use_redis_jobs:
            store = self._store()
            from vehicle_inventory.jobs.runs import dealer_vehicle_refresh_params_from_payload

            refresh_payload = dict(payload)
            params = dealer_vehicle_refresh_params_from_payload(
                refresh_payload,
                all_models=all_models,
                model_codes=model_codes,
                make_slug=self.make.slug,
            )
            job_run_id = store.start(
                "dealer_vehicle_refresh",
                params,
                trigger_source=trigger_source,
                message="Queued dealer vehicle refresh...",
                status="queued",
            )
            self._set_live(
                self._live_ingest_key,
                {
                    "status": "queued",
                    "phase": "queued",
                    "message": "Queued dealer vehicle refresh (1 mi per dealer ZIP)...",
                    "job_run_id": job_run_id,
                    "job_type": "dealer_vehicle_refresh",
                    "distance": params.get("distance", 1),
                    "percent": 0.0,
                    "make": self.make.slug,
                },
            )
            self._enqueue(
                self._queue,
                "vehicle_inventory.jobs.worker_tasks.run_dealer_vehicle_refresh_task",
                job_run_id,
                self.make.slug,
                self.database_url,
                _ingest_payload(refresh_payload, schema_path=self.settings.schema_path),
                all_models,
                model_codes,
                job_id=f"{self.make.slug}-dealer-refresh-{job_run_id}",
                timeout=INGEST_JOB_TIMEOUT_SEC,
            )
            return self.ingest_status()
        self._ingest_thread.start_dealer_refresh(
            make_slug=self.make.slug,
            payload=payload,
            model_codes=model_codes,
            all_models=all_models,
            trigger_source=trigger_source,
        )
        return self._ingest_thread.status()

    def start_geocode(
        self,
        *,
        limit: Optional[int] = None,
        delay_sec: float = 1.1,
        force: bool = False,
        workers: int = 8,
        trigger_source: str = "ui",
    ) -> dict:
        if self.settings.use_redis_jobs:
            store = self._store()
            from vehicle_inventory.jobs.runs import geocode_params

            params = geocode_params(limit=limit, delay_sec=delay_sec, force=force, workers=workers)
            params["make"] = self.make.slug
            job_run_id = store.start(
                "geocode",
                params,
                trigger_source=trigger_source,
                message="Queued geocode job...",
                status="queued",
            )
            if self._redis is not None:
                self._redis.delete(self._cancel_geocode_key)
            self._set_live(
                self._live_geocode_key,
                GeocodeProgress(
                    status="queued",
                    phase="queued",
                    message="Queued geocode job...",
                    job_run_id=job_run_id,
                ).to_dict(),
            )
            self._enqueue(
                self._geocode_queue,
                "vehicle_inventory.jobs.worker_tasks.run_geocode_task",
                job_run_id,
                self.make.slug,
                self.database_url,
                params,
                job_id=f"{self.make.slug}-geocode-{job_run_id}",
                timeout=GEOCODE_JOB_TIMEOUT_SEC,
            )
            return self.geocode_status()
        self._geocode_thread.start(
            limit=limit,
            delay_sec=delay_sec,
            force=force,
            workers=workers,
            trigger_source=trigger_source,
        )
        return self._geocode_thread.status()

    def cancel_geocode(self) -> bool:
        if self.settings.use_redis_jobs:
            if not self.geocode_is_running():
                return False
            if self._redis is not None:
                self._redis.set(self._cancel_geocode_key, "1", ex=3600)
            return True
        return self._geocode_thread.cancel()

    def update_live_ingest(self, progress: IngestProgress | dict) -> None:
        payload = progress if isinstance(progress, dict) else progress.to_dict()
        payload.setdefault("make", self.make.slug)
        existing = self.ingest_status()
        for key in ("job_run_id", "job_type", "zip_code", "distance", "page_size", "nationwide"):
            if not payload.get(key) and existing.get(key):
                payload[key] = existing[key]
        self._set_live(self._live_ingest_key, payload)

    def update_live_geocode(self, progress: GeocodeProgress | dict) -> None:
        payload = progress if isinstance(progress, dict) else progress.to_dict()
        payload.setdefault("make", self.make.slug)
        self._set_live(self._live_geocode_key, payload)

    def geocode_should_cancel(self) -> bool:
        if self._redis is None:
            return False
        return bool(self._redis.get(self._cancel_geocode_key))

    def _rq_job_status(self, job_type: str, job_run_id: int) -> str:
        if not self.settings.use_redis_jobs or self._redis is None:
            return "missing"
        from rq.exceptions import NoSuchJobError
        from rq.job import Job

        prefix = {"ingest": "ingest", "geocode": "geocode", "dealer_vehicle_refresh": "dealer-refresh"}.get(
            job_type
        )
        if not prefix:
            return "missing"
        try:
            rq_job = Job.fetch(f"{self.make.slug}-{prefix}-{job_run_id}", connection=self._redis)
        except NoSuchJobError:
            return "missing"
        if rq_job.is_queued:
            return "queued"
        if rq_job.is_started:
            return "started"
        if rq_job.is_finished:
            return "finished"
        if rq_job.is_failed:
            return "failed"
        return "missing"

    def _rq_job_is_active(self, job_type: str, job_run_id: int) -> bool:
        return self._rq_job_status(job_type, job_run_id) in {"queued", "started"}

    def _sanitize_live_status(
        self,
        live: dict,
        *,
        job_type: str,
        live_key: str,
        store: JobRunStore,
    ) -> dict:
        status = live.get("status")
        if not job_status_is_active(status):
            return live

        if not self.settings.use_redis_jobs:
            if job_type == "ingest":
                return live if self._ingest_thread.is_running() else {"status": "idle"}
            if job_type == "geocode":
                return live if self._geocode_thread.is_running() else {"status": "idle"}
            return live

        job_run_id = live.get("job_run_id")
        if not job_run_id:
            self._set_live(live_key, {"status": "idle"})
            return {"status": "idle"}

        run = store.get(int(job_run_id))
        if run and not job_status_is_active(run.get("status")):
            terminal = {
                "status": run["status"],
                "job_run_id": job_run_id,
                "message": run.get("message") or "",
            }
            if run.get("error"):
                terminal["error"] = run["error"]
            result = run.get("result") or {}
            if isinstance(result, dict):
                terminal.update(result)
            self._set_live(live_key, terminal)
            return terminal

        rq_state = self._rq_job_status(job_type, int(job_run_id))
        if rq_state == "queued":
            resolved = {
                **live,
                "status": "queued",
                "phase": "queued",
                "message": live.get("message") or "Waiting for worker...",
            }
            if resolved != live:
                self._set_live(live_key, resolved)
            return resolved

        if rq_state == "started":
            resolved = dict(live)
            if resolved.get("status") != "running":
                resolved["status"] = "running"
            if resolved.get("phase") == "queued":
                resolved["phase"] = "starting"
            if run and run.get("status") == "queued":
                store.mark_running(int(job_run_id))
            if resolved != live:
                self._set_live(live_key, resolved)
            return resolved

        if not self._rq_job_is_active(job_type, int(job_run_id)):
            self._set_live(live_key, {"status": "idle"})
            return {"status": "idle"}

        return live

    def _resolve_live_ingest_job_type(self, live: dict, store: JobRunStore) -> str:
        job_type = str(live.get("job_type") or "").strip()
        if job_type:
            return job_type
        job_run_id = live.get("job_run_id")
        if job_run_id:
            run = store.get(int(job_run_id))
            if run and run.get("job_type"):
                return str(run["job_type"])
        return "ingest"

    def resolved_ingest_status(self, store: JobRunStore) -> dict:
        live = self.ingest_status()
        return self._sanitize_live_status(
            live,
            job_type=self._resolve_live_ingest_job_type(live, store),
            live_key=self._live_ingest_key,
            store=store,
        )

    def resolved_geocode_status(self, store: JobRunStore) -> dict:
        live = self.geocode_status()
        return self._sanitize_live_status(
            live,
            job_type="geocode",
            live_key=self._live_geocode_key,
            store=store,
        )

    @staticmethod
    def jobs_are_active(ingest: dict, geocode: dict) -> bool:
        return job_status_is_active(ingest.get("status")) or job_status_is_active(geocode.get("status"))

    def list_runs(self, **kwargs) -> List[dict]:
        return self._store().list_runs(**kwargs)

    def get_run(self, job_run_id: int) -> Optional[dict]:
        return self._store().get(job_run_id)

    def summary(self, *, since_days: int = 30) -> Dict[str, dict]:
        return self._store().summary(since_days=since_days)

    def reconcile_stale_runs(self, store: JobRunStore) -> int:
        from vehicle_inventory.jobs.runs import (
            reconcile_live_job_run,
            reconcile_rq_stale_runs,
        )

        repaired = 0
        if reconcile_live_job_run(store, self.ingest_status()):
            repaired += 1
        if reconcile_live_job_run(store, self.geocode_status()):
            repaired += 1
        if self.settings.use_redis_jobs and self.settings.redis_url:
            repaired += reconcile_rq_stale_runs(store, self.settings.redis_url)
        return repaired


_job_services: Dict[str, JobService] = {}
_job_service_lock = threading.Lock()


def get_job_service(
    settings: Optional[Settings] = None,
    *,
    make_slug: Optional[str] = None,
) -> JobService:
    runtime_settings = settings or get_settings()
    slug = (make_slug or get_default_make_slug()).strip().lower()
    with _job_service_lock:
        existing = _job_services.get(slug)
        if existing is None or existing.settings != runtime_settings:
            _job_services[slug] = JobService(runtime_settings, make_profile=get_make_profile(slug))
        return _job_services[slug]
