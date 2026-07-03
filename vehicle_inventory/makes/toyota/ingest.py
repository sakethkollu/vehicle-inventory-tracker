"""Toyota USA GraphQL live-ingest orchestration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from vehicle_inventory.db import InventoryDb, utc_now
from vehicle_inventory.db.run_scope import refresh_series_latest_runs, repair_series_latest_runs
from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback, emit_progress
from vehicle_inventory.makes.toyota.client import (
    PageFetchProgress,
    ToyotaClientConfig,
    ToyotaInventoryClient,
    ToyotaModel,
)
from vehicle_inventory.makes.toyota.waf_token import fetch_waf_token

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0"
)


@dataclass
class LiveIngestSettings:
    database_url: str
    schema_path: Path
    zip_code: str = "95132"
    distance: int = 500
    page_size: int = 250
    lead_id: str = "3807e828-1b31-4efa-962f-7646948b7d4b"
    series_code: str = "rav4pluginhybrid"
    model_codes: Optional[List[str]] = None
    all_models: bool = False
    waf_token: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    referer: str = "https://www.toyota.com/"
    origin: str = "https://www.toyota.com"
    x_api_key: str = "undefined"
    interior_media: bool = True
    page_delay: float = 0.5
    max_retries: int = 5
    retry_backoff: float = 1.0
    waf_refresh_cooldown: float = 30.0
    waf_post_refresh_delay: float = 3.0
    rate_limit_backoff: float = 20.0
    stream_to_db: bool = False
    make_slug: str = "toyota"


def resolve_waf_token(waf_token: str = "") -> str:
    token = waf_token or os.getenv("TOYOTA_WAF_TOKEN", "")
    if token:
        return token
    from vehicle_inventory.makes.toyota.waf_token import fetch_waf_token

    return fetch_waf_token()


def refresh_waf_token_playwright(
    settings: LiveIngestSettings,
    progress_callback: Optional[ProgressCallback] = None,
    progress: Optional[IngestProgress] = None,
) -> str:
    from vehicle_inventory.makes.toyota.waf_token import fetch_waf_token

    message = "Fetching fresh WAF token via Playwright..."
    print(f"[ingest] {message}", flush=True)
    if progress_callback:
        if progress is None:
            progress = IngestProgress(status="running", phase="token")
        emit_progress(progress, progress_callback, message=message, phase="token")

    token = fetch_waf_token()
    settings.waf_token = token
    os.environ["TOYOTA_WAF_TOKEN"] = token
    print(f"[ingest] WAF token refreshed: {token[:48]}...", flush=True)
    return token


def build_client(
    settings: LiveIngestSettings,
    waf_token: str,
    waf_token_refresh: Optional[Callable[[], str]] = None,
) -> ToyotaInventoryClient:
    return ToyotaInventoryClient(
        ToyotaClientConfig(
            user_agent=settings.user_agent,
            referer=settings.referer,
            origin=settings.origin,
            x_api_key=settings.x_api_key,
            x_aws_waf_token=waf_token,
            page_delay_sec=settings.page_delay,
            max_retries=settings.max_retries,
            retry_backoff_sec=settings.retry_backoff,
            waf_token_refresh=waf_token_refresh,
            waf_refresh_cooldown_sec=settings.waf_refresh_cooldown,
            waf_post_refresh_delay_sec=settings.waf_post_refresh_delay,
            rate_limit_backoff_sec=settings.rate_limit_backoff,
        )
    )


def sync_model_catalog(
    client: ToyotaInventoryClient,
    db: InventoryDb,
    zip_code: str,
    ts: str,
) -> List[ToyotaModel]:
    models = client.fetch_models(zip_code=zip_code)
    db.upsert_model_catalog(
        [
            {
                "model_code": model.model_code,
                "series": model.series,
                "title": model.title,
                "year": model.year,
                "msrp": model.msrp,
                "image": model.image,
                "as_shown": model.as_shown,
                "top_label": model.top_label,
            }
            for model in models
        ],
        ts=ts,
    )
    db.commit()
    return models


def _models_from_catalog_rows(rows: List[Dict]) -> List[ToyotaModel]:
    return [
        ToyotaModel(
            model_code=row["model_code"],
            series=row.get("series") or row["model_code"],
            title=row.get("title") or row["model_code"],
            year=str(row.get("year") or ""),
            msrp=row.get("msrp"),
            image=row.get("image"),
            as_shown=row.get("as_shown"),
            top_label=row.get("top_label"),
        )
        for row in rows
    ]


def resolve_target_models(
    settings: LiveIngestSettings,
    client: ToyotaInventoryClient,
    db: InventoryDb,
    ts: str,
) -> List[ToyotaModel]:
    if settings.all_models or settings.model_codes:
        if settings.all_models:
            models = sync_model_catalog(client, db, settings.zip_code, ts)
        else:
            catalog_rows = db.list_model_catalog()
            if not catalog_rows:
                raise RuntimeError(
                    "Model catalog is empty. Use Admin → Sync Model Catalog before ingesting "
                    "selected models."
                )
            models = _models_from_catalog_rows(catalog_rows)
        if settings.model_codes:
            selected = {code.strip().lower() for code in settings.model_codes if code.strip()}
            models = [model for model in models if model.model_code.lower() in selected]
        if not models:
            if settings.model_codes:
                requested = ", ".join(settings.model_codes)
                raise RuntimeError(
                    f"No catalog entries matched the selected model(s): {requested}. "
                    "Sync the model catalog, then try again."
                )
            raise RuntimeError("No models matched the requested ingest selection.")
        return models

    return [
        ToyotaModel(
            model_code=settings.series_code,
            series=settings.series_code,
            title=settings.series_code,
            year="",
        )
    ]


def persist_run(
    database_url: str,
    schema_path: Path,
    queried_at: str,
    zip_code: str,
    distance: int,
    page_size: int,
    lead_id: str,
    series_code: str,
    archive_dir: Optional[str],
    vehicles: List[Dict],
    *,
    mark_missing_inactive: bool = True,
) -> int:
    db = InventoryDb(database_url=database_url, schema_path=schema_path)
    db.initialize()
    run_id = db.create_run(
        queried_at=queried_at,
        zip_code=zip_code,
        distance=distance,
        page_size=page_size,
        series_codes=[series_code],
        lead_id=lead_id,
        archive_dir=archive_dir,
    )

    ts = queried_at
    try:
        processed = 0
        total = len(vehicles)
        checkpoint = 500
        for vehicle in vehicles:
            db.process_vehicle(run_id=run_id, series_code=series_code, vehicle=vehicle, ts=ts)
            processed += 1
            if processed == total or processed % checkpoint == 0:
                print(f"[db] processed {processed}/{total}", flush=True)
        inactive_count = 0
        if mark_missing_inactive:
            inactive_count = db.mark_inactive_not_seen(
                run_id=run_id, series_codes=[series_code], ts=ts
            )
        refresh_series_latest_runs(db.conn, force=True)
        db.commit()
    except Exception:
        db.rollback()
        db.close()
        raise
    db.close()
    print(
        f"Run {run_id} complete. Vehicles processed: {len(vehicles)}. "
        f"Marked inactive: {inactive_count}."
    )
    return run_id


def ingest_single_model(
    client: ToyotaInventoryClient,
    settings: LiveIngestSettings,
    model: ToyotaModel,
    queried_at: str,
    on_page_fetched: Optional[Callable[[PageFetchProgress], None]] = None,
    db: Optional[InventoryDb] = None,
) -> None:
    if settings.stream_to_db:
        if db is None:
            raise RuntimeError("stream_to_db requires an open InventoryDb connection")
        _ingest_single_model_streaming(
            client=client,
            settings=settings,
            model=model,
            queried_at=queried_at,
            db=db,
            on_page_fetched=on_page_fetched,
        )
        return

    fetch_result = client.fetch_all_pages(
        zip_code=settings.zip_code,
        distance=settings.distance,
        page_size=settings.page_size,
        series_code=model.model_code,
        lead_id=settings.lead_id,
        interior_media=settings.interior_media,
        progress_callback=on_page_fetched,
    )

    if fetch_result.partial:
        print(
            f"Warning: {model.model_code} fetch stopped early after page "
            f"{fetch_result.last_page_fetched}/{fetch_result.total_pages}. "
            f"{fetch_result.fetch_error}",
            flush=True,
        )
    else:
        print(
            f"Fetch complete for {model.model_code}. pages={len(fetch_result.raw_pages)} "
            f"vehicles={len(fetch_result.vehicles)}",
            flush=True,
        )

    persist_run(
        database_url=settings.database_url,
        schema_path=settings.schema_path,
        queried_at=queried_at,
        zip_code=settings.zip_code,
        distance=settings.distance,
        page_size=settings.page_size,
        lead_id=settings.lead_id,
        series_code=model.model_code,
        archive_dir=None,
        vehicles=fetch_result.vehicles,
        mark_missing_inactive=not fetch_result.partial,
    )


def _ingest_single_model_streaming(
    client: ToyotaInventoryClient,
    settings: LiveIngestSettings,
    model: ToyotaModel,
    queried_at: str,
    db: InventoryDb,
    on_page_fetched: Optional[Callable[[PageFetchProgress], None]] = None,
) -> None:
    run_id = db.create_run(
        queried_at=queried_at,
        zip_code=settings.zip_code,
        distance=settings.distance,
        page_size=settings.page_size,
        series_codes=[model.model_code],
        lead_id=settings.lead_id,
        archive_dir=None,
    )

    persisted_total = 0

    def persist_page(page_progress: PageFetchProgress) -> None:
        nonlocal persisted_total
        for vehicle in page_progress.vehicles:
            db.process_vehicle(
                run_id=run_id,
                series_code=model.model_code,
                vehicle=vehicle,
                ts=queried_at,
            )
            persisted_total += 1
        db.commit()
        print(
            f"[db] {model.model_code} page {page_progress.page_no}/{page_progress.total_pages}: "
            f"persisted {len(page_progress.vehicles)} vehicles "
            f"(model total {persisted_total})",
            flush=True,
        )
        if on_page_fetched:
            on_page_fetched(page_progress)

    fetch_result = client.fetch_all_pages(
        zip_code=settings.zip_code,
        distance=settings.distance,
        page_size=settings.page_size,
        series_code=model.model_code,
        lead_id=settings.lead_id,
        interior_media=settings.interior_media,
        progress_callback=persist_page,
    )

    inactive_count = 0
    if not fetch_result.partial:
        inactive_count = db.mark_inactive_not_seen(
            run_id=run_id,
            series_codes=[model.model_code],
            ts=queried_at,
        )
    else:
        print(
            f"Warning: skipping mark-inactive for {model.model_code} because fetch was partial.",
            flush=True,
        )

    refresh_series_latest_runs(db.conn, force=True)
    db.commit()

    if fetch_result.partial:
        print(
            f"Warning: {model.model_code} fetch stopped early after page "
            f"{fetch_result.last_page_fetched}/{fetch_result.total_pages}. "
            f"{fetch_result.fetch_error}. Persisted {persisted_total} vehicles.",
            flush=True,
        )
    else:
        print(
            f"Run {run_id} complete for {model.model_code}. "
            f"Persisted {persisted_total} vehicles. Marked inactive: {inactive_count}."
        )


def run_live_ingest(
    settings: LiveIngestSettings,
    progress_callback: Optional[ProgressCallback] = None,
) -> IngestProgress:
    progress = IngestProgress(status="running", phase="token")
    progress.set_message("Resolving WAF token...")
    if progress_callback:
        progress_callback(progress)

    waf_token = resolve_waf_token(settings.waf_token)

    def on_waf_token_refresh() -> str:
        return refresh_waf_token_playwright(settings, progress_callback, progress)

    client = build_client(settings, waf_token, waf_token_refresh=on_waf_token_refresh)
    queried_at = utc_now()

    db = InventoryDb(database_url=settings.database_url, schema_path=settings.schema_path)
    db.initialize()

    catalog_message = (
        "Resolving selected models from catalog..."
        if settings.model_codes and not settings.all_models
        else "Fetching Toyota model catalog..."
    )
    emit_progress(
        progress,
        progress_callback,
        phase="catalog",
        message=catalog_message,
        percent=1.0,
    )

    models = resolve_target_models(settings, client, db, queried_at)
    if not settings.stream_to_db:
        db.close()
        db = None

    emit_progress(
        progress,
        progress_callback,
        total_models=len(models),
        phase="ingesting",
        message=f"Ingesting {len(models)} model(s)...",
    )

    if settings.stream_to_db and db is None:
        db = InventoryDb(database_url=settings.database_url, schema_path=settings.schema_path)
        db.initialize()

    try:
        for index, model in enumerate(models, start=1):
            emit_progress(
                progress,
                progress_callback,
                model_index=index,
                current_model=model.model_code,
                current_model_title=model.title or model.series or model.model_code,
                current_page=0,
                total_pages=0,
                message=f"Ingesting {model.title or model.series or model.model_code} ({model.model_code})...",
                percent=max(2.0, ((index - 1) / max(progress.total_models, 1)) * 100.0),
            )

            fetched_total = 0

            def on_page_fetched(page_progress: PageFetchProgress) -> None:
                nonlocal fetched_total
                page_vehicle_count = page_progress.vehicle_count
                fetched_total += page_vehicle_count
                progress.vehicles_fetched += page_vehicle_count
                if settings.stream_to_db:
                    progress.vehicles_persisted += page_vehicle_count
                model_fraction = page_progress.page_no / max(page_progress.total_pages, 1)
                overall = ((index - 1) + model_fraction) / max(progress.total_models, 1)
                persisted_note = (
                    f", {progress.vehicles_persisted:,} saved"
                    if settings.stream_to_db
                    else ""
                )
                emit_progress(
                    progress,
                    progress_callback,
                    current_page=page_progress.page_no,
                    total_pages=page_progress.total_pages,
                    vehicles_fetched=progress.vehicles_fetched,
                    vehicles_persisted=progress.vehicles_persisted,
                    percent=max(2.0, min(99.0, overall * 100.0)),
                    message=(
                        f"{progress.current_model_title}: page {page_progress.page_no}/"
                        f"{page_progress.total_pages} "
                        f"({page_vehicle_count} vehicles this page, {fetched_total} this model"
                        f"{persisted_note})"
                    ),
                )
                print(
                    f"[fetch] {model.model_code} page {page_progress.page_no}/"
                    f"{page_progress.total_pages} "
                    f"vehicles_this_page={page_vehicle_count} model_total={fetched_total}",
                    flush=True,
                )

            ingest_single_model(
                client=client,
                settings=settings,
                model=model,
                queried_at=queried_at,
                on_page_fetched=on_page_fetched,
                db=db,
            )
            progress.completed_models.append(model.model_code)
        if db is not None and settings.stream_to_db:
            from vehicle_inventory.jobs.service import get_job_service

            jobs = get_job_service(make_slug=settings.make_slug)
            if not jobs.geocode_is_running():
                try:
                    jobs.start_geocode(limit=None, delay_sec=1.1, trigger_source="auto")
                    geocode_message = "Dealer geocoding started in background..."
                except RuntimeError:
                    geocode_message = "Dealer geocoding already running in background."
            else:
                geocode_message = "Dealer geocoding already running in background."
            emit_progress(progress, progress_callback, message=geocode_message)
    except Exception:
        if db is not None and settings.stream_to_db:
            try:
                repair_series_latest_runs(db.conn)
                db.commit()
            except Exception as exc:
                print(
                    f"[toyota] failed to repair series latest runs after ingest error: {exc}",
                    flush=True,
                )
        raise
    finally:
        if db is not None:
            db.close()

    emit_progress(
        progress,
        progress_callback,
        status="completed",
        phase="done",
        percent=100.0,
        message=f"Ingest complete for {len(models)} model(s).",
    )
    return progress
