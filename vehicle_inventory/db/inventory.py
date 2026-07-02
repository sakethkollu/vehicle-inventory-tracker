import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from vehicle_inventory.db.backend import DbConnection, open_db_connection
from vehicle_inventory.db.sql_compat import ensure_index, table_exists_sql

ALLOCATION_STAGE_LABELS = {
    "A": "Allocation",
    "F": "Freight",
    "G": "Ground",
    "01": "In Transit",
    "02": "At Dealership",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InventoryDb:
    def __init__(
        self,
        *,
        database_url: str,
        schema_path: Optional[Path] = None,
    ):
        self.database_url = database_url
        self.schema_path = schema_path or Path(__file__).resolve().parent / "schema_mysql.sql"
        self.conn: DbConnection = open_db_connection(database_url)

    def close(self) -> None:
        self.conn.close()

    def initialize(self) -> None:
        schema = self.schema_path.read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self._apply_migrations()
        self.conn.commit()

    def _apply_migrations(self) -> None:
        self._ensure_column(
            table_name="vehicle_runs",
            column_name="allocation_stage_code",
            column_type="TEXT",
        )
        self._ensure_column(
            table_name="vehicle_runs",
            column_name="allocation_stage_label",
            column_type="TEXT",
        )
        ensure_index(
            self.conn,
            name="idx_vehicle_runs_stage_code",
            table="vehicle_runs",
            columns="allocation_stage_code",
        )
        self._ensure_query_performance_indexes()
        self._ensure_column(
            table_name="vehicles",
            column_name="exterior_color_swatch",
            column_type="TEXT",
        )
        self._ensure_column(
            table_name="vehicles",
            column_name="interior_color_swatch",
            column_type="TEXT",
        )
        from vehicle_inventory.geo.dealer_geo import ensure_dealer_geo_cache_table
        from vehicle_inventory.jobs.runs import ensure_job_runs_table

        ensure_dealer_geo_cache_table(self.conn)
        ensure_job_runs_table(self.conn)
        self._repair_mazda_media_hrefs()

    def _repair_mazda_media_hrefs(self) -> None:
        if "mazda" not in self.database_url.lower():
            return
        from vehicle_inventory.makes.mazda.media import classify_mazda_media, normalize_mazda_media_href

        rows = self.conn.execute(
            """
            SELECT media_id, href, media_type, image_tag
            FROM media
            WHERE href LIKE '%mazdausa.com:443%'
            """
        ).fetchall()
        for row in rows:
            media_id = int(row["media_id"])
            old_href = str(row["href"] or "")
            new_href = normalize_mazda_media_href(old_href)
            classified = classify_mazda_media(
                new_href,
                image_tag=str(row["image_tag"] or ""),
                media_type=str(row["media_type"] or ""),
            )
            media_type = classified["type"]
            image_tag = classified.get("imageTag") or row["image_tag"]

            if new_href != old_href:
                existing = self.conn.execute(
                    "SELECT media_id FROM media WHERE href = ?",
                    (new_href,),
                ).fetchone()
                if existing and int(existing["media_id"]) != media_id:
                    target_id = int(existing["media_id"])
                    self.conn.execute(
                        """
                        INSERT INTO vehicle_media (vin, media_id, first_seen_at, last_seen_at)
                        SELECT vin, ?, first_seen_at, last_seen_at
                        FROM vehicle_media
                        WHERE media_id = ?
                        ON CONFLICT(vin, media_id) DO UPDATE SET
                            last_seen_at=excluded.last_seen_at
                        """,
                        (target_id, media_id),
                    )
                    self.conn.execute("DELETE FROM vehicle_media WHERE media_id = ?", (media_id,))
                    self.conn.execute("DELETE FROM media WHERE media_id = ?", (media_id,))
                    self.conn.execute(
                        """
                        UPDATE media
                        SET media_type = ?, image_tag = COALESCE(?, image_tag), updated_at = ?
                        WHERE media_id = ?
                        """,
                        (media_type, image_tag, utc_now(), target_id),
                    )
                    continue

            self.conn.execute(
                """
                UPDATE media
                SET href = ?, media_type = ?, image_tag = COALESCE(?, image_tag), updated_at = ?
                WHERE media_id = ?
                """,
                (new_href, media_type, image_tag, utc_now(), media_id),
            )

    def _ensure_query_performance_indexes(self) -> None:
        from vehicle_inventory.db.run_scope import ensure_series_latest_runs_table

        ensure_series_latest_runs_table(self.conn)
        for name, table, columns in (
            ("idx_vehicle_runs_vin_run", "vehicle_runs", "vin, run_id"),
            ("idx_vehicle_prices_vin_run", "vehicle_prices", "vin, run_id"),
            ("idx_vehicle_runs_run_id", "vehicle_runs", "run_id"),
            ("idx_vehicle_runs_dealer", "vehicle_runs", "dealer_cd"),
            ("idx_vehicles_active_series", "vehicles", "is_active, series_code"),
            ("idx_vehicle_options_vin", "vehicle_options", "vin"),
        ):
            ensure_index(
                self.conn,
                name=name,
                table=table,
                columns=columns,
            )

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(table_exists_sql(), (table_name,)).fetchone()
        return row is not None

    def _ensure_column(self, table_name: str, column_name: str, column_type: str) -> None:
        if not self._table_exists(table_name):
            return
        rows = self.conn.execute(
            "SELECT COLUMN_NAME AS name FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            (table_name,),
        ).fetchall()
        names = {row["name"] for row in rows}
        if column_name in names:
            return
        self.conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
        )

    def create_run(
        self,
        queried_at: str,
        zip_code: str,
        distance: int,
        page_size: int,
        series_codes: List[str],
        lead_id: Optional[str],
        archive_dir: Optional[str],
        *,
        source: str = "graphql",
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO runs (
                queried_at, source, zip_code, distance, page_size, series_codes_json, lead_id, archive_dir
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                queried_at,
                source,
                zip_code,
                distance,
                page_size,
                json.dumps(series_codes, separators=(",", ":")),
                lead_id,
                archive_dir,
            ),
        )
        self.conn.commit()
        return int(self.conn.lastrowid)

    def upsert_series(self, series_code: str, marketing_series: Optional[str], ts: str) -> None:
        self.conn.execute(
            """
            INSERT INTO series (series_code, marketing_series, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(series_code) DO UPDATE SET
                marketing_series=COALESCE(excluded.marketing_series, series.marketing_series),
                updated_at=excluded.updated_at
            """,
            (series_code, marketing_series, ts, ts),
        )

    def upsert_model_catalog(self, models: Iterable[Dict], ts: str) -> None:
        for model in models:
            model_code = model.get("model_code") or model.get("modelCode")
            if not model_code:
                continue
            self.conn.execute(
                """
                INSERT INTO model_catalog (
                    model_code, series, title, year, msrp, image, as_shown, top_label, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_code) DO UPDATE SET
                    series=excluded.series,
                    title=excluded.title,
                    year=excluded.year,
                    msrp=excluded.msrp,
                    image=COALESCE(NULLIF(excluded.image, ''), model_catalog.image),
                    as_shown=excluded.as_shown,
                    top_label=excluded.top_label,
                    last_synced_at=excluded.last_synced_at
                """,
                (
                    model_code,
                    model.get("series"),
                    model.get("title"),
                    model.get("year"),
                    model.get("msrp"),
                    model.get("image"),
                    model.get("as_shown") or model.get("asShown"),
                    model.get("top_label") or model.get("topLabel"),
                    ts,
                ),
            )
            self.upsert_series(series_code=model_code, marketing_series=model.get("series"), ts=ts)

    def patch_model_catalog_image_if_missing(self, model_code: str, image: str, ts: str) -> None:
        model_code = str(model_code or "").strip()
        image = str(image or "").strip()
        if not model_code or not image:
            return
        self.conn.execute(
            """
            UPDATE model_catalog
            SET image = ?, last_synced_at = COALESCE(last_synced_at, ?)
            WHERE model_code = ? AND (image IS NULL OR image = '')
            """,
            (image, ts, model_code),
        )

    def list_model_catalog(self) -> List[Dict]:
        rows = self.conn.execute(
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
            ORDER BY mc.title, mc.model_code
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_dealer(self, dealer: Dict, ts: str) -> None:
        dealer_cd = dealer.get("dealerCd")
        if not dealer_cd:
            return
        self.conn.execute(
            """
            INSERT INTO dealers (
                dealer_cd, dealer_marketing_name, dealer_website, distributor_cd,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dealer_cd) DO UPDATE SET
                dealer_marketing_name=CASE
                    WHEN excluded.dealer_marketing_name IS NOT NULL
                         AND excluded.dealer_marketing_name <> excluded.dealer_cd
                    THEN excluded.dealer_marketing_name
                    WHEN dealers.dealer_marketing_name IS NULL
                         OR dealers.dealer_marketing_name = dealers.dealer_cd
                    THEN COALESCE(excluded.dealer_marketing_name, dealers.dealer_marketing_name)
                    ELSE dealers.dealer_marketing_name
                END,
                dealer_website=COALESCE(excluded.dealer_website, dealers.dealer_website),
                distributor_cd=COALESCE(excluded.distributor_cd, dealers.distributor_cd),
                updated_at=excluded.updated_at
            """,
            (
                dealer_cd,
                dealer.get("dealerMarketingName"),
                dealer.get("dealerWebsite"),
                dealer.get("distributorCd"),
                ts,
                ts,
            ),
        )

    def upsert_vehicle(self, vehicle: Dict, series_code: str, ts: str) -> None:
        model = vehicle.get("model") or {}
        transmission = vehicle.get("transmission") or {}
        fuel = vehicle.get("fuelType") or {}
        engine = vehicle.get("engine") or {}
        drivetrain = vehicle.get("drivetrain") or {}
        ext = vehicle.get("extColor") or {}
        intr = vehicle.get("intColor") or {}

        self.conn.execute(
            """
            INSERT INTO vehicles (
                vin, brand, series_code, marketing_series, grade, dealer_trim, year,
                model_cd, model_marketing_name, model_marketing_title,
                transmission_type, fuel_type_code, fuel_type_name, engine_cd, engine_name,
                drivetrain_code, drivetrain_title,
                exterior_color_cd, exterior_color_name, exterior_color_hex, exterior_color_swatch,
                interior_color_cd, interior_color_name, interior_color_swatch,
                first_seen_at, last_seen_at, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(vin) DO UPDATE SET
                brand=COALESCE(excluded.brand, vehicles.brand),
                series_code=excluded.series_code,
                marketing_series=COALESCE(excluded.marketing_series, vehicles.marketing_series),
                grade=COALESCE(excluded.grade, vehicles.grade),
                dealer_trim=COALESCE(excluded.dealer_trim, vehicles.dealer_trim),
                year=COALESCE(excluded.year, vehicles.year),
                model_cd=COALESCE(excluded.model_cd, vehicles.model_cd),
                model_marketing_name=COALESCE(excluded.model_marketing_name, vehicles.model_marketing_name),
                model_marketing_title=COALESCE(excluded.model_marketing_title, vehicles.model_marketing_title),
                transmission_type=COALESCE(excluded.transmission_type, vehicles.transmission_type),
                fuel_type_code=COALESCE(excluded.fuel_type_code, vehicles.fuel_type_code),
                fuel_type_name=COALESCE(excluded.fuel_type_name, vehicles.fuel_type_name),
                engine_cd=COALESCE(excluded.engine_cd, vehicles.engine_cd),
                engine_name=COALESCE(excluded.engine_name, vehicles.engine_name),
                drivetrain_code=COALESCE(excluded.drivetrain_code, vehicles.drivetrain_code),
                drivetrain_title=COALESCE(excluded.drivetrain_title, vehicles.drivetrain_title),
                exterior_color_cd=COALESCE(excluded.exterior_color_cd, vehicles.exterior_color_cd),
                exterior_color_name=COALESCE(excluded.exterior_color_name, vehicles.exterior_color_name),
                exterior_color_hex=COALESCE(excluded.exterior_color_hex, vehicles.exterior_color_hex),
                exterior_color_swatch=CASE
                    WHEN excluded.exterior_color_hex IS NOT NULL AND excluded.exterior_color_swatch IS NULL
                    THEN NULL
                    ELSE COALESCE(excluded.exterior_color_swatch, vehicles.exterior_color_swatch)
                END,
                interior_color_cd=COALESCE(excluded.interior_color_cd, vehicles.interior_color_cd),
                interior_color_name=COALESCE(excluded.interior_color_name, vehicles.interior_color_name),
                interior_color_swatch=COALESCE(excluded.interior_color_swatch, vehicles.interior_color_swatch),
                last_seen_at=excluded.last_seen_at,
                is_active=1,
                updated_at=excluded.updated_at
            """,
            (
                vehicle["vin"],
                vehicle.get("brand"),
                series_code,
                vehicle.get("marketingSeries"),
                vehicle.get("grade"),
                vehicle.get("dealerTrim"),
                vehicle.get("year"),
                model.get("modelCd"),
                model.get("marketingName"),
                model.get("marketingTitle"),
                transmission.get("transmissionType"),
                fuel.get("code"),
                fuel.get("name"),
                engine.get("engineCd"),
                engine.get("name"),
                drivetrain.get("code"),
                drivetrain.get("title"),
                ext.get("colorCd"),
                ext.get("marketingName"),
                ext.get("colorHexCd"),
                ext.get("colorSwatch"),
                intr.get("colorCd"),
                intr.get("marketingName"),
                intr.get("colorSwatch"),
                ts,
                ts,
                ts,
                ts,
            ),
        )

    def insert_vehicle_run(self, run_id: int, vehicle: Dict, ts: str) -> None:
        mpg = vehicle.get("mpg") or {}
        allocation_stage_code = vehicle.get("dealerCategory")
        allocation_stage_label = ALLOCATION_STAGE_LABELS.get(allocation_stage_code)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO vehicle_runs (
                run_id, vin, dealer_cd, stock_num, inventory_status, is_pre_sold,
                is_smart_path, is_unlock_price_dealer, distance, inventory_mileage,
                vdp_url, family_json, cab_json, bed_json, mpg_city, mpg_highway, mpg_combined,
                allocation_stage_code, allocation_stage_label,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                vehicle["vin"],
                vehicle.get("dealerCd"),
                vehicle.get("stockNum"),
                vehicle.get("inventoryStatus"),
                int(bool(vehicle.get("isPreSold"))),
                int(bool(vehicle.get("isSmartPath"))),
                int(bool(vehicle.get("isUnlockPriceDealer"))),
                vehicle.get("distance"),
                vehicle.get("inventoryMileage"),
                vehicle.get("vdpUrl"),
                json.dumps(vehicle.get("family"), separators=(",", ":")),
                json.dumps(vehicle.get("cab"), separators=(",", ":")),
                json.dumps(vehicle.get("bed"), separators=(",", ":")),
                mpg.get("city"),
                mpg.get("highway"),
                mpg.get("combined"),
                allocation_stage_code,
                allocation_stage_label,
                ts,
            ),
        )

    def insert_vehicle_price(self, run_id: int, vin: str, price: Optional[Dict], ts: str) -> None:
        price = price or {}
        self.conn.execute(
            """
            INSERT OR REPLACE INTO vehicle_prices (
                run_id, vin, advertized_price, non_sp_advertized_price, total_msrp,
                selling_price, dph, dio_total_msrp, dio_total_dealer_selling_price,
                dealer_cash_applied, base_msrp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                vin,
                price.get("advertizedPrice"),
                price.get("nonSpAdvertizedPrice"),
                price.get("totalMsrp"),
                price.get("sellingPrice"),
                price.get("dph"),
                price.get("dioTotalMsrp"),
                price.get("dioTotalDealerSellingPrice"),
                price.get("dealerCashApplied"),
                price.get("baseMsrp"),
                ts,
            ),
        )

    def upsert_option(self, option: Dict, ts: str) -> None:
        option_cd = option.get("optionCd")
        if not option_cd:
            return
        self.conn.execute(
            """
            INSERT INTO options (
                option_cd, marketing_name, marketing_long_name, option_type, package_ind,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(option_cd) DO UPDATE SET
                marketing_name=COALESCE(excluded.marketing_name, options.marketing_name),
                marketing_long_name=COALESCE(excluded.marketing_long_name, options.marketing_long_name),
                option_type=COALESCE(excluded.option_type, options.option_type),
                package_ind=COALESCE(excluded.package_ind, options.package_ind),
                updated_at=excluded.updated_at
            """,
            (
                option_cd,
                option.get("marketingName"),
                option.get("marketingLongName"),
                option.get("optionType"),
                int(bool(option.get("packageInd"))),
                ts,
                ts,
            ),
        )

    def link_vehicle_option(self, vin: str, option_cd: str, ts: str) -> None:
        self.conn.execute(
            """
            INSERT INTO vehicle_options (vin, option_cd, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(vin, option_cd) DO UPDATE SET
                last_seen_at=excluded.last_seen_at
            """,
            (vin, option_cd, ts, ts),
        )

    def upsert_media(self, media: Dict, ts: str) -> Optional[int]:
        href = media.get("href")
        if not href:
            return None
        href = str(href).strip()
        if "mazdausa.com" in href.lower():
            from vehicle_inventory.makes.mazda.media import normalize_mazda_media_href

            href = normalize_mazda_media_href(href)
        self.conn.execute(
            """
            INSERT INTO media (href, media_type, media_size, image_tag, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(href) DO UPDATE SET
                media_type=COALESCE(excluded.media_type, media.media_type),
                media_size=COALESCE(excluded.media_size, media.media_size),
                image_tag=COALESCE(excluded.image_tag, media.image_tag),
                source=COALESCE(excluded.source, media.source),
                updated_at=excluded.updated_at
            """,
            (
                href,
                media.get("type"),
                media.get("size"),
                media.get("imageTag"),
                media.get("source"),
                ts,
                ts,
            ),
        )
        row = self.conn.execute("SELECT media_id FROM media WHERE href = ?", (href,)).fetchone()
        return int(row["media_id"]) if row else None

    def link_vehicle_media(self, vin: str, media_id: int, ts: str) -> None:
        self.conn.execute(
            """
            INSERT INTO vehicle_media (vin, media_id, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(vin, media_id) DO UPDATE SET
                last_seen_at=excluded.last_seen_at
            """,
            (vin, media_id, ts, ts),
        )

    def insert_vehicle_snapshot(self, run_id: int, vin: str, vehicle: Dict, ts: str) -> None:
        encoded = json.dumps(vehicle, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        payload = gzip.compress(encoded)
        sha = hashlib.sha256(encoded).hexdigest()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO vehicle_snapshots (run_id, vin, payload_gzip, payload_sha256, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, vin, payload, sha, ts),
        )

    def mark_inactive_not_seen(self, run_id: int, series_codes: Iterable[str], ts: str) -> int:
        codes = list(series_codes)
        if not codes:
            return 0
        placeholders = ",".join("?" for _ in codes)
        sql = f"""
            UPDATE vehicles
            SET is_active = 0, updated_at = ?
            WHERE series_code IN ({placeholders})
            AND vin NOT IN (
                SELECT vin FROM vehicle_runs WHERE run_id = ?
            )
        """
        cur = self.conn.execute(sql, (ts, *codes, run_id))
        return cur.rowcount

    def process_vehicle(self, run_id: int, series_code: str, vehicle: Dict, ts: str) -> None:
        if "vin" not in vehicle:
            return
        self.upsert_series(series_code=series_code, marketing_series=vehicle.get("marketingSeries"), ts=ts)
        self.upsert_dealer(vehicle, ts=ts)
        self.upsert_vehicle(vehicle=vehicle, series_code=series_code, ts=ts)
        self.insert_vehicle_run(run_id=run_id, vehicle=vehicle, ts=ts)
        self.insert_vehicle_price(run_id=run_id, vin=vehicle["vin"], price=vehicle.get("price"), ts=ts)

        for option in vehicle.get("options") or []:
            option_cd = option.get("optionCd")
            if not option_cd:
                continue
            self.upsert_option(option, ts=ts)
            self.link_vehicle_option(vehicle["vin"], option_cd, ts=ts)

        for media in vehicle.get("media") or []:
            media_id = self.upsert_media(media, ts=ts)
            if media_id is not None:
                self.link_vehicle_media(vehicle["vin"], media_id, ts=ts)

        jelly = vehicle.get("jelly")
        if jelly:
            media_id = self.upsert_media(jelly, ts=ts)
            if media_id is not None:
                self.link_vehicle_media(vehicle["vin"], media_id, ts=ts)

        self.insert_vehicle_snapshot(run_id=run_id, vin=vehicle["vin"], vehicle=vehicle, ts=ts)

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def decode_snapshot_payload(self, run_id: int, vin: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT payload_gzip FROM vehicle_snapshots WHERE run_id = ? AND vin = ?",
            (run_id, vin),
        ).fetchone()
        if not row:
            return None
        raw = gzip.decompress(row["payload_gzip"])
        return json.loads(raw.decode("utf-8"))
