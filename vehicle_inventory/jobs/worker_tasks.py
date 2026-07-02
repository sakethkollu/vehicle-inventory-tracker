"""RQ worker task entry points."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger
from vehicle_inventory.db import InventoryDb, utc_now
from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.geo.dealer_geo import geocode_all_dealers
from vehicle_inventory.ingest.progress import IngestProgress
from vehicle_inventory.ingest.router import build_ingest_request, run_make_dealer_vehicle_refresh, run_make_ingest, sync_make_catalog
from vehicle_inventory.jobs.runs import (
    JobRunStore,
    geocode_result_from_progress,
    ingest_result_from_progress,
)
from vehicle_inventory.jobs.service import get_job_service
from vehicle_inventory.makes.registry import resolve_database_url

log = get_logger(__name__)


def _database_url_for_make(make_slug: str) -> str:
    return resolve_database_url(make_slug)


def _mark_job_running(store: JobRunStore, service, *, job_run_id: int, live_key: str, payload: dict) -> None:
    store.mark_running(job_run_id)
    running = dict(payload)
    running["status"] = "running"
    if running.get("phase") == "queued":
        running["phase"] = "starting"
    service._set_live(live_key, running)


def run_ingest_task(
    job_run_id: int,
    make_slug: str,
    settings_payload: Dict[str, Any],
    all_models: bool,
    model_codes: Optional[List[str]],
) -> dict:
    configure_logging(level=get_settings().log_level, json_logs=get_settings().log_json)
    database_url = _database_url_for_make(make_slug)
    store = JobRunStore(database_url)
    service = get_job_service(make_slug=make_slug)
    settings = get_settings()
    _mark_job_running(
        store,
        service,
        job_run_id=job_run_id,
        live_key=service._live_ingest_key,
        payload={
            **service.ingest_status(),
            "job_run_id": job_run_id,
            "job_type": "ingest",
            "message": "Worker picked up ingest job...",
        },
    )

    payload = dict(settings_payload)
    payload["all_models"] = all_models
    payload["model_codes"] = model_codes or []
    request = build_ingest_request(
        make_slug,
        payload,
        database_url=database_url,
        schema_path=settings.schema_path,
    )

    def on_progress(progress: IngestProgress) -> None:
        progress_payload = progress.to_dict()
        progress_payload["job_run_id"] = job_run_id
        progress_payload["job_type"] = "ingest"
        service.update_live_ingest(progress_payload)

    try:
        log.info("ingest_started", job_run_id=job_run_id, make=make_slug)
        progress = run_make_ingest(make_slug, request, progress_callback=on_progress)
    except Exception as exc:
        log.exception("ingest_failed", job_run_id=job_run_id, make=make_slug)
        existing = service.ingest_status()
        failed = IngestProgress(status="failed", error=str(exc))
        failed.logs = list(existing.get("logs") or [])
        failed.set_message(f"Ingest failed: {exc}")
        try:
            store.finish(
                job_run_id,
                "failed",
                result=ingest_result_from_progress(failed),
                error=str(exc),
                message=failed.message,
            )
        except Exception:
            log.exception("ingest_finish_failed", job_run_id=job_run_id, phase="failed")
        service.update_live_ingest(failed.to_dict())
        raise

    on_progress(progress)
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

    log.info("ingest_finished", job_run_id=job_run_id, make=make_slug, status=progress.status)
    return progress.to_dict()


def run_geocode_task(job_run_id: int, make_slug: str, params: Dict[str, Any]) -> dict:
    configure_logging(level=get_settings().log_level, json_logs=get_settings().log_json)
    from vehicle_inventory.jobs.geocode_thread import GeocodeProgress

    database_url = _database_url_for_make(make_slug)
    store = JobRunStore(database_url)
    service = get_job_service(make_slug=make_slug)
    conn = open_db_connection(database_url)
    _mark_job_running(
        store,
        service,
        job_run_id=job_run_id,
        live_key=service._live_geocode_key,
        payload={
            **service.geocode_status(),
            "job_run_id": job_run_id,
            "message": "Worker picked up geocode job...",
        },
    )
    progress = GeocodeProgress(
        status="running",
        phase="geocoding",
        message="Starting dealer geocoding...",
        job_run_id=job_run_id,
    )
    service.update_live_geocode(progress.to_dict())

    def on_progress(done: int, total: int, dealer_cd: str) -> None:
        progress.processed = done
        progress.total = total
        progress.current_dealer_cd = dealer_cd
        progress.message = f"Geocoding dealers ({done}/{total}): {dealer_cd}"
        service.update_live_geocode(progress.to_dict())

    result = None
    try:
        result = geocode_all_dealers(
            conn,
            limit=params.get("limit"),
            delay_sec=float(params.get("delay_sec") or 1.1),
            progress_callback=on_progress,
            force=bool(params.get("force")),
            workers=max(1, int(params.get("workers") or 8)),
            should_cancel=service.geocode_should_cancel,
        )
        if service.geocode_should_cancel():
            progress.status = "cancelled"
            progress.phase = "cancelled"
            progress.message = "Dealer geocoding cancelled."
            store.finish(
                job_run_id,
                "cancelled",
                result=geocode_result_from_progress(progress, result),
                message=progress.message,
            )
        else:
            progress.status = "completed"
            progress.phase = "done"
            progress.processed = int(result.get("processed", 0))
            progress.total = int(result.get("processed", 0))
            progress.geocoded = int(result.get("batch_geocoded", 0))
            progress.failed = int(result.get("batch_failed", 0))
            progress.remaining = int(result.get("remaining", 0))
            progress.message = (
                f"Geocoded {result.get('batch_geocoded', 0)} dealer(s) this run; "
                f"{result.get('remaining', 0)} remaining."
            )
            store.finish(
                job_run_id,
                "completed",
                result=geocode_result_from_progress(progress, result),
                message=progress.message,
            )
        service.update_live_geocode(progress.to_dict())
        log.info("geocode_finished", job_run_id=job_run_id, status=progress.status)
        return progress.to_dict()
    except Exception as exc:
        log.exception("geocode_failed", job_run_id=job_run_id)
        progress.status = "failed"
        progress.phase = "failed"
        progress.error = str(exc)
        progress.message = f"Dealer geocoding failed: {exc}"
        store.finish(
            job_run_id,
            "failed",
            result=geocode_result_from_progress(progress, result),
            error=str(exc),
            message=progress.message,
        )
        service.update_live_geocode(progress.to_dict())
        raise
    finally:
        conn.close()


def run_catalog_sync_task(job_run_id: int, make_slug: str, zip_code: str) -> dict:
    configure_logging(level=get_settings().log_level, json_logs=get_settings().log_json)
    database_url = _database_url_for_make(make_slug)
    store = JobRunStore(database_url)
    settings = get_settings()
    try:
        result = sync_make_catalog(
            make_slug,
            database_url=database_url,
            schema_path=settings.schema_path,
            zip_code=zip_code,
        )
        store.finish(
            job_run_id,
            "completed",
            result={"count": result.get("count", 0)},
            message=f"Synced {result.get('count', 0)} model(s).",
        )
        return result
    except Exception as exc:
        store.finish(job_run_id, "failed", error=str(exc), message=f"Catalog sync failed: {exc}")
        raise


def run_dealer_vehicle_refresh_task(
    job_run_id: int,
    make_slug: str,
    settings_payload: Dict[str, Any],
    all_models: bool,
    model_codes: Optional[List[str]],
) -> dict:
    configure_logging(level=get_settings().log_level, json_logs=get_settings().log_json)
    database_url = _database_url_for_make(make_slug)
    store = JobRunStore(database_url)
    service = get_job_service(make_slug=make_slug)
    settings = get_settings()
    _mark_job_running(
        store,
        service,
        job_run_id=job_run_id,
        live_key=service._live_ingest_key,
        payload={
            **service.ingest_status(),
            "job_run_id": job_run_id,
            "job_type": "dealer_vehicle_refresh",
            "message": "Worker picked up dealer vehicle refresh...",
        },
    )

    payload = dict(settings_payload)

    def on_progress(progress: IngestProgress) -> None:
        progress_payload = progress.to_dict()
        progress_payload["job_run_id"] = job_run_id
        progress_payload["job_type"] = "dealer_vehicle_refresh"
        service.update_live_ingest(progress_payload)

    try:
        log.info("dealer_vehicle_refresh_started", job_run_id=job_run_id, make=make_slug)
        progress = run_make_dealer_vehicle_refresh(
            make_slug,
            database_url=database_url,
            schema_path=settings.schema_path,
            all_models=all_models,
            model_codes=model_codes or [],
            distance=int(payload.get("distance") or 1),
            page_size=int(payload.get("page_size") or 100),
            progress_callback=on_progress,
        )
    except Exception as exc:
        log.exception("dealer_vehicle_refresh_failed", job_run_id=job_run_id, make=make_slug)
        existing = service.ingest_status()
        failed = IngestProgress(status="failed", error=str(exc))
        failed.logs = list(existing.get("logs") or [])
        failed.set_message(f"Dealer vehicle refresh failed: {exc}")
        try:
            store.finish(
                job_run_id,
                "failed",
                result=ingest_result_from_progress(failed),
                error=str(exc),
                message=failed.message,
            )
        except Exception:
            log.exception("dealer_refresh_finish_failed", job_run_id=job_run_id, phase="failed")
        service.update_live_ingest(failed.to_dict())
        raise

    on_progress(progress)
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

    log.info(
        "dealer_vehicle_refresh_finished",
        job_run_id=job_run_id,
        make=make_slug,
        status=progress.status,
    )
    return progress.to_dict()
