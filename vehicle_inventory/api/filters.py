from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from vehicle_inventory.db.backend import DbConnection
from vehicle_inventory.geo.dealer_geo import (
    append_run_location_filters,
    dealer_display_distance_sql,
    ensure_dealer_geo_cache_table,
    expand_state_filter_values,
    geocode_postal_code,
    normalize_dealer_display_distance,
    normalize_state_code,
    normalize_us_zip,
    state_label,
)
from vehicle_inventory.db.run_scope import vehicle_runs_latest_join
from vehicle_inventory.db.sql_compat import ensure_index, haversine_miles_sql


@dataclass
class FilterContext:
    series_codes: List[str] = field(default_factory=list)
    active_only: bool = True
    model_values: List[str] = field(default_factory=list)
    exterior_colors: List[str] = field(default_factory=list)
    interior_colors: List[str] = field(default_factory=list)
    drivetrain_codes: List[str] = field(default_factory=list)
    stage_codes: List[str] = field(default_factory=list)
    option_codes: List[str] = field(default_factory=list)
    dealer_codes: List[str] = field(default_factory=list)
    distance_max: Optional[int] = None
    distance_min: Optional[int] = None
    search_zip: Optional[str] = None
    filter_by_distance: bool = False
    state_codes: List[str] = field(default_factory=list)
    reference_lat: Optional[float] = None
    reference_lng: Optional[float] = None


def _parse_series_codes(args) -> List[str]:
    raw = args.get("series_codes", "").strip()
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    legacy = args.get("series_code", "").strip()
    return [legacy] if legacy else []


def _parse_int_arg(args, key: str) -> Optional[int]:
    raw = args.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_float_arg(args, key: str) -> Optional[float]:
    raw = args.get(key, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_filter_context(args) -> FilterContext:
    return FilterContext(
        series_codes=_parse_series_codes(args),
        active_only=args.get("active_only", "1") == "1",
        model_values=[
            x.strip() for x in args.get("model_marketing_names", "").split(",") if x.strip()
        ],
        exterior_colors=[x.strip() for x in args.get("exterior_colors", "").split(",") if x.strip()],
        interior_colors=[x.strip() for x in args.get("interior_colors", "").split(",") if x.strip()],
        drivetrain_codes=[
            x.strip().upper() for x in args.get("drivetrain_codes", "").split(",") if x.strip()
        ],
        stage_codes=[x.strip().upper() for x in args.get("stage_codes", "").split(",") if x.strip()],
        option_codes=[x.strip() for x in args.get("option_codes", "").split(",") if x.strip()],
        dealer_codes=[x.strip() for x in args.get("dealer_codes", "").split(",") if x.strip()],
        distance_max=_parse_int_arg(args, "distance_max"),
        distance_min=_parse_int_arg(args, "distance_min"),
        search_zip=normalize_us_zip(args.get("search_zip", "").strip()),
        filter_by_distance=args.get("filter_by_distance", "0") == "1",
        state_codes=[
            x.strip().upper() for x in args.get("state_codes", "").split(",") if x.strip()
        ],
        reference_lat=_parse_float_arg(args, "reference_lat"),
        reference_lng=_parse_float_arg(args, "reference_lng"),
    )


def _build_vehicle_scope(
    ctx: FilterContext,
    exclude: Optional[str] = None,
) -> Tuple[str, str, List]:
    joins: List[str] = []
    where = ["1=1"]
    params: List = []

    run_series = None if exclude == "series" else (ctx.series_codes or None)
    run_join, run_params = vehicle_runs_latest_join(run_series)
    joins.append(run_join)
    params.extend(run_params)

    if exclude != "series" and ctx.series_codes:
        placeholders = ",".join("?" for _ in ctx.series_codes)
        where.append(f"v.series_code IN ({placeholders})")
        params.extend(ctx.series_codes)
    if ctx.active_only:
        where.append("v.is_active = 1")

    if exclude != "model" and ctx.model_values:
        placeholders = ",".join("?" for _ in ctx.model_values)
        where.append(f"v.model_marketing_name IN ({placeholders})")
        params.extend(ctx.model_values)

    if exclude != "exterior" and ctx.exterior_colors:
        placeholders = ",".join("?" for _ in ctx.exterior_colors)
        where.append(f"COALESCE(v.exterior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(ctx.exterior_colors)

    if exclude != "interior" and ctx.interior_colors:
        placeholders = ",".join("?" for _ in ctx.interior_colors)
        where.append(f"COALESCE(v.interior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(ctx.interior_colors)

    if exclude != "drivetrain" and ctx.drivetrain_codes:
        placeholders = ",".join("?" for _ in ctx.drivetrain_codes)
        where.append(f"COALESCE(v.drivetrain_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(ctx.drivetrain_codes)

    if exclude != "stage" and ctx.stage_codes:
        placeholders = ",".join("?" for _ in ctx.stage_codes)
        where.append(f"COALESCE(vr.allocation_stage_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(ctx.stage_codes)

    if exclude != "option" and ctx.option_codes:
        placeholders = ",".join("?" for _ in ctx.option_codes)
        where.append(
            f"""
            (
                SELECT COUNT(DISTINCT vo.option_cd)
                FROM vehicle_options vo
                WHERE vo.vin = v.vin AND vo.option_cd IN ({placeholders})
            ) = ?
            """
        )
        params.extend(ctx.option_codes)
        params.append(len(ctx.option_codes))

    if exclude != "dealer" and ctx.dealer_codes:
        placeholders = ",".join("?" for _ in ctx.dealer_codes)
        where.append(f"vr.dealer_cd IN ({placeholders})")
        params.extend(ctx.dealer_codes)

    location_excluded = exclude in {"distance", "state"}
    append_run_location_filters(
        where,
        params,
        distance_max=ctx.distance_max if ctx.filter_by_distance and not location_excluded else None,
        distance_min=ctx.distance_min if ctx.filter_by_distance and not location_excluded else None,
        state_codes=ctx.state_codes if exclude != "state" else None,
        search_zip=ctx.search_zip if ctx.filter_by_distance and not location_excluded else None,
    )

    from_sql = f"vehicles v {' '.join(joins)}".strip()
    return from_sql, " AND ".join(where), params


def _series_only_context(ctx: FilterContext) -> FilterContext:
    return FilterContext(series_codes=ctx.series_codes, active_only=ctx.active_only)


def _query_model_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="model"    )

    universe_rows = conn.execute(
        f"""
        SELECT v.model_marketing_name AS value, COUNT(*) AS vehicle_count
        FROM {universe_from}
        WHERE {universe_where} AND v.model_marketing_name IS NOT NULL
        GROUP BY v.model_marketing_name
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT v.model_marketing_name AS value
        FROM {available_from}
        WHERE {available_where} AND v.model_marketing_name IS NOT NULL
        """,
        available_params,
    ).fetchall()
    return _merge_facet_rows(universe_rows, {row["value"] for row in available_rows})


def _query_exterior_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="exterior"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            COALESCE(v.exterior_color_name, 'Unknown') AS value,
            MAX(v.exterior_color_hex) AS exterior_color_hex,
            MAX(v.exterior_color_swatch) AS exterior_color_swatch,
            COUNT(*) AS vehicle_count
        FROM {universe_from}
        WHERE {universe_where}
        GROUP BY COALESCE(v.exterior_color_name, 'Unknown')
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT COALESCE(v.exterior_color_name, 'Unknown') AS value
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    available = {row["value"] for row in available_rows}
    items = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available
        items.append(payload)
    return items


def _query_interior_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="interior"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            COALESCE(v.interior_color_name, 'Unknown') AS value,
            MAX(v.interior_color_swatch) AS interior_color_swatch,
            COUNT(*) AS vehicle_count
        FROM {universe_from}
        WHERE {universe_where}
        GROUP BY COALESCE(v.interior_color_name, 'Unknown')
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT COALESCE(v.interior_color_name, 'Unknown') AS value
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    available = {row["value"] for row in available_rows}
    items = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available
        items.append(payload)
    return items


def _query_drivetrain_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="drivetrain"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            COALESCE(v.drivetrain_code, 'UNKNOWN') AS value,
            MAX(v.drivetrain_title) AS label,
            COUNT(*) AS vehicle_count
        FROM {universe_from}
        WHERE {universe_where}
        GROUP BY COALESCE(v.drivetrain_code, 'UNKNOWN')
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT COALESCE(v.drivetrain_code, 'UNKNOWN') AS value
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    return _merge_facet_rows(universe_rows, {row["value"] for row in available_rows}, label_key="label")


def _query_stage_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="stage"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            COALESCE(vr.allocation_stage_code, 'UNKNOWN') AS value,
            COALESCE(vr.allocation_stage_label, 'Unknown') AS label,
            COUNT(*) AS vehicle_count
        FROM {universe_from}
        WHERE {universe_where}
        GROUP BY allocation_stage_code, allocation_stage_label
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT COALESCE(vr.allocation_stage_code, 'UNKNOWN') AS value
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    return _merge_facet_rows(universe_rows, {row["value"] for row in available_rows}, label_key="label")


def _query_option_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="option"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            o.option_cd AS value,
            o.marketing_name AS label,
            COUNT(DISTINCT v.vin) AS vehicle_count
        FROM {universe_from}
        JOIN vehicle_options vo ON vo.vin = v.vin
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE {universe_where}
        GROUP BY o.option_cd, o.marketing_name
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT o.option_cd AS value
        FROM {available_from}
        JOIN vehicle_options vo ON vo.vin = v.vin
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    return _merge_facet_rows(universe_rows, {row["value"] for row in available_rows}, label_key="label")


def _dealer_join_suffix() -> str:
    return " LEFT JOIN dealers d ON d.dealer_cd = vr.dealer_cd"


def _filter_reference_coords(ctx: FilterContext) -> Optional[Tuple[float, float]]:
    if expand_state_filter_values(ctx.state_codes or []):
        return None
    if ctx.search_zip:
        return geocode_postal_code(ctx.search_zip)
    return None


def _query_dealer_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="dealer"    )
    geo_join = " LEFT JOIN dealer_geo_cache dgc ON dgc.dealer_cd = vr.dealer_cd"
    ref = _filter_reference_coords(ctx)

    if ref:
        lat, lng = ref
        miles = haversine_miles_sql("?", "?")
        distance_sql = dealer_display_distance_sql(miles)
        universe_rows = conn.execute(
            f"""
            SELECT
                vr.dealer_cd AS value,
                MAX(COALESCE(d.dealer_marketing_name, vr.dealer_cd)) AS label,
                COUNT(*) AS vehicle_count,
                {distance_sql}
            FROM {universe_from}{_dealer_join_suffix()}{geo_join}
            WHERE {universe_where} AND vr.dealer_cd IS NOT NULL
            GROUP BY vr.dealer_cd
            ORDER BY distance_miles IS NULL, distance_miles, label
            """,
            [lat, lng, lat, *universe_params],
        ).fetchall()
    else:
        universe_rows = conn.execute(
            f"""
            SELECT
                vr.dealer_cd AS value,
                MAX(COALESCE(d.dealer_marketing_name, vr.dealer_cd)) AS label,
                COUNT(*) AS vehicle_count
            FROM {universe_from}{_dealer_join_suffix()}
            WHERE {universe_where} AND vr.dealer_cd IS NOT NULL
            GROUP BY vr.dealer_cd
            ORDER BY label
            """,
            universe_params,
        ).fetchall()

    available_rows = conn.execute(
        f"""
        SELECT DISTINCT vr.dealer_cd AS value
        FROM {available_from}{_dealer_join_suffix()}
        WHERE {available_where} AND vr.dealer_cd IS NOT NULL
        """,
        available_params,
    ).fetchall()
    items = _merge_facet_rows(universe_rows, {row["value"] for row in available_rows}, label_key="label")
    for item in items:
        item["distance_miles"] = normalize_dealer_display_distance(item.get("distance_miles"))
    return items


def _query_state_facets(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    ensure_dealer_geo_cache_table(conn)

    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="state"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            UPPER(TRIM(COALESCE(dgc.state, ''))) AS value,
            COUNT(*) AS vehicle_count
        FROM {universe_from}
        LEFT JOIN dealer_geo_cache dgc ON dgc.dealer_cd = vr.dealer_cd
        WHERE {universe_where}
          AND COALESCE(dgc.state, '') != ''
        GROUP BY UPPER(TRIM(COALESCE(dgc.state, '')))
        ORDER BY vehicle_count DESC, value
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT UPPER(TRIM(COALESCE(dgc.state, ''))) AS value
        FROM {available_from}
        LEFT JOIN dealer_geo_cache dgc ON dgc.dealer_cd = vr.dealer_cd
        WHERE {available_where}
          AND COALESCE(dgc.state, '') != ''
        """,
        available_params,
    ).fetchall()
    items = _merge_facet_rows(universe_rows, {row["value"] for row in available_rows})
    for item in items:
        item["available"] = True
    normalized_items: Dict[str, Dict] = {}
    for item in items:
        code = normalize_state_code(item.get("value") or "") or (item.get("value") or "")
        if not code:
            continue
        bucket = normalized_items.setdefault(
            code,
            {
                "value": code,
                "label": state_label(code),
                "vehicle_count": 0,
                "available": False,
            },
        )
        bucket["vehicle_count"] += int(item.get("vehicle_count") or 0)
        bucket["available"] = bucket["available"] or bool(item.get("available"))
    return sorted(
        normalized_items.values(),
        key=lambda row: (-int(row["vehicle_count"]), row["label"]),
    )


def _merge_facet_rows(
    universe_rows: List[Any],
    available_values: Set[str],
    label_key: Optional[str] = None,
) -> List[Dict]:
    items: List[Dict] = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available_values
        if label_key and payload.get(label_key):
            payload["label"] = payload[label_key]
        elif not payload.get("label"):
            payload["label"] = payload["value"]
        items.append(payload)
    return items


def _context_vehicle_count(
    conn: DbConnection, ctx: FilterContext) -> int:
    from_sql, where_sql, params = _build_vehicle_scope(ctx)
    row = conn.execute(
        f"SELECT COUNT(DISTINCT v.vin) AS total FROM {from_sql} WHERE {where_sql}",
        params,
    ).fetchone()
    return int(row["total"]) if row else 0


def _query_series_list(
    conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        FilterContext(active_only=ctx.active_only)    )
    available_from, available_where, available_params = _build_vehicle_scope(
        ctx, exclude="series"    )

    universe_rows = conn.execute(
        f"""
        SELECT
            v.series_code AS value,
            v.series_code,
            COALESCE(MAX(s.marketing_series), MAX(v.marketing_series), v.series_code) AS series_name,
            COUNT(DISTINCT v.vin) AS vehicle_count
        FROM {universe_from}
        LEFT JOIN series s ON s.series_code = v.series_code
        WHERE {universe_where}
        GROUP BY v.series_code
        ORDER BY series_name COLLATE NOCASE, v.series_code
        """,
        universe_params,
    ).fetchall()
    available_rows = conn.execute(
        f"""
        SELECT DISTINCT v.series_code AS value
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    ).fetchall()
    available = {row["value"] for row in available_rows}
    items: List[Dict] = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available
        items.append(payload)
    return items


def _materialize_filter_scopes(conn: DbConnection, ctx: FilterContext) -> None:
    universe_from, universe_where, universe_params = _build_vehicle_scope(
        _series_only_context(ctx)
    )
    available_from, available_where, available_params = _build_vehicle_scope(ctx)

    conn.execute("DROP TABLE IF EXISTS _filter_universe")
    conn.execute(
        f"""
        CREATE TEMPORARY TABLE _filter_universe AS
        SELECT
            v.vin,
            v.series_code,
            v.model_marketing_name,
            COALESCE(v.exterior_color_name, 'Unknown') AS exterior_color_name,
            v.exterior_color_hex,
            v.exterior_color_swatch,
            COALESCE(v.interior_color_name, 'Unknown') AS interior_color_name,
            v.interior_color_swatch,
            COALESCE(v.drivetrain_code, 'UNKNOWN') AS drivetrain_code,
            v.drivetrain_title,
            COALESCE(vr.allocation_stage_code, 'UNKNOWN') AS allocation_stage_code,
            COALESCE(vr.allocation_stage_label, 'Unknown') AS allocation_stage_label,
            vr.dealer_cd,
            UPPER(TRIM(COALESCE(dgc.state, ''))) AS dealer_state
        FROM {universe_from}
        LEFT JOIN dealer_geo_cache dgc ON dgc.dealer_cd = vr.dealer_cd
        WHERE {universe_where}
        """,
        universe_params,
    )
    ensure_index(
        conn,
        name="idx_filter_universe_vin",
        table="_filter_universe",
        columns="vin",
    )

    conn.execute("DROP TABLE IF EXISTS _filter_available")
    conn.execute(
        f"""
        CREATE TEMPORARY TABLE _filter_available AS
        SELECT DISTINCT v.vin
        FROM {available_from}
        WHERE {available_where}
        """,
        available_params,
    )
    ensure_index(
        conn,
        name="idx_filter_available_vin",
        table="_filter_available",
        columns="vin",
    )


def _available_values(conn: DbConnection, column_sql: str) -> Set[str]:
    rows = conn.execute(
        f"""
        SELECT DISTINCT {column_sql} AS value
        FROM _filter_universe fu
        JOIN _filter_available av ON av.vin = fu.vin
        WHERE {column_sql} IS NOT NULL AND {column_sql} != ''
        """
    ).fetchall()
    return {row["value"] for row in rows}


def _query_series_from_scope(conn: DbConnection, ctx: FilterContext) -> List[Dict]:
    return _query_series_list(conn, ctx)


def _query_model_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT fu.model_marketing_name AS value, COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        WHERE fu.model_marketing_name IS NOT NULL
        GROUP BY fu.model_marketing_name
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.model_marketing_name")
    return _merge_facet_rows(universe_rows, available)


def _query_exterior_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            fu.exterior_color_name AS value,
            MAX(fu.exterior_color_hex) AS exterior_color_hex,
            MAX(fu.exterior_color_swatch) AS exterior_color_swatch,
            COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        GROUP BY fu.exterior_color_name
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.exterior_color_name")
    items = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available
        items.append(payload)
    return items


def _query_interior_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            fu.interior_color_name AS value,
            MAX(fu.interior_color_swatch) AS interior_color_swatch,
            COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        GROUP BY fu.interior_color_name
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.interior_color_name")
    items = []
    for row in universe_rows:
        payload = dict(row)
        payload["available"] = payload["value"] in available
        items.append(payload)
    return items


def _query_drivetrain_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            fu.drivetrain_code AS value,
            MAX(fu.drivetrain_title) AS label,
            COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        GROUP BY fu.drivetrain_code
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.drivetrain_code")
    return _merge_facet_rows(universe_rows, available, label_key="label")


def _query_stage_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            fu.allocation_stage_code AS value,
            fu.allocation_stage_label AS label,
            COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        GROUP BY fu.allocation_stage_code, fu.allocation_stage_label
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.allocation_stage_code")
    return _merge_facet_rows(universe_rows, available, label_key="label")


def _query_option_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            o.option_cd AS value,
            o.marketing_name AS label,
            COUNT(DISTINCT fu.vin) AS vehicle_count
        FROM _filter_universe fu
        JOIN vehicle_options vo ON vo.vin = fu.vin
        JOIN options o ON o.option_cd = vo.option_cd
        GROUP BY o.option_cd, o.marketing_name
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    rows = conn.execute(
        """
        SELECT DISTINCT o.option_cd AS value
        FROM _filter_universe fu
        JOIN _filter_available av ON av.vin = fu.vin
        JOIN vehicle_options vo ON vo.vin = fu.vin
        JOIN options o ON o.option_cd = vo.option_cd
        """
    ).fetchall()
    available = {row["value"] for row in rows}
    return _merge_facet_rows(universe_rows, available, label_key="label")


def _query_dealer_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT
            fu.dealer_cd AS value,
            MAX(COALESCE(d.dealer_marketing_name, fu.dealer_cd)) AS label,
            COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        LEFT JOIN dealers d ON d.dealer_cd = fu.dealer_cd
        WHERE fu.dealer_cd IS NOT NULL
        GROUP BY fu.dealer_cd
        ORDER BY vehicle_count DESC, label
        """
    ).fetchall()
    available = _available_values(conn, "fu.dealer_cd")
    return _merge_facet_rows(universe_rows, available, label_key="label")


def _query_state_from_scope(conn: DbConnection) -> List[Dict]:
    universe_rows = conn.execute(
        """
        SELECT fu.dealer_state AS value, COUNT(*) AS vehicle_count
        FROM _filter_universe fu
        WHERE fu.dealer_state != ''
        GROUP BY fu.dealer_state
        ORDER BY vehicle_count DESC, value
        """
    ).fetchall()
    available = _available_values(conn, "fu.dealer_state")
    items = _merge_facet_rows(universe_rows, available)
    for item in items:
        item["available"] = True
    normalized_items: Dict[str, Dict] = {}
    for item in items:
        code = normalize_state_code(item.get("value") or "") or (item.get("value") or "")
        if not code:
            continue
        bucket = normalized_items.setdefault(
            code,
            {
                "value": code,
                "label": state_label(code),
                "vehicle_count": 0,
                "available": False,
            },
        )
        bucket["vehicle_count"] += int(item.get("vehicle_count") or 0)
        bucket["available"] = bucket["available"] or bool(item.get("available"))
    return sorted(
        normalized_items.values(),
        key=lambda row: (-int(row["vehicle_count"]), row["label"]),
    )


def _context_vehicle_count_from_scope(conn: DbConnection) -> int:
    row = conn.execute("SELECT COUNT(*) AS total FROM _filter_available").fetchone()
    return int(row["total"]) if row else 0


def build_filters_payload(conn: DbConnection, ctx: FilterContext) -> Dict:
    ensure_dealer_geo_cache_table(conn)

    latest_run_row = conn.execute("SELECT MAX(run_id) AS max_run_id FROM runs").fetchone()
    latest_run_id = latest_run_row["max_run_id"] if latest_run_row else None

    return {
        "series": _query_series_list(conn, ctx),
        "models": _query_model_facets(conn, ctx),
        "exterior_colors": _query_exterior_facets(conn, ctx),
        "interior_colors": _query_interior_facets(conn, ctx),
        "drivetrains": _query_drivetrain_facets(conn, ctx),
        "stages": _query_stage_facets(conn, ctx),
        "options": _query_option_facets(conn, ctx),
        "dealers": _query_dealer_facets(conn, ctx),
        "states": _query_state_facets(conn, ctx),
        "context_count": _context_vehicle_count(conn, ctx),
        "latest_run_id": latest_run_id,
    }
