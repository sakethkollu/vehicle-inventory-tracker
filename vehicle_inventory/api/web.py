from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, session

from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.db.run_scope import refresh_series_latest_runs

from vehicle_inventory.makes.context import resolve_make_slug, set_session_make
from vehicle_inventory.makes.registry import get_make_adapter, get_make_profile, list_makes
from vehicle_inventory.core.config import Settings, get_settings
from vehicle_inventory.ingest.router import sync_make_catalog
from vehicle_inventory.jobs.service import get_job_service
from vehicle_inventory.jobs.worker_status import get_worker_fleet_status
from vehicle_inventory.api.inventory import (
    attach_options,
    attach_wheels,
    build_analytics_payload,
    build_inventory_csv,
    count_inventory_rows,
    fetch_inventory_rows,
    fetch_inventory_geo_map,
    parse_inventory_filters,
    rows_to_items,
)
from vehicle_inventory.geo.dealer_geo import (
    clear_dealer_geo_cache,
    dealer_geo_stats,
    geocode_all_dealers,
    reverse_geocode_postal_code,
)
from vehicle_inventory.jobs.runs import JobRunStore
from vehicle_inventory.api.admin_auth import (
    admin_enabled,
    configure_admin,
    is_admin_authenticated,
    require_admin_api,
    require_admin_page,
)
from vehicle_inventory.api.filters import build_filters_payload, parse_filter_context
from vehicle_inventory.api.image_proxy import fetch_proxied_image, is_allowed_image_url
from vehicle_inventory.api.pricing import build_msrp_comparison_for_filters


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def create_app(settings: Optional[Settings] = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(_PROJECT_ROOT / "templates"),
        static_folder=str(_PROJECT_ROOT / "static"),
    )
    runtime_settings = settings or get_settings()
    app.config["SETTINGS"] = runtime_settings
    configure_admin(app)

    def current_make():
        return get_make_profile(resolve_make_slug())

    def request_jobs():
        return get_job_service(runtime_settings, make_slug=resolve_make_slug())

    def job_store():
        return JobRunStore(current_make().database_url)

    def ensure_runtime_columns() -> None:
        from vehicle_inventory.db import InventoryDb

        for make in list_makes():
            db = InventoryDb(
                database_url=make.database_url,
                schema_path=runtime_settings.schema_path,
            )
            try:
                db.initialize()
                refresh_series_latest_runs(db.conn, force=True)
            finally:
                db.close()

    ensure_runtime_columns()

    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    def get_conn(*, readonly: bool = False):
        return open_db_connection(current_make().database_url, readonly=readonly)

    def utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_api_payload(make):
        adapter = get_make_adapter(make.slug)
        return {
            "slug": make.slug,
            "display_name": make.display_name,
            "ingest_adapter": make.ingest_adapter,
            "inventory_origin": make.inventory_origin,
            "supports_catalog_sync": adapter.supports_catalog_sync(),
            "requires_model_selection": adapter.requires_model_selection(),
        }

    @app.get("/api/makes")
    def api_makes():
        current = current_make()
        return jsonify(
            {
                "current": _make_api_payload(current),
                "makes": [_make_api_payload(make) for make in list_makes()],
            }
        )

    @app.post("/api/session/make")
    def api_session_make():
        payload = request.get_json(silent=True) or {}
        slug = str(payload.get("make") or "").strip().lower()
        if not slug:
            return jsonify({"error": "make is required"}), 400
        try:
            set_session_make(slug)
        except KeyError:
            return jsonify({"error": f"Unknown make: {slug}"}), 400
        make = current_make()
        return jsonify({"ok": True, "make": make.slug, "display_name": make.display_name})

    def validate_ingest_selection(payload: dict) -> tuple[bool, list[str], bool]:
        make = current_make()
        adapter = get_make_adapter(make.slug)
        all_models = bool(payload.get("all_models"))
        model_codes = payload.get("model_codes") or []
        if not isinstance(model_codes, list):
            raise ValueError("model_codes must be an array")
        model_codes = [str(code).strip() for code in model_codes if str(code).strip()]
        if not adapter.requires_model_selection():
            all_models = all_models or not model_codes
        elif not all_models and not model_codes:
            raise ValueError("Select at least one model or choose all models.")
        return all_models, model_codes, True

    @app.get("/")
    def index():
        make = current_make()
        return render_template(
            "index.html",
            app_title="Vehicle Inventory Tracker",
            make_slug=make.slug,
            make_name=make.display_name,
        )

    @app.get("/admin")
    @require_admin_page
    def admin_dashboard(*, admin_enabled: bool = True, authenticated: bool = False):
        make = current_make()
        return render_template(
            "admin.html",
            admin_enabled=admin_enabled,
            authenticated=authenticated,
            login_error=None,
            app_title="Vehicle Inventory Tracker",
            make_slug=make.slug,
            make_name=make.display_name,
        )

    @app.get("/admin/login")
    def admin_login():
        if not admin_enabled(app):
            return render_template(
                "admin.html",
                admin_enabled=False,
                authenticated=False,
                login_error=None,
            ), 503
        if is_admin_authenticated():
            return redirect("/admin")
        return render_template(
            "admin.html",
            admin_enabled=True,
            authenticated=False,
            login_error=None,
        )

    @app.post("/admin/login")
    def admin_login_submit():
        if not admin_enabled(app):
            return render_template(
                "admin.html",
                admin_enabled=False,
                authenticated=False,
                login_error=None,
            ), 503
        password = (request.form.get("password") or "").strip()
        if password and password == app.config["ADMIN_PASSWORD"]:
            session["admin_authenticated"] = True
            return redirect("/admin")
        return render_template(
            "admin.html",
            admin_enabled=True,
            authenticated=False,
            login_error="Invalid password.",
        ), 401

    @app.post("/admin/logout")
    def admin_logout():
        session.pop("admin_authenticated", None)
        return redirect("/admin/login")

    @app.get("/api/admin/overview")
    @require_admin_api
    def admin_overview():
        conn = get_conn(readonly=True)
        try:
            geocode_payload = dict(dealer_geo_stats(conn))
        finally:
            conn.close()
        job = request_jobs().geocode_status()
        db_remaining = int(geocode_payload.get("remaining", 0))
        store = JobRunStore(current_make().database_url)
        request_jobs().reconcile_stale_runs(store)
        ingest_live = request_jobs().resolved_ingest_status(store)
        job = request_jobs().resolved_geocode_status(store)
        if job.get("status") in {"idle", "completed", "failed", "cancelled"}:
            job["remaining"] = db_remaining
        if job.get("status") == "idle" and db_remaining > 0:
            job["message"] = f"{db_remaining} dealer(s) need geocoding. Job not running."
        geocode_payload["job"] = job
        jobs_active = request_jobs().jobs_are_active(ingest_live, job)
        runtime_settings = get_settings()
        workers = get_worker_fleet_status(
            redis_url=runtime_settings.redis_url,
            use_redis_jobs=runtime_settings.use_redis_jobs,
        )
        return jsonify(
            {
                "ingest": ingest_live,
                "geocode": geocode_payload,
                "jobs_active": jobs_active,
                "workers": workers,
                "make": {
                    "slug": current_make().slug,
                    "display_name": current_make().display_name,
                },
                "recent_runs": store.list_runs(limit=50, since_days=30),
                "summary": store.summary(since_days=30),
            }
        )

    @app.post("/api/admin/geocode/start")
    @require_admin_api
    def admin_geocode_start():
        try:
            request_jobs().start_geocode(limit=None, delay_sec=1.1, trigger_source="admin")
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "job": request_jobs().geocode_status()})

    @app.post("/api/admin/geocode/cancel")
    @require_admin_api
    def admin_geocode_cancel():
        cancelled = request_jobs().cancel_geocode()
        if not cancelled:
            return jsonify({"ok": False, "error": "No geocoding job is running."}), 409
        return jsonify({"ok": True, "job": request_jobs().geocode_status()})

    @app.post("/api/admin/workers/repair")
    @require_admin_api
    def admin_workers_repair():
        runtime_settings = get_settings()
        if not runtime_settings.use_redis_jobs:
            return jsonify({"ok": False, "error": "Redis job queue is disabled."}), 409
        from vehicle_inventory.jobs.rq_maintenance import repair_rq_fleet

        result = repair_rq_fleet(runtime_settings.redis_url)
        workers = get_worker_fleet_status(
            redis_url=runtime_settings.redis_url,
            use_redis_jobs=runtime_settings.use_redis_jobs,
        )
        return jsonify({"ok": True, "repair": result, "workers": workers})

    @app.get("/favicon.ico")
    def favicon():
        static_dir = Path(app.static_folder or ".")
        svg_path = static_dir / "favicon.svg"
        if svg_path.is_file():
            return send_from_directory(static_dir, "favicon.svg", mimetype="image/svg+xml")
        return send_from_directory(static_dir, "favicon.ico", mimetype="image/png")

    @app.get("/api/geocode/reverse")
    def geocode_reverse():
        try:
            lat = float(request.args.get("lat", ""))
            lng = float(request.args.get("lng", ""))
        except (TypeError, ValueError):
            return jsonify({"error": "lat and lng are required"}), 400
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            return jsonify({"error": "invalid coordinates"}), 400
        postal_code = reverse_geocode_postal_code(lat, lng)
        return jsonify({"postal_code": postal_code, "lat": lat, "lng": lng})

    @app.get("/api/filters")
    def filters():
        ctx = parse_filter_context(request.args)
        conn = get_conn()
        try:
            return jsonify(build_filters_payload(conn, ctx))
        finally:
            conn.close()

    def inventory_response(filters, paginate: bool = True) -> Dict:
        conn = get_conn()
        try:
            max_run_row = conn.execute("SELECT MAX(run_id) AS max_run_id FROM runs").fetchone()
            latest_run_id = max_run_row["max_run_id"] if max_run_row else None
            if latest_run_id is None:
                return {
                    "latest_run_id": None,
                    "total_count": 0,
                    "count": 0,
                    "page": filters.page,
                    "page_size": filters.page_size,
                    "page_count": 0,
                    "items": [],
                }

            total_count = count_inventory_rows(conn, filters)
            if paginate:
                offset = (filters.page - 1) * filters.page_size
                rows = fetch_inventory_rows(
                    conn,
                    filters,
                    limit=filters.page_size,
                    offset=offset,
                )
            else:
                rows = fetch_inventory_rows(conn, filters)
            page_items = rows_to_items(rows)
            attach_options(conn, page_items)
            attach_wheels(conn, page_items)

            page_count = max(1, (total_count + filters.page_size - 1) // filters.page_size) if total_count else 0
            return {
                "latest_run_id": latest_run_id,
                "total_count": total_count,
                "count": len(page_items),
                "page": filters.page,
                "page_size": filters.page_size,
                "page_count": page_count,
                "items": page_items,
            }
        finally:
            conn.close()

    @app.get("/api/inventory")
    def inventory():
        filters = parse_inventory_filters(request.args)
        return jsonify(inventory_response(filters, paginate=True))

    @app.get("/api/inventory/export")
    def inventory_export():
        filters = parse_inventory_filters(request.args)
        payload = inventory_response(filters, paginate=False)
        csv_text = build_inventory_csv(payload.get("items") or [])
        run_id = payload.get("latest_run_id") or "export"
        series = "-".join(filters.series_codes) if filters.series_codes else "all"
        if len(series) > 48:
            series = f"{len(filters.series_codes)}_series"
        make = current_make()
        filename = f"inventory_{make.slug}_{series}_run{run_id}.csv"
        return Response(
            csv_text,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/inventory/analytics")
    def inventory_analytics():
        filters = parse_inventory_filters(request.args)
        conn = get_conn(readonly=True)
        try:
            max_run_row = conn.execute("SELECT MAX(run_id) AS max_run_id FROM runs").fetchone()
            latest_run_id = max_run_row["max_run_id"] if max_run_row else None
            if latest_run_id is None:
                return jsonify(
                    {
                        "latest_run_id": None,
                        "total_count": 0,
                        "advertized_price": None,
                        "total_msrp": None,
                        "histogram": None,
                        "insights": None,
                    }
                )

            analytics = build_analytics_payload(conn, filters)
            analytics["latest_run_id"] = latest_run_id
            return jsonify(analytics)
        finally:
            conn.close()

    @app.get("/api/inventory/msrp-comparison")
    def inventory_msrp_comparison():
        filters = parse_inventory_filters(request.args)
        conn = get_conn(readonly=True)
        try:
            comparison = build_msrp_comparison_for_filters(conn, filters)
            return jsonify(comparison or {})
        finally:
            conn.close()

    @app.get("/api/inventory/geo-map")
    def inventory_geo_map():
        filters = parse_inventory_filters(request.args)
        conn = get_conn(readonly=True)
        try:
            return jsonify(fetch_inventory_geo_map(conn, filters))
        finally:
            conn.close()

    @app.post("/api/catalog/sync")
    def catalog_sync():
        make = current_make()
        adapter = get_make_adapter(make.slug)
        if not adapter.supports_catalog_sync():
            return jsonify(
                {
                    "ok": False,
                    "error": f"Catalog sync is not supported for {make.display_name}. Run ingest to populate models.",
                }
            ), 400
        payload = request.get_json(silent=True) or {}
        zip_code = str(payload.get("zip_code") or "95132")
        distance_raw = payload.get("distance")
        distance = int(distance_raw) if distance_raw not in (None, "") else None
        nationwide_raw = payload.get("nationwide")
        nationwide = True if nationwide_raw is None else bool(nationwide_raw)
        store = JobRunStore(current_make().database_url)
        job_run_id = store.start(
            "catalog_sync",
            {"zip_code": zip_code, "distance": distance, "make": make.slug, "nationwide": nationwide},
            trigger_source="ui",
            message="Syncing model catalog...",
        )
        try:
            result = sync_make_catalog(
                make.slug,
                database_url=make.database_url,
                schema_path=runtime_settings.schema_path,
                zip_code=zip_code,
                distance=distance,
                nationwide=nationwide if make.slug == "mazda" else None,
            )
            store.finish(
                job_run_id,
                "completed",
                result={"count": result.get("count", 0)},
                message=f"Synced {result.get('count', 0)} model(s).",
            )
            return jsonify(
                {
                    "ok": True,
                    "job_run_id": job_run_id,
                    "count": result.get("count", 0),
                    "models": result.get("models", []),
                }
            )
        except Exception as exc:
            store.finish(job_run_id, "failed", error=str(exc), message=f"Catalog sync failed: {exc}")
            return jsonify({"ok": False, "error": str(exc), "job_run_id": job_run_id}), 500

    @app.post("/api/dealers/sync")
    def dealers_sync():
        make = current_make()
        if make.slug != "mazda":
            return jsonify({"ok": False, "error": "Nationwide dealer sync is only supported for Mazda."}), 400
        adapter = get_make_adapter(make.slug)
        sync_dealers = getattr(adapter, "sync_dealers", None)
        if not callable(sync_dealers):
            return jsonify({"ok": False, "error": "Dealer sync is not supported for this make."}), 400
        store = JobRunStore(make.database_url)
        job_run_id = store.start(
            "dealer_sync",
            {"make": make.slug},
            trigger_source="ui",
            message="Syncing Mazda dealers nationwide...",
        )
        try:
            result = sync_dealers(
                database_url=make.database_url,
                schema_path=runtime_settings.schema_path,
            )
            store.finish(
                job_run_id,
                "completed",
                result={"count": result.get("count", 0), "seed_zips": result.get("seed_zips", 0)},
                message=f"Synced {result.get('count', 0)} dealer(s).",
            )
            conn = get_conn()
            try:
                remaining = int(dealer_geo_stats(conn).get("remaining", 0))
            finally:
                conn.close()
            if remaining > 0 and not request_jobs().geocode_is_running():
                try:
                    request_jobs().start_geocode(
                        limit=None,
                        delay_sec=1.1,
                        trigger_source="auto",
                    )
                except RuntimeError:
                    pass
            return jsonify({"ok": True, "job_run_id": job_run_id, **result})
        except Exception as exc:
            store.finish(job_run_id, "failed", error=str(exc), message=f"Dealer sync failed: {exc}")
            return jsonify({"ok": False, "error": str(exc), "job_run_id": job_run_id}), 500

    @app.post("/api/dealers/refresh-vehicles")
    def dealers_refresh_vehicles():
        make = current_make()
        if make.slug != "mazda":
            return jsonify({"ok": False, "error": "Dealer vehicle refresh is only supported for Mazda."}), 400
        adapter = get_make_adapter(make.slug)
        refresh = getattr(adapter, "refresh_dealer_vehicles", None)
        if not callable(refresh):
            return jsonify({"ok": False, "error": "Dealer vehicle refresh is not supported for this make."}), 400
        payload = request.get_json(silent=True) or {}
        try:
            all_models, model_codes, _ = validate_ingest_selection(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            request_jobs().start_dealer_vehicle_refresh(
                payload=payload,
                model_codes=model_codes if not all_models else None,
                all_models=all_models,
            )
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "status": request_jobs().ingest_status(), "make": make.slug})

    @app.post("/api/dealers/geocode-batch")
    def dealers_geocode_batch():
        geocode_all = request.args.get("all", "0") == "1"
        force = request.args.get("force", "0") == "1"
        clear_cache = request.args.get("clear", "0") == "1"
        background = request.args.get("background", "0") == "1"
        workers_raw = request.args.get("workers", "8").strip()
        try:
            workers = max(1, min(int(workers_raw), 32))
        except ValueError:
            workers = 8
        limit_raw = request.args.get("limit", "").strip()
        if geocode_all or force:
            limit = None
        elif limit_raw:
            limit = min(max(int(limit_raw), 1), 500)
        else:
            limit = 40

        cleared = 0
        if clear_cache:
            conn = get_conn()
            try:
                cleared = clear_dealer_geo_cache(conn)
            finally:
                conn.close()

        if background:
            try:
                request_jobs().start_geocode(
                    limit=None if (geocode_all or force or clear_cache) else limit,
                    delay_sec=1.1,
                    force=force or clear_cache,
                    workers=workers,
                )
            except RuntimeError as exc:
                return jsonify({"ok": False, "error": str(exc)}), 409
            conn = get_conn(readonly=True)
            try:
                stats = dealer_geo_stats(conn)
            finally:
                conn.close()
            return jsonify(
                {
                    "ok": True,
                    "background": True,
                    "cleared": cleared,
                    "job": request_jobs().geocode_status(),
                    **stats,
                }
            )
        conn = get_conn()
        try:
            result = geocode_all_dealers(
                conn, limit=limit, delay_sec=1.1, force=force, workers=workers
            )
            return jsonify(
                {"ok": True, "all": geocode_all, "force": force, "workers": workers, **result}
            )
        finally:
            conn.close()

    @app.post("/api/dealers/geocode-cancel")
    def dealers_geocode_cancel():
        cancelled = request_jobs().cancel_geocode()
        if not cancelled:
            return jsonify({"ok": False, "error": "No geocoding job is running."}), 409
        return jsonify({"ok": True, "job": request_jobs().geocode_status()})

    @app.get("/api/dealers/geocode-status")
    def dealers_geocode_status():
        conn = get_conn(readonly=True)
        try:
            payload = dealer_geo_stats(conn)
            store = JobRunStore(current_make().database_url)
            job = request_jobs().resolved_geocode_status(store)
            db_remaining = int(payload.get("remaining", 0))
            if job.get("status") in {"idle", "completed", "failed"}:
                job["remaining"] = db_remaining
            if job.get("status") == "idle" and db_remaining > 0:
                job["message"] = f"{db_remaining} dealer(s) need geocoding. Job not running."
            payload["job"] = job
            return jsonify(payload)
        finally:
            conn.close()

    @app.get("/api/image-proxy")
    def image_proxy():
        url = request.args.get("url", "").strip()
        if not url:
            return jsonify({"error": "url query parameter is required"}), 400
        if not is_allowed_image_url(url):
            return jsonify({"error": "image URL host is not allowed"}), 403
        try:
            data, content_type = fetch_proxied_image(url)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 502
        return Response(
            data,
            mimetype=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/catalog/models")
    def catalog_models():
        conn = get_conn(readonly=True)
        try:
            rows = conn.execute(
                """
                SELECT
                    mc.model_code,
                    mc.series,
                    mc.title,
                    mc.year,
                    mc.msrp,
                    COALESCE(
                        NULLIF(mc.image, ''),
                        (
                            SELECT m.href
                            FROM vehicles v
                            JOIN vehicle_media vm ON vm.vin = v.vin
                            JOIN media m ON m.media_id = vm.media_id
                            WHERE UPPER(v.series_code) = UPPER(mc.model_code) AND v.is_active = 1
                              AND m.href IS NOT NULL AND m.href != ''
                            ORDER BY
                                CASE
                                    WHEN LOWER(m.href) LIKE '%profile-jellies%' THEN 0
                                    WHEN LOWER(m.href) LIKE '%profile%' THEN 1
                                    WHEN LOWER(m.href) LIKE '%jellies%' THEN 2
                                    ELSE 3
                                END,
                                vm.media_id
                            LIMIT 1
                        )
                    ) AS image,
                    mc.as_shown,
                    mc.top_label,
                    mc.last_synced_at,
                    (
                        SELECT COUNT(*)
                        FROM vehicles v
                        WHERE UPPER(v.series_code) = UPPER(mc.model_code) AND v.is_active = 1
                    ) AS active_vehicle_count
                FROM model_catalog mc
                ORDER BY mc.title COLLATE NOCASE, mc.model_code
                """
            ).fetchall()
            models = [dict(row) for row in rows]
            if current_make().slug == "mazda":
                from vehicle_inventory.makes.mazda.media import normalize_mazda_media_href

                for model in models:
                    image = str(model.get("image") or "").strip()
                    if image:
                        model["image"] = normalize_mazda_media_href(image)
            return jsonify({"models": models})
        finally:
            conn.close()

    @app.post("/api/ingest/start")
    def ingest_start():
        payload = request.get_json(silent=True) or {}
        make = current_make()
        try:
            all_models, model_codes, _ = validate_ingest_selection(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            request_jobs().start_ingest(
                payload=payload,
                model_codes=model_codes if not all_models else None,
                all_models=all_models,
            )
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"ok": True, "status": request_jobs().ingest_status(), "make": make.slug})

    @app.get("/api/ingest/status")
    def ingest_status():
        store = JobRunStore(current_make().database_url)
        return jsonify(request_jobs().resolved_ingest_status(store))

    @app.get("/api/jobs/runs")
    def jobs_runs_list():
        limit_raw = request.args.get("limit", "50").strip()
        try:
            limit = max(1, min(int(limit_raw), 200))
        except ValueError:
            limit = 50
        job_type = request.args.get("job_type", "").strip() or None
        since_days_raw = request.args.get("since_days", "30").strip()
        try:
            since_days = max(1, min(int(since_days_raw), 365))
        except ValueError:
            since_days = 30
        include_summary = request.args.get("include_summary", "1") != "0"
        store = JobRunStore(current_make().database_url)
        runs = store.list_runs(limit=limit, job_type=job_type, since_days=since_days)
        payload: Dict = {"runs": runs}
        if include_summary:
            payload["summary"] = store.summary(since_days=since_days)
        return jsonify(payload)

    @app.get("/api/jobs/runs/<int:job_run_id>")
    def jobs_runs_detail(job_run_id: int):
        store = JobRunStore(current_make().database_url)
        run = store.get(job_run_id)
        if run is None:
            return jsonify({"error": "Job run not found."}), 404
        return jsonify(run)

    @app.post("/api/jobs/ingest/start")
    def jobs_ingest_start():
        payload = request.get_json(silent=True) or {}
        try:
            all_models, model_codes, _ = validate_ingest_selection(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            status = request_jobs().start_ingest(
                payload=payload,
                model_codes=model_codes if not all_models else None,
                all_models=all_models,
                trigger_source=str(payload.get("trigger_source") or "ui"),
            )
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"ok": True, "status": status})

    @app.get("/api/jobs/ingest/status")
    def jobs_ingest_status():
        store = JobRunStore(current_make().database_url)
        return jsonify(request_jobs().resolved_ingest_status(store))

    @app.post("/api/jobs/geocode/start")
    def jobs_geocode_start():
        payload = request.get_json(silent=True) or {}
        geocode_all = bool(payload.get("all"))
        force = bool(payload.get("force"))
        workers = max(1, min(int(payload.get("workers") or 8), 32))
        limit = None if geocode_all or force else payload.get("limit")
        try:
            status = request_jobs().start_geocode(
                limit=limit,
                delay_sec=float(payload.get("delay_sec") or 1.1),
                force=force,
                workers=workers,
                trigger_source=str(payload.get("trigger_source") or "ui"),
            )
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, "job": status})

    @app.post("/api/jobs/geocode/cancel")
    def jobs_geocode_cancel():
        cancelled = request_jobs().cancel_geocode()
        if not cancelled:
            return jsonify({"ok": False, "error": "No geocoding job is running."}), 409
        return jsonify({"ok": True, "job": request_jobs().geocode_status()})

    @app.get("/api/jobs/geocode/status")
    def jobs_geocode_status():
        conn = get_conn(readonly=True)
        try:
            payload = dict(dealer_geo_stats(conn))
        finally:
            conn.close()
        store = JobRunStore(current_make().database_url)
        job = request_jobs().resolved_geocode_status(store)
        db_remaining = int(payload.get("remaining", 0))
        if job.get("status") in {"idle", "completed", "failed"}:
            job["remaining"] = db_remaining
        if job.get("status") == "idle" and db_remaining > 0:
            job["message"] = f"{db_remaining} dealer(s) need geocoding. Job not running."
        payload["job"] = job
        return jsonify(payload)

    @app.get("/api/summary")
    def summary():
        conn = get_conn(readonly=True)
        try:
            row = conn.execute(
                """
                SELECT
                    (SELECT MAX(run_id) FROM runs) AS latest_run_id,
                    (SELECT queried_at FROM runs WHERE run_id = (SELECT MAX(run_id) FROM runs)) AS latest_queried_at,
                    (SELECT COUNT(*) FROM vehicles WHERE is_active = 1) AS active_count,
                    (SELECT COUNT(*) FROM vehicles) AS all_vehicle_count
                """
            ).fetchone()
            result = dict(row)
            return jsonify(result)
        finally:
            conn.close()

    @app.get("/api/run-stages")
    def run_stages():
        run_id = request.args.get("run_id", "")
        conn = get_conn(readonly=True)
        try:
            if run_id:
                target_run = int(run_id)
            else:
                row = conn.execute("SELECT MAX(run_id) AS max_run_id FROM runs").fetchone()
                target_run = row["max_run_id"] if row else None

            if target_run is None:
                return jsonify({"run_id": None, "stages": []})

            rows = conn.execute(
                """
                SELECT
                    COALESCE(allocation_stage_code, 'UNKNOWN') AS allocation_stage_code,
                    COALESCE(allocation_stage_label, 'Unknown') AS allocation_stage_label,
                    COUNT(*) AS vehicle_count
                FROM vehicle_runs
                WHERE run_id = ?
                GROUP BY allocation_stage_code, allocation_stage_label
                ORDER BY vehicle_count DESC
                """,
                (target_run,),
            ).fetchall()
            return jsonify({"run_id": target_run, "stages": [dict(r) for r in rows]})
        finally:
            conn.close()

    @app.get("/api/vehicle-dealer-map")
    def vehicle_dealer_map():
        run_id = request.args.get("run_id", "")
        conn = get_conn(readonly=True)
        try:
            if run_id:
                target_run = int(run_id)
            else:
                row = conn.execute("SELECT MAX(run_id) AS max_run_id FROM runs").fetchone()
                target_run = row["max_run_id"] if row else None
            if target_run is None:
                return jsonify({"run_id": None, "items": []})

            rows = conn.execute(
                """
                SELECT vr.vin, vr.dealer_cd, d.dealer_marketing_name
                FROM vehicle_runs vr
                LEFT JOIN dealers d ON d.dealer_cd = vr.dealer_cd
                WHERE vr.run_id = ?
                ORDER BY vr.vin
                LIMIT 500
                """,
                (target_run,),
            ).fetchall()
            return jsonify({"run_id": target_run, "items": [dict(r) for r in rows]})
        finally:
            conn.close()

    @app.get("/api/health")
    def health():
        db_ready = False
        try:
            conn = get_conn()
            try:
                conn.execute("SELECT 1 AS ok").fetchone()
                db_ready = True
            finally:
                conn.close()
        except Exception:
            db_ready = False
        make = current_make()
        return jsonify(
            {
                "ok": db_ready,
                "make": make.slug,
                "use_redis_jobs": runtime_settings.use_redis_jobs,
                "db_ready": db_ready,
                "ingest_running": request_jobs().ingest_is_running(),
                "geocode_running": request_jobs().geocode_is_running(),
            }
        )

    @app.get("/api/vehicle/<vin>")
    def vehicle_detail(vin: str):
        conn = get_conn(readonly=True)
        try:
            base = conn.execute(
                """
                SELECT
                    v.vin,
                    v.series_code,
                    v.marketing_series,
                    v.grade,
                    v.model_marketing_name,
                    v.model_marketing_title,
                    v.year,
                    v.exterior_color_name,
                    v.exterior_color_hex,
                    v.exterior_color_swatch,
                    v.interior_color_name,
                    v.interior_color_swatch,
                    v.engine_name,
                    v.drivetrain_code,
                    v.drivetrain_title,
                    v.transmission_type,
                    v.first_seen_at,
                    v.last_seen_at,
                    v.is_active
                FROM vehicles v
                WHERE v.vin = ?
                """,
                (vin,),
            ).fetchone()
            if not base:
                return jsonify({"error": "VIN not found"}), 404

            latest_run = conn.execute(
                """
                SELECT
                    vr.run_id,
                    r.queried_at,
                    vr.dealer_cd,
                    vr.stock_num,
                    d.dealer_marketing_name,
                    d.dealer_website,
                    vr.inventory_status,
                    vr.allocation_stage_code,
                    vr.allocation_stage_label,
                    vr.distance,
                    vr.vdp_url,
                    p.advertized_price,
                    p.non_sp_advertized_price,
                    p.total_msrp,
                    p.base_msrp,
                    p.selling_price
                FROM vehicle_runs vr
                JOIN runs r ON r.run_id = vr.run_id
                LEFT JOIN dealers d ON d.dealer_cd = vr.dealer_cd
                LEFT JOIN vehicle_prices p ON p.vin = vr.vin AND p.run_id = vr.run_id
                WHERE vr.vin = ?
                ORDER BY vr.run_id DESC
                LIMIT 1
                """,
                (vin,),
            ).fetchone()

            options = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        o.option_cd,
                        o.marketing_name,
                        o.marketing_long_name,
                        o.option_type,
                        o.package_ind
                    FROM vehicle_options vo
                    JOIN options o ON o.option_cd = vo.option_cd
                    WHERE vo.vin = ?
                    ORDER BY o.option_type, o.option_cd
                    """,
                    (vin,),
                ).fetchall()
            ]

            wheel_options = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        o.option_cd,
                        o.marketing_name
                    FROM vehicle_options vo
                    JOIN options o ON o.option_cd = vo.option_cd
                    WHERE vo.vin = ?
                      AND (
                        LOWER(COALESCE(o.marketing_name, '')) LIKE '%wheel%'
                        OR LOWER(COALESCE(o.marketing_name, '')) LIKE '%inch%'
                      )
                    ORDER BY o.marketing_name
                    """,
                    (vin,),
                ).fetchall()
            ]

            media = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        m.media_id,
                        m.href,
                        m.media_type,
                        m.media_size,
                        m.image_tag
                    FROM vehicle_media vm
                    JOIN media m ON m.media_id = vm.media_id
                    WHERE vm.vin = ?
                    ORDER BY
                        CASE
                            WHEN LOWER(m.href) LIKE '%/i360-%'
                              OR LOWER(m.href) LIKE '%/e360-%'
                              OR LOWER(m.media_type) = 'interior360' THEN 2
                            ELSE 1
                        END,
                        CASE m.media_type
                            WHEN 'carjellyimage' THEN 1
                            WHEN 'exterior' THEN 2
                            WHEN 'interior' THEN 3
                            WHEN 'interior360' THEN 4
                            ELSE 5
                        END,
                        m.media_size
                    """,
                    (vin,),
                ).fetchall()
            ]

            price_history = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        p.run_id,
                        r.queried_at,
                        p.advertized_price,
                        p.non_sp_advertized_price,
                        p.total_msrp,
                        p.base_msrp,
                        p.selling_price
                    FROM vehicle_prices p
                    JOIN runs r ON r.run_id = p.run_id
                    WHERE p.vin = ?
                    ORDER BY p.run_id DESC
                    """,
                    (vin,),
                ).fetchall()
            ]

            if current_make().slug == "mazda":
                from vehicle_inventory.makes.mazda.media import enrich_mazda_media_row

                media = [enrich_mazda_media_row(row) for row in media]

            return jsonify(
                {
                    "vehicle": dict(base),
                    "latest": dict(latest_run) if latest_run else None,
                    "options": options,
                    "media": media,
                    "price_history": price_history,
                    "wheel_options": wheel_options,
                }
            )
        finally:
            conn.close()

    return app

