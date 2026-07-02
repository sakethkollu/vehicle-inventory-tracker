"""Mazda USA inventory ingest into the shared MySQL schema."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from vehicle_inventory.db import InventoryDb, utc_now
from vehicle_inventory.db.run_scope import refresh_series_latest_runs
from vehicle_inventory.ingest.progress import IngestProgress, ProgressCallback, emit_progress
from vehicle_inventory.makes.mazda.client import (
    MAZDA_ORIGIN,
    MazdaCatalogModel,
    MazdaClientConfig,
    MazdaDealer,
    MazdaInventoryClient,
    MazdaVehicle,
)
from vehicle_inventory.makes.mazda.dealers import (
    MAZDA_DISCOVERY_MAX_DISTANCE,
    discover_nationwide_dealers,
    list_dealer_refresh_zips,
    mazda_discovery_seed_zips,
)
from vehicle_inventory.geo.dealer_geo import ensure_dealer_geo_cache_table, store_dealer_geo_coordinates
from vehicle_inventory.makes.mazda.colors import resolve_exterior_color_hex
from vehicle_inventory.makes.mazda.media import classify_mazda_media, normalize_mazda_media_href
from vehicle_inventory.makes.mazda.models import (
    build_mazda_catalog_code_index,
    compose_mazda_model_marketing_name,
    resolve_mazda_series_code,
)
from vehicle_inventory.makes.mazda.stage import resolve_mazda_allocation_stage
from vehicle_inventory.makes.mazda.session import resolve_mazda_cookies


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "unknown"


@dataclass
class MazdaIngestSettings:
    database_url: str
    schema_path: Path
    zip_code: str = "95101"
    distance: int = 50
    page_size: int = 100
    model_codes: Optional[List[str]] = None
    all_models: bool = False
    nationwide: bool = True
    page_delay: float = 0.35
    dealer_discovery_delay: float = 0.15
    fetch_vehicle_details: bool = True
    detail_delay: float = 0.15


@dataclass
class MazdaDealerRefreshSettings:
    database_url: str
    schema_path: Path
    distance: int = 1
    page_size: int = 100
    model_codes: Optional[List[str]] = None
    all_models: bool = False
    page_delay: float = 0.35
    zip_delay: float = 0.15
    fetch_vehicle_details: bool = True
    detail_delay: float = 0.15


def _absolute_image_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    url = re.sub(r"^(https://www\.mazdausa\.com):443", r"\1", url, flags=re.IGNORECASE)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"{MAZDA_ORIGIN}{url}"
    return url


def _catalog_image_rank(url: str) -> int:
    lower = str(url or "").lower()
    if "profile-jellies" in lower or "profile-jelly" in lower:
        return 0
    if "/profile/" in lower or "profile.png" in lower:
        return 1
    if "jellies" in lower or "jelly" in lower:
        return 2
    return 3


def _pick_best_catalog_image_url(urls: List[str]) -> str:
    candidates = [_absolute_image_url(url) for url in urls]
    candidates = [url for url in candidates if url]
    if not candidates:
        return ""
    candidates.sort(key=lambda url: (_catalog_image_rank(url), len(url)))
    return candidates[0]


def _vehicle_image_candidates(vehicle: MazdaVehicle) -> List[str]:
    candidates: List[str] = []
    if vehicle.image_url:
        candidates.append(vehicle.image_url)
    images = vehicle.raw.get("ImagesListInfo") if isinstance(vehicle.raw, dict) else None
    if isinstance(images, list):
        for row in images:
            if isinstance(row, dict) and row.get("Url"):
                candidates.append(str(row.get("Url")))
    return candidates


def _catalog_model_to_row(model: MazdaCatalogModel, *, nationwide: bool = False) -> dict:
    top_label = None
    if model.inventory_count is not None:
        scope = "nationwide" if nationwide else "in dealer radius"
        top_label = f"{model.inventory_count:,} {scope}"
    return {
        "model_code": model.model_code,
        "series": model.series,
        "title": model.title,
        "year": model.year or None,
        "image": model.image,
        "top_label": top_label,
    }


def _backfill_catalog_images(
    client: MazdaInventoryClient,
    dealer_ids: List[int],
    models: List[MazdaCatalogModel],
) -> None:
    """Mazda sometimes omits catalog ``Image`` even when inventory exists."""
    for model in models:
        if model.image:
            continue
        try:
            payload = client.search_inventory(
                dealer_ids,
                results_start=1,
                page_size=12,
                carlines=[model.model_code],
            )
            vehicles = client.parse_vehicles(payload)
        except Exception as exc:
            print(f"[mazda] catalog image backfill failed for {model.model_code}: {exc}", flush=True)
            continue
        image_urls: List[str] = []
        for vehicle in vehicles:
            image_urls.extend(_vehicle_image_candidates(vehicle))
        image_url = _pick_best_catalog_image_url(image_urls)
        if image_url:
            model.image = image_url


def _backfill_catalog_images_from_db(db: InventoryDb, models: List[MazdaCatalogModel]) -> None:
    for model in models:
        if model.image:
            continue
        rows = db.conn.execute(
            """
            SELECT m.href
            FROM vehicles v
            JOIN vehicle_media vm ON vm.vin = v.vin
            JOIN media m ON m.media_id = vm.media_id
            WHERE UPPER(v.series_code) = UPPER(?)
              AND v.is_active = 1
              AND m.href IS NOT NULL
              AND m.href != ''
            ORDER BY vm.media_id
            LIMIT 24
            """,
            (model.model_code,),
        ).fetchall()
        image_url = _pick_best_catalog_image_url([str(row["href"] or "") for row in rows])
        if image_url:
            model.image = image_url


def persist_mazda_dealers(db: InventoryDb, dealers: List[MazdaDealer], ts: str) -> None:
    ensure_dealer_geo_cache_table(db.conn)
    for dealer in dealers:
        db.upsert_dealer(
            {
                "dealerCd": str(dealer.dealer_id),
                "dealerMarketingName": dealer.name,
                "dealerWebsite": dealer.web_url or None,
            },
            ts,
        )
        if dealer.lat or dealer.lon:
            store_dealer_geo_coordinates(
                db.conn,
                str(dealer.dealer_id),
                latitude=dealer.lat,
                longitude=dealer.lon,
                postal_code=dealer.zip_code,
                city=dealer.city,
                state=dealer.state,
                query_text=f"{dealer.name}, {dealer.city}, {dealer.state} {dealer.zip_code}",
            )


def _resolve_mazda_dealers(
    client: MazdaInventoryClient,
    *,
    zip_code: str,
    distance: int,
    nationwide: bool = False,
    discovery_delay: float = 0.15,
    progress_callback: Optional[ProgressCallback] = None,
) -> tuple[List[MazdaDealer], List[int]]:
    """Resolve dealers for inventory search — nationwide seed grid or single ZIP radius."""
    if nationwide:
        seed_count = len(mazda_discovery_seed_zips())

        def emit_discovery(message: str) -> None:
            if progress_callback:
                emit_progress(
                    IngestProgress(status="running", phase="dealers"),
                    progress_callback,
                    message=message,
                )

        emit_discovery(
            f"Discovering Mazda dealers nationwide ({seed_count} seed ZIPs, "
            f"{MAZDA_DISCOVERY_MAX_DISTANCE} mi radius)..."
        )
        dealers = discover_nationwide_dealers(
            client,
            max_distance=MAZDA_DISCOVERY_MAX_DISTANCE,
            zip_delay=discovery_delay,
            progress_callback=lambda message: emit_discovery(message),
        )
    else:
        if not client.validate_zip(zip_code):
            raise RuntimeError(f"Invalid ZIP code for Mazda dealer lookup: {zip_code}")
        dealers = client.fetch_dealers(zip_code, max_distance=distance)

    if not dealers:
        scope = "nationwide seed ZIP grid" if nationwide else f"{distance} mi of {zip_code}"
        raise RuntimeError(f"No Mazda dealers found ({scope}).")
    dealer_ids = [dealer.dealer_id for dealer in dealers]
    return dealers, dealer_ids


def sync_nationwide_dealers(
    client: MazdaInventoryClient,
    db: InventoryDb,
    *,
    ts: str,
    discovery_delay: float = 0.15,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[MazdaDealer]:
    dealers, _dealer_ids = _resolve_mazda_dealers(
        client,
        zip_code="",
        distance=0,
        nationwide=True,
        discovery_delay=discovery_delay,
        progress_callback=progress_callback,
    )
    persist_mazda_dealers(db, dealers, ts)
    db.commit()
    return dealers


def sync_model_catalog(
    client: MazdaInventoryClient,
    db: InventoryDb,
    *,
    zip_code: str,
    distance: int,
    ts: str,
    nationwide: bool = True,
    discovery_delay: float = 0.15,
    progress_callback: Optional[ProgressCallback] = None,
) -> List[MazdaCatalogModel]:
    dealers, dealer_ids = _resolve_mazda_dealers(
        client,
        zip_code=zip_code,
        distance=distance,
        nationwide=nationwide,
        discovery_delay=discovery_delay,
        progress_callback=progress_callback,
    )
    persist_mazda_dealers(db, dealers, ts)
    models = client.fetch_model_catalog(dealer_ids)
    if not models:
        raise RuntimeError("Mazda inventory search returned no model catalog entries.")
    _backfill_catalog_images(client, dealer_ids, models)
    _backfill_catalog_images_from_db(db, models)
    db.upsert_model_catalog(
        [_catalog_model_to_row(model, nationwide=nationwide) for model in models],
        ts=ts,
    )
    db.commit()
    return models


def _catalog_models_from_rows(rows: List[dict]) -> List[MazdaCatalogModel]:
    models: List[MazdaCatalogModel] = []
    for row in rows:
        model_code = str(row.get("model_code") or "").strip()
        if not model_code:
            continue
        count = None
        top_label = str(row.get("top_label") or "")
        if top_label:
            digits = re.sub(r"[^0-9]", "", top_label.split(" in dealer radius", 1)[0])
            if digits:
                count = int(digits)
        models.append(
            MazdaCatalogModel(
                model_code=model_code,
                title=str(row.get("title") or model_code),
                series=str(row.get("series") or model_code),
                year=str(row.get("year") or ""),
                image=row.get("image"),
                inventory_count=count,
            )
        )
    return models


def resolve_target_carlines(
    settings: MazdaIngestSettings,
    client: MazdaInventoryClient,
    db: InventoryDb,
    ts: str,
) -> Optional[List[str]]:
    if settings.all_models:
        return None
    if settings.model_codes:
        catalog_rows = db.list_model_catalog()
        if not catalog_rows:
            raise RuntimeError(
                "Model catalog is empty. Use Admin → Sync Model Catalog before ingesting selected models."
            )
        models = _catalog_models_from_rows(catalog_rows)
        selected = {code.strip().upper() for code in settings.model_codes if str(code).strip()}
        matched = [model.model_code for model in models if model.model_code.upper() in selected]
        if not matched:
            requested = ", ".join(settings.model_codes)
            raise RuntimeError(
                f"No catalog entries matched the selected model(s): {requested}. "
                "Sync the model catalog, then try again."
            )
        return matched
    raise RuntimeError("Select at least one model or choose all models.")


def resolve_ingest_carlines(settings: MazdaIngestSettings, db: InventoryDb) -> List[str]:
    """Return the catalog carline codes to ingest one model at a time."""
    if settings.all_models:
        catalog_rows = db.list_model_catalog()
        if not catalog_rows:
            raise RuntimeError(
                "Model catalog is empty. Use Admin → Sync Model Catalog before ingesting all models."
            )
        return [
            str(row["model_code"]).strip()
            for row in catalog_rows
            if str(row.get("model_code") or "").strip()
        ]
    carlines = resolve_target_carlines(settings, client=None, db=db, ts="")
    if not carlines:
        raise RuntimeError("Select at least one model or choose all models.")
    return carlines


def _inventory_count_from_catalog_row(row: dict) -> Optional[int]:
    top_label = str(row.get("top_label") or "")
    if top_label:
        digits = re.sub(r"[^0-9]", "", top_label.split(" in dealer radius", 1)[0])
        if digits:
            return int(digits)
    count = row.get("inventory_count")
    if count is not None:
        try:
            return int(count)
        except (TypeError, ValueError):
            return None
    return None


def _estimate_carline_total(api_total: int, catalog_count: Optional[int]) -> int:
    """Use ``TotalVehicles`` from the carline-filtered search; catalog is fallback only."""
    if api_total > 0:
        return api_total
    if catalog_count and catalog_count > 0:
        return catalog_count
    return 0


def _estimated_total_pages(total_vehicles: int, page_size: int) -> int:
    return max(1, math.ceil(max(total_vehicles, 1) / max(page_size, 1)))


def _pagination_should_stop(
    *,
    vehicles_on_page: int,
    new_on_page: int,
    model_saved: int,
    estimated_total: int,
    page_no: int,
    total_pages: int,
    page_size: int,
) -> bool:
    if vehicles_on_page == 0:
        return True
    if new_on_page == 0:
        return True
    if vehicles_on_page < page_size:
        return True
    if estimated_total > 0 and model_saved >= estimated_total:
        return True
    if page_no >= total_pages:
        return True
    if page_no >= 500:
        return True
    return False


def _vehicle_payload(vehicle: MazdaVehicle) -> dict:
    ext_color = {"marketingName": vehicle.exterior_color}
    ext_hex = resolve_exterior_color_hex(vehicle.exterior_color)
    if ext_hex:
        ext_color["colorHexCd"] = ext_hex
    model_name = compose_mazda_model_marketing_name(
        marketing_series=vehicle.carline,
        model_marketing_name=vehicle.model_name,
        grade=vehicle.model_name,
    )
    stage_code, _stage_label = resolve_mazda_allocation_stage(vehicle_location=vehicle.vehicle_location)
    payload = {
        "vin": vehicle.vin,
        "brand": "Mazda",
        "marketingSeries": vehicle.carline,
        "year": vehicle.year,
        "grade": vehicle.model_name,
        "dealerTrim": vehicle.model_name,
        "model": {
            "modelCd": vehicle.carline,
            "marketingName": model_name,
            "marketingTitle": model_name,
        },
        "extColor": ext_color,
        "intColor": {"marketingName": vehicle.interior_color},
        "dealerCd": str(vehicle.dealer_id) if vehicle.dealer_id is not None else None,
        "vdpUrl": (
            f"{MAZDA_ORIGIN}{vehicle.details_url}"
            if vehicle.details_url.startswith("/")
            else vehicle.details_url
        ),
        "price": {
            "advertizedPrice": vehicle.price,
            "totalMsrp": vehicle.base_msrp,
            "baseMsrp": vehicle.base_msrp,
            "sellingPrice": vehicle.price,
        },
    }
    if stage_code:
        payload["dealerCategory"] = stage_code
        payload["vehicleLocation"] = stage_code
    if vehicle.eta_date:
        payload["etaDate"] = vehicle.eta_date
    return payload


def _resolve_dealer_payload(
    client: MazdaInventoryClient,
    cache: Dict[int, dict],
    dealer_id: int,
) -> dict:
    if dealer_id in cache:
        return cache[dealer_id]
    try:
        payload = client.fetch_dealer_by_id(dealer_id)
    except Exception as exc:
        print(f"[mazda] dealer lookup failed for {dealer_id}: {exc}", flush=True)
        payload = {"dealerCd": str(dealer_id)}
    cache[dealer_id] = payload
    return payload


def _persist_vehicle(
    db: InventoryDb,
    *,
    run_id: int,
    vehicle: MazdaVehicle,
    dealer_distance: dict[int, float],
    dealer_cache: Dict[int, dict],
    client: MazdaInventoryClient,
    settings: MazdaIngestSettings,
    catalog_index: Dict[str, str],
    ts: str,
) -> None:
    series_code = resolve_mazda_series_code(
        carline=vehicle.carline,
        model_name=vehicle.model_name,
        raw=vehicle.raw,
        catalog_index=catalog_index,
    )
    payload = _vehicle_payload(vehicle)
    if vehicle.dealer_id is not None:
        dealer_payload = _resolve_dealer_payload(client, dealer_cache, int(vehicle.dealer_id))
        db.upsert_dealer(dealer_payload, ts)
        if dealer_payload.get("dealerMarketingName"):
            payload["dealerMarketingName"] = dealer_payload["dealerMarketingName"]
        if dealer_payload.get("dealerWebsite"):
            payload["dealerWebsite"] = dealer_payload["dealerWebsite"]

    if settings.fetch_vehicle_details:
        try:
            detail = client.fetch_vehicle_detail(
                vehicle.vin,
                referer=MazdaInventoryClient.detail_referer(vehicle),
            )
            payload = MazdaInventoryClient.enrich_vehicle_payload(payload, detail)
        except Exception as exc:
            print(f"[mazda] detail fetch failed for {vehicle.vin}: {exc}", flush=True)
        if settings.detail_delay > 0:
            time.sleep(settings.detail_delay)

    payload["distance"] = dealer_distance.get(int(vehicle.dealer_id or 0))
    db.process_vehicle(run_id=run_id, series_code=series_code, vehicle=payload, ts=ts)

    image_url = _absolute_image_url(vehicle.image_url)
    if not image_url and payload.get("media"):
        first_media = payload["media"][0] if isinstance(payload["media"], list) else {}
        if isinstance(first_media, dict):
            image_url = _absolute_image_url(str(first_media.get("href") or ""))
    if image_url and not payload.get("media"):
        media_payload = classify_mazda_media(
            normalize_mazda_media_href(image_url),
            image_tag="Exterior",
            media_type="carjellyimage",
        )
        media_id = db.upsert_media(media_payload, ts)
        if media_id:
            db.link_vehicle_media(vehicle.vin, media_id, ts)
    if image_url:
        db.patch_model_catalog_image_if_missing(series_code, image_url, ts)


def run_mazda_ingest(
    settings: MazdaIngestSettings,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> IngestProgress:
    progress = IngestProgress(status="running", phase="bootstrap", percent=1.0)
    emit_progress(progress, progress_callback, message="Starting Mazda ingest...")

    db = InventoryDb(database_url=settings.database_url, schema_path=settings.schema_path)
    db.initialize()
    ts = utc_now()

    try:
        emit_progress(progress, progress_callback, phase="session", message="Refreshing Mazda session cookies...")
        client = MazdaInventoryClient(
            MazdaClientConfig(
                cookies=resolve_mazda_cookies(),
                page_size=settings.page_size,
            )
        )

        emit_progress(
            progress,
            progress_callback,
            phase="dealers",
            message=(
                "Discovering Mazda dealers nationwide..."
                if settings.nationwide
                else f"Looking up Mazda dealers near ZIP {settings.zip_code}..."
            ),
        )
        dealers, dealer_ids = _resolve_mazda_dealers(
            client,
            zip_code=settings.zip_code,
            distance=settings.distance,
            nationwide=settings.nationwide,
            discovery_delay=settings.dealer_discovery_delay,
            progress_callback=progress_callback,
        )
        dealer_distance = {dealer.dealer_id: dealer.distance_mi for dealer in dealers}
        dealer_cache: Dict[int, dict] = {}
        persist_mazda_dealers(db, dealers, ts)
        for dealer in dealers:
            dealer_payload = {
                "dealerCd": str(dealer.dealer_id),
                "dealerMarketingName": dealer.name,
                "dealerWebsite": dealer.web_url or None,
            }
            dealer_cache[dealer.dealer_id] = dealer_payload

        catalog_rows = db.list_model_catalog()
        catalog_by_code = {
            str(row.get("model_code") or "").strip(): row
            for row in catalog_rows
            if str(row.get("model_code") or "").strip()
        }
        carlines_to_fetch = resolve_ingest_carlines(settings, db)
        catalog_index = build_mazda_catalog_code_index(catalog_rows)

        run_id = db.create_run(
            queried_at=ts,
            zip_code=settings.zip_code,
            distance=settings.distance,
            page_size=settings.page_size,
            series_codes=carlines_to_fetch,
            lead_id=None,
            archive_dir=None,
            source="mazda_rest",
        )

        progress.total_models = len(carlines_to_fetch)
        emit_progress(
            progress,
            progress_callback,
            phase="ingesting",
            message=(
                f"Resolved {len(dealer_ids)} dealer(s) "
                f"({'nationwide' if settings.nationwide else 'dealer.ajax'}); "
                f"fetching inventory for {len(carlines_to_fetch)} model(s)..."
            ),
        )

        seen_vins: set[str] = set()
        vehicles_persisted = 0
        for model_index, carline in enumerate(carlines_to_fetch, start=1):
            catalog_row = catalog_by_code.get(carline, {})
            model_title = str(catalog_row.get("title") or carline)
            catalog_count = _inventory_count_from_catalog_row(catalog_row)

            progress.current_model = carline
            progress.current_model_title = model_title
            progress.model_index = model_index
            emit_progress(
                progress,
                progress_callback,
                message=f"Ingesting {model_title} ({carline})...",
                percent=max(2.0, ((model_index - 1) / max(progress.total_models, 1)) * 100.0),
            )

            first = client.search_inventory(
                dealer_ids,
                results_start=1,
                page_size=settings.page_size,
                carlines=[carline],
            )
            api_total = client.total_vehicle_count(first)
            estimated_total = _estimate_carline_total(api_total, catalog_count)
            total_pages = _estimated_total_pages(estimated_total, settings.page_size)
            progress.total_pages = total_pages

            page_no = 0
            model_saved = 0
            while True:
                page_no += 1
                if page_no > 1 and settings.page_delay > 0:
                    time.sleep(settings.page_delay)
                payload = first if page_no == 1 else client.search_inventory(
                    dealer_ids,
                    results_start=client.results_start_for_page(page_no),
                    page_size=settings.page_size,
                    carlines=[carline],
                )
                vehicles = client.parse_vehicles(payload)
                if not vehicles:
                    break

                new_on_page = 0
                for vehicle in vehicles:
                    if vehicle.vin in seen_vins:
                        continue
                    seen_vins.add(vehicle.vin)
                    new_on_page += 1
                    _persist_vehicle(
                        db,
                        run_id=run_id,
                        vehicle=vehicle,
                        dealer_distance=dealer_distance,
                        dealer_cache=dealer_cache,
                        client=client,
                        settings=settings,
                        catalog_index=catalog_index,
                        ts=ts,
                    )
                    vehicles_persisted += 1
                    model_saved += 1

                progress.current_page = page_no
                progress.vehicles_fetched = len(seen_vins)
                progress.vehicles_persisted = vehicles_persisted
                model_fraction = min(page_no / max(total_pages, 1), 1.0)
                overall = ((model_index - 1) + model_fraction) / max(progress.total_models, 1)
                progress.percent = max(2.0, min(99.0, overall * 100.0))
                emit_progress(
                    progress,
                    progress_callback,
                    message=(
                        f"{model_title}: page {page_no}/{total_pages} "
                        f"({model_saved:,}/{estimated_total:,} this model, "
                        f"{vehicles_persisted:,} total saved)"
                    ),
                )

                if _pagination_should_stop(
                    vehicles_on_page=len(vehicles),
                    new_on_page=new_on_page,
                    model_saved=model_saved,
                    estimated_total=estimated_total,
                    page_no=page_no,
                    total_pages=total_pages,
                    page_size=settings.page_size,
                ):
                    if page_no >= 500:
                        print(
                            f"[mazda] stopping pagination for {carline} after {page_no} pages (safety cap)",
                            flush=True,
                        )
                    break

            progress.completed_models.append(carline)

        db.conn.commit()
        refresh_series_latest_runs(db.conn, force=True)
        db.conn.commit()

        from vehicle_inventory.jobs.service import get_job_service

        jobs = get_job_service(make_slug="mazda")
        if not jobs.geocode_is_running():
            try:
                jobs.start_geocode(limit=None, delay_sec=1.1, trigger_source="auto")
                geocode_message = "Dealer geocoding started in background..."
            except RuntimeError:
                geocode_message = "Dealer geocoding already running in background."
        else:
            geocode_message = "Dealer geocoding already running in background."
        emit_progress(progress, progress_callback, message=geocode_message)
    finally:
        db.close()

    emit_progress(
        progress,
        progress_callback,
        status="completed",
        phase="done",
        percent=100.0,
        message=f"Mazda ingest complete ({progress.vehicles_persisted:,} vehicles).",
    )
    return progress


def run_mazda_dealer_vehicle_refresh(
    settings: MazdaDealerRefreshSettings,
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> IngestProgress:
    """Refresh inventory by querying each synced dealer ZIP at a tight radius."""
    progress = IngestProgress(status="running", phase="bootstrap", percent=1.0)
    emit_progress(
        progress,
        progress_callback,
        message="Starting Mazda dealer ZIP vehicle refresh...",
    )

    db = InventoryDb(database_url=settings.database_url, schema_path=settings.schema_path)
    db.initialize()
    ts = utc_now()
    vehicles_persisted = 0
    zips_processed = 0
    zips_with_inventory = 0

    try:
        dealer_zips = list_dealer_refresh_zips(db.conn)
        if not dealer_zips:
            raise RuntimeError(
                "No dealer ZIP codes found. Run Admin → Sync Dealers (Nationwide) first."
            )

        emit_progress(
            progress,
            progress_callback,
            phase="session",
            message="Refreshing Mazda session cookies...",
        )
        client = MazdaInventoryClient(
            MazdaClientConfig(
                cookies=resolve_mazda_cookies(),
                page_size=settings.page_size,
            )
        )

        catalog_rows = db.list_model_catalog()
        catalog_by_code = {
            str(row.get("model_code") or "").strip(): row
            for row in catalog_rows
            if str(row.get("model_code") or "").strip()
        }
        carlines_to_fetch = resolve_ingest_carlines(settings, db)
        catalog_index = build_mazda_catalog_code_index(catalog_rows)

        run_id = db.create_run(
            queried_at=ts,
            zip_code="dealer-refresh",
            distance=settings.distance,
            page_size=settings.page_size,
            series_codes=carlines_to_fetch,
            lead_id=None,
            archive_dir=None,
            source="mazda_dealer_zip_refresh",
        )

        total_zips = len(dealer_zips)
        total_carlines = len(carlines_to_fetch)
        total_steps = max(1, total_zips * total_carlines)
        progress.total_models = total_zips
        emit_progress(
            progress,
            progress_callback,
            phase="ingesting",
            message=(
                f"Refreshing {total_carlines} model(s) across {total_zips} dealer ZIP(s) "
                f"at {settings.distance} mi..."
            ),
        )

        seen_vins: set[str] = set()
        zips_processed = 0
        zips_with_inventory = 0

        for zip_index, zip_code in enumerate(dealer_zips, start=1):
            if zip_index > 1 and settings.zip_delay > 0:
                time.sleep(settings.zip_delay)

            progress.current_model = zip_code
            progress.model_index = zip_index
            emit_progress(
                progress,
                progress_callback,
                message=f"ZIP {zip_code} ({zip_index}/{total_zips}): looking up dealers...",
                percent=max(2.0, ((zip_index - 1) / total_zips) * 100.0),
            )

            try:
                dealers = client.fetch_dealers(zip_code, max_distance=settings.distance)
            except Exception as exc:
                print(f"[mazda] dealer refresh skipped {zip_code}: {exc}", flush=True)
                continue

            if not dealers:
                continue

            zips_processed += 1
            persist_mazda_dealers(db, dealers, ts)
            dealer_ids = [dealer.dealer_id for dealer in dealers]
            dealer_distance = {dealer.dealer_id: dealer.distance_mi for dealer in dealers}
            dealer_cache: Dict[int, dict] = {
                dealer.dealer_id: {
                    "dealerCd": str(dealer.dealer_id),
                    "dealerMarketingName": dealer.name,
                    "dealerWebsite": dealer.web_url or None,
                }
                for dealer in dealers
            }

            zip_saved_before = vehicles_persisted
            for carline_index, carline in enumerate(carlines_to_fetch, start=1):
                catalog_row = catalog_by_code.get(carline, {})
                model_title = str(catalog_row.get("title") or carline)
                catalog_count = _inventory_count_from_catalog_row(catalog_row)
                progress.current_model_title = model_title

                step_base = (zip_index - 1) * total_carlines + (carline_index - 1)
                emit_progress(
                    progress,
                    progress_callback,
                    message=f"ZIP {zip_code}: {model_title} ({carline_index}/{total_carlines})...",
                    percent=max(2.0, min(99.0, (step_base / total_steps) * 100.0)),
                )

                first = client.search_inventory(
                    dealer_ids,
                    results_start=1,
                    page_size=settings.page_size,
                    carlines=[carline],
                )
                api_total = client.total_vehicle_count(first)
                estimated_total = _estimate_carline_total(api_total, catalog_count)
                total_pages = _estimated_total_pages(estimated_total, settings.page_size)
                progress.total_pages = total_pages

                page_no = 0
                model_saved = 0
                while True:
                    page_no += 1
                    if page_no > 1 and settings.page_delay > 0:
                        time.sleep(settings.page_delay)
                    payload = first if page_no == 1 else client.search_inventory(
                        dealer_ids,
                        results_start=client.results_start_for_page(page_no),
                        page_size=settings.page_size,
                        carlines=[carline],
                    )
                    vehicles = client.parse_vehicles(payload)
                    if not vehicles:
                        break

                    new_on_page = 0
                    for vehicle in vehicles:
                        if vehicle.vin in seen_vins:
                            continue
                        seen_vins.add(vehicle.vin)
                        new_on_page += 1
                        _persist_vehicle(
                            db,
                            run_id=run_id,
                            vehicle=vehicle,
                            dealer_distance=dealer_distance,
                            dealer_cache=dealer_cache,
                            client=client,
                            settings=settings,
                            catalog_index=catalog_index,
                            ts=ts,
                        )
                        vehicles_persisted += 1
                        model_saved += 1

                    progress.current_page = page_no
                    progress.vehicles_fetched = len(seen_vins)
                    progress.vehicles_persisted = vehicles_persisted
                    step_fraction = (step_base + min(page_no / max(total_pages, 1), 1.0)) / total_steps
                    progress.percent = max(2.0, min(99.0, step_fraction * 100.0))
                    emit_progress(
                        progress,
                        progress_callback,
                        message=(
                            f"ZIP {zip_code} · {model_title}: page {page_no}/{total_pages} "
                            f"({model_saved:,}/{estimated_total:,} this model, "
                            f"{vehicles_persisted:,} total saved)"
                        ),
                    )

                    if _pagination_should_stop(
                        vehicles_on_page=len(vehicles),
                        new_on_page=new_on_page,
                        model_saved=model_saved,
                        estimated_total=estimated_total,
                        page_no=page_no,
                        total_pages=total_pages,
                        page_size=settings.page_size,
                    ):
                        if page_no >= 500:
                            print(
                                f"[mazda] stopping pagination for {carline} near {zip_code} "
                                f"after {page_no} pages (safety cap)",
                                flush=True,
                            )
                        break

                if model_saved > 0 and carline not in progress.completed_models:
                    progress.completed_models.append(carline)

            if vehicles_persisted > zip_saved_before:
                zips_with_inventory += 1

        db.conn.commit()
        refresh_series_latest_runs(db.conn, force=True)
        db.conn.commit()

        from vehicle_inventory.jobs.service import get_job_service

        jobs = get_job_service(make_slug="mazda")
        if not jobs.geocode_is_running():
            try:
                jobs.start_geocode(limit=None, delay_sec=1.1, trigger_source="auto")
                geocode_message = "Dealer geocoding started in background..."
            except RuntimeError:
                geocode_message = "Dealer geocoding already running in background."
        else:
            geocode_message = "Dealer geocoding already running in background."
        emit_progress(progress, progress_callback, message=geocode_message)
    finally:
        db.close()

    emit_progress(
        progress,
        progress_callback,
        status="completed",
        phase="done",
        percent=100.0,
        message=(
            f"Dealer ZIP refresh complete ({vehicles_persisted:,} vehicles from "
            f"{zips_with_inventory}/{zips_processed} ZIP(s))."
        ),
    )
    return progress
