import csv
import io
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from vehicle_inventory.db.backend import DbConnection, DbRow, fetchall_with_retry, fetchone_with_retry
from vehicle_inventory.geo.dealer_geo import (
    append_run_location_filters,
    geocode_postal_code,
    normalize_us_zip,
)
from vehicle_inventory.db.run_scope import vehicle_runs_latest_join
from vehicle_inventory.db.sql_compat import ensure_index, haversine_miles_sql


INVENTORY_SELECT = """
    v.vin,
    v.series_code,
    v.marketing_series,
    v.grade,
    v.model_marketing_name,
    v.year,
    vr.dealer_cd,
    vr.stock_num,
    d.dealer_marketing_name,
    d.dealer_website,
    vr.inventory_status,
    vr.allocation_stage_code,
    vr.allocation_stage_label,
    {distance_select} AS distance,
    vr.vdp_url,
    dgc.postal_code AS dealer_postal_code,
    dgc.city AS dealer_city,
    dgc.state AS dealer_state,
    p.advertized_price,
    p.total_msrp,
    p.base_msrp,
    wheels.wheel_options,
    v.exterior_color_name,
    v.exterior_color_hex,
    v.exterior_color_swatch,
    v.interior_color_name,
    v.interior_color_swatch,
    v.drivetrain_code,
    v.drivetrain_title,
    v.last_seen_at
"""

WHEELS_JOIN = """
    LEFT JOIN (
        SELECT
            vo.vin,
            GROUP_CONCAT(o.marketing_name, ' | ') AS wheel_options
        FROM vehicle_options vo
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE LOWER(COALESCE(o.marketing_name, '')) LIKE '%wheel%'
           OR LOWER(COALESCE(o.marketing_name, '')) LIKE '%inch%'
        GROUP BY vo.vin
    ) wheels ON wheels.vin = v.vin
"""

INVENTORY_GROUP = """
    GROUP BY
        v.vin,
        v.series_code,
        v.marketing_series,
        v.grade,
        v.model_marketing_name,
        v.year,
        vr.dealer_cd,
        vr.stock_num,
        d.dealer_marketing_name,
        d.dealer_website,
        vr.inventory_status,
        vr.allocation_stage_code,
        vr.allocation_stage_label,
        vr.vdp_url,
        dgc.postal_code,
        dgc.city,
        dgc.state,
        dgc.latitude,
        dgc.longitude,
        p.advertized_price,
        p.total_msrp,
        p.base_msrp,
        wheels.wheel_options,
        v.exterior_color_name,
        v.exterior_color_hex,
        v.exterior_color_swatch,
        v.interior_color_name,
        v.interior_color_swatch,
        v.drivetrain_code,
        v.drivetrain_title,
        v.last_seen_at
"""

INVENTORY_ORDER = """
    ORDER BY
        (p.advertized_price IS NULL) ASC,
        p.advertized_price ASC,
        (distance IS NULL) ASC,
        distance ASC
"""

SORTABLE_INVENTORY_COLUMNS: Dict[str, str] = {
    "vin": "v.vin",
    "stock_num": "vr.stock_num",
    "year": "v.year",
    "marketing_series": "COALESCE(v.marketing_series, v.series_code)",
    "grade": "v.grade",
    "model_marketing_name": "v.model_marketing_name",
    "drivetrain_code": "COALESCE(v.drivetrain_code, v.drivetrain_title)",
    "dealer_marketing_name": "COALESCE(d.dealer_marketing_name, vr.dealer_cd)",
    "allocation_stage_code": "COALESCE(vr.allocation_stage_label, vr.allocation_stage_code)",
    "advertized_price": "COALESCE(p.advertized_price, p.non_sp_advertized_price)",
    "total_msrp": "COALESCE(p.total_msrp, p.base_msrp)",
    "msrp_delta": (
        "(COALESCE(NULLIF(p.advertized_price, 0), NULLIF(p.non_sp_advertized_price, 0)) "
        "- COALESCE(NULLIF(p.total_msrp, 0), NULLIF(p.base_msrp, 0)))"
    ),
    # Sorted via the aliased distance expression built from the user's search ZIP.
    "distance": "distance",
    "exterior_color_name": "v.exterior_color_name",
    "interior_color_name": "v.interior_color_name",
}


def _resolve_search_coords(search_zip: Optional[str]) -> Optional[Tuple[float, float]]:
    normalized = normalize_us_zip(search_zip or "")
    if not normalized:
        return None
    return geocode_postal_code(normalized)


def _distance_select_sql(
    search_coords: Optional[Tuple[float, float]],
) -> Tuple[str, List]:
    """Return the SQL expression + params for the user-relative distance column.

    Distance is the haversine miles between the user's search ZIP and the
    dealer's geocoded coordinates. If either is missing the column is NULL.
    """
    if search_coords is None:
        return "NULL", []
    miles = haversine_miles_sql("?", "?")
    expr = (
        f"MIN(CASE WHEN dgc.latitude IS NOT NULL AND dgc.longitude IS NOT NULL "
        f"THEN ({miles}) END)"
    )
    lat, lng = search_coords
    return expr, [lat, lng, lat]


@dataclass
class InventoryFilters:
    series_codes: List[str] = field(default_factory=list)
    filter_mode: str = "none"
    grade_values: List[str] = field(default_factory=list)
    model_values: List[str] = field(default_factory=list)
    vin_query: str = ""
    stock_query: str = ""
    vins: List[str] = field(default_factory=list)
    stage_codes: List[str] = field(default_factory=list)
    exterior_colors: List[str] = field(default_factory=list)
    interior_colors: List[str] = field(default_factory=list)
    drivetrain_codes: List[str] = field(default_factory=list)
    distance_max: Optional[int] = None
    distance_min: Optional[int] = None
    search_zip: Optional[str] = None
    state_codes: List[str] = field(default_factory=list)
    active_only: bool = True
    option_codes: List[str] = field(default_factory=list)
    dealer_codes: List[str] = field(default_factory=list)
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    price_metric: str = "advertized_price"
    page: int = 1
    page_size: int = 20
    sort_key: str = "advertized_price"
    sort_dir: str = "asc"


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


def parse_inventory_filters(args) -> InventoryFilters:
    price_min_raw = args.get("price_min", "").strip()
    price_max_raw = args.get("price_max", "").strip()
    price_metric = args.get("price_metric", "advertized_price").strip() or "advertized_price"
    if price_metric not in {"advertized_price", "total_msrp"}:
        price_metric = "advertized_price"
    vins = [x.strip().upper() for x in args.get("vins", "").split(",") if x.strip()]
    page_size_raw = max(int(args.get("page_size", "20") or 20), 1)
    max_page_size = 200 if vins else 100
    return InventoryFilters(
        series_codes=_parse_series_codes(args),
        filter_mode=args.get("filter_mode", "none").strip() or "none",
        grade_values=[x.strip() for x in args.get("grade_values", "").split(",") if x.strip()],
        model_values=[
            x.strip() for x in args.get("model_marketing_names", "").split(",") if x.strip()
        ],
        vin_query=args.get("vin_query", "").strip().upper(),
        stock_query=args.get("stock_query", "").strip().upper(),
        stage_codes=[x.strip().upper() for x in args.get("stage_codes", "").split(",") if x.strip()],
        exterior_colors=[x.strip() for x in args.get("exterior_colors", "").split(",") if x.strip()],
        interior_colors=[x.strip() for x in args.get("interior_colors", "").split(",") if x.strip()],
        drivetrain_codes=[
            x.strip().upper() for x in args.get("drivetrain_codes", "").split(",") if x.strip()
        ],
        distance_max=_parse_int_arg(args, "distance_max"),
        distance_min=_parse_int_arg(args, "distance_min"),
        search_zip=normalize_us_zip(args.get("search_zip", "").strip()),
        state_codes=[
            x.strip().upper() for x in args.get("state_codes", "").split(",") if x.strip()
        ],
        active_only=args.get("active_only", "1") == "1",
        option_codes=[x.strip() for x in args.get("option_codes", "").split(",") if x.strip()],
        dealer_codes=[x.strip() for x in args.get("dealer_codes", "").split(",") if x.strip()],
        price_min=float(price_min_raw) if price_min_raw else None,
        price_max=float(price_max_raw) if price_max_raw else None,
        price_metric=price_metric,
        vins=vins,
        page=max(int(args.get("page", "1") or 1), 1),
        page_size=min(page_size_raw, max_page_size),
        sort_key=_parse_sort_key(args.get("sort_key", "advertized_price")),
        sort_dir=_parse_sort_dir(args.get("sort_dir", "asc")),
    )


def _parse_sort_key(raw: str) -> str:
    key = (raw or "advertized_price").strip()
    return key if key in SORTABLE_INVENTORY_COLUMNS else "advertized_price"


def _parse_sort_dir(raw: str) -> str:
    direction = (raw or "asc").strip().lower()
    return direction if direction in {"asc", "desc"} else "asc"


def _inventory_order_clause(filters: InventoryFilters) -> str:
    expr = SORTABLE_INVENTORY_COLUMNS.get(_parse_sort_key(filters.sort_key))
    if not expr:
        return INVENTORY_ORDER
    direction = _parse_sort_dir(filters.sort_dir)
    if direction == "desc":
        return f"ORDER BY ({expr} IS NULL) ASC, {expr} DESC, v.vin ASC"
    return f"ORDER BY ({expr} IS NULL) ASC, {expr} ASC, v.vin ASC"


def _append_inventory_filters(
    where: List[str],
    params: List,
    filters: InventoryFilters,
) -> None:
    if filters.series_codes:
        placeholders = ",".join("?" for _ in filters.series_codes)
        where.append(f"v.series_code IN ({placeholders})")
        params.extend(filters.series_codes)
    if filters.filter_mode == "grade" and filters.grade_values:
        placeholders = ",".join("?" for _ in filters.grade_values)
        where.append(f"v.grade IN ({placeholders})")
        params.extend(filters.grade_values)
    elif filters.filter_mode == "model" and filters.model_values:
        placeholders = ",".join("?" for _ in filters.model_values)
        where.append(f"v.model_marketing_name IN ({placeholders})")
        params.extend(filters.model_values)
    if filters.vin_query:
        where.append("v.vin LIKE ?")
        params.append(f"%{filters.vin_query}%")
    if filters.vins:
        placeholders = ",".join("?" for _ in filters.vins)
        where.append(f"v.vin IN ({placeholders})")
        params.extend(filters.vins)
    if filters.stock_query:
        where.append("COALESCE(vr.stock_num, '') LIKE ?")
        params.append(f"%{filters.stock_query}%")
    if filters.stage_codes:
        placeholders = ",".join("?" for _ in filters.stage_codes)
        where.append(f"COALESCE(vr.allocation_stage_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(filters.stage_codes)
    if filters.exterior_colors:
        placeholders = ",".join("?" for _ in filters.exterior_colors)
        where.append(f"COALESCE(v.exterior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(filters.exterior_colors)
    if filters.interior_colors:
        placeholders = ",".join("?" for _ in filters.interior_colors)
        where.append(f"COALESCE(v.interior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(filters.interior_colors)
    if filters.drivetrain_codes:
        placeholders = ",".join("?" for _ in filters.drivetrain_codes)
        where.append(f"COALESCE(v.drivetrain_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(filters.drivetrain_codes)
    if filters.dealer_codes:
        placeholders = ",".join("?" for _ in filters.dealer_codes)
        where.append(f"vr.dealer_cd IN ({placeholders})")
        params.extend(filters.dealer_codes)
    append_run_location_filters(
        where,
        params,
        distance_max=filters.distance_max,
        distance_min=filters.distance_min,
        state_codes=filters.state_codes,
        search_zip=filters.search_zip,
    )
    if filters.active_only:
        where.append("v.is_active = 1")
    if filters.price_min is not None:
        where.append(f"p.{filters.price_metric} >= ?")
        params.append(filters.price_min)
    if filters.price_max is not None:
        where.append(f"p.{filters.price_metric} <= ?")
        params.append(filters.price_max)


def _inventory_scope(
    filters: InventoryFilters,
    *,
    include_wheels: bool = False,
) -> Tuple[str, str, List, str, str, str]:
    run_join, run_params = vehicle_runs_latest_join(filters.series_codes or None)
    where: List[str] = []
    params: List = list(run_params)
    _append_inventory_filters(where, params, filters)

    option_join = ""
    option_having = ""
    group_sql = ""
    if filters.option_codes:
        placeholders = ",".join("?" for _ in filters.option_codes)
        option_join = f"""
        JOIN vehicle_options vo ON vo.vin = v.vin
        AND vo.option_cd IN ({placeholders})
        """
        params.extend(filters.option_codes)
        group_sql = INVENTORY_GROUP
        option_having = "HAVING COUNT(DISTINCT vo.option_cd) = ?"
        params.append(len(filters.option_codes))

    wheels_sql = WHEELS_JOIN if include_wheels else ""
    from_sql = f"""
        FROM vehicles v
        {run_join}
        JOIN vehicle_prices p ON p.vin = v.vin AND p.run_id = vr.run_id
        LEFT JOIN dealers d ON d.dealer_cd = vr.dealer_cd
        LEFT JOIN dealer_geo_cache dgc ON dgc.dealer_cd = vr.dealer_cd
        {wheels_sql}
        {option_join}
    """
    where_sql = " AND ".join(where) if where else "1=1"
    return from_sql, where_sql, params, group_sql, option_having, option_join


def build_inventory_query(
    filters: InventoryFilters,
) -> Tuple[str, List, str, str]:
    """Legacy helper retained for pricing queries built with JOIN ... ON filters."""
    from_sql, where_sql, params, group_sql, option_having, option_join = _inventory_scope(filters)
    del from_sql, group_sql
    return where_sql, params, option_join, option_having


def _inventory_select(
    *,
    include_wheels: bool,
    distance_select: str,
) -> str:
    wheel_expr = "wheels.wheel_options" if include_wheels else "NULL AS wheel_options"
    select = INVENTORY_SELECT.replace("wheels.wheel_options", wheel_expr)
    return select.format(distance_select=distance_select)


def _inventory_sql(
    filters: InventoryFilters,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Tuple[str, List]:
    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        filters,
        include_wheels=False,
    )
    distance_expr, distance_params = _distance_select_sql(
        _resolve_search_coords(filters.search_zip)
    )
    select_sql = _inventory_select(include_wheels=False, distance_select=distance_expr)
    sql = f"""
        SELECT {select_sql}
        {from_sql}
        WHERE {where_sql}
        {group_sql}
        {option_having}
        {_inventory_order_clause(filters)}
    """
    combined_params = [*distance_params, *params]
    if limit is not None:
        sql += " LIMIT ?"
        combined_params.append(limit)
    if offset is not None:
        sql += " OFFSET ?"
        combined_params.append(offset)
    return sql, combined_params


def fetch_inventory_rows(
    conn: DbConnection,
    filters: InventoryFilters,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> List[DbRow]:
    sql, params = _inventory_sql(filters, limit=limit, offset=offset)
    return fetchall_with_retry(conn, sql, params)


def count_inventory_rows(
    conn: DbConnection, filters: InventoryFilters
) -> int:
    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        filters,
        include_wheels=False,
    )
    if group_sql:
        row = fetchone_with_retry(
            conn,
            f"""
            SELECT COUNT(*) AS total FROM (
                SELECT v.vin
                {from_sql}
                WHERE {where_sql}
                {group_sql}
                {option_having}
            ) scoped
            """,
            params,
        )
    else:
        row = fetchone_with_retry(
            conn,
            f"""
            SELECT COUNT(*) AS total
            {from_sql}
            WHERE {where_sql}
            """,
            params,
        )
    return int(row["total"]) if row else 0


def _price_sql_expr(metric: str) -> str:
    if metric == "advertized_price":
        return "COALESCE(p.advertized_price, p.non_sp_advertized_price)"
    if metric == "total_msrp":
        return "COALESCE(p.total_msrp, p.base_msrp)"
    return f"p.{metric}"


def fetch_price_values(
    conn: DbConnection,
    filters: InventoryFilters,
    metric: str,
) -> List[float]:
    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        filters,
        include_wheels=False,
    )
    price_expr = _price_sql_expr(metric)
    rows = fetchall_with_retry(
        conn,
        f"""
        SELECT {price_expr} AS price_value
        {from_sql}
        WHERE {where_sql}
        {group_sql}
        {option_having}
        """,
        params,
    )
    values: List[float] = []
    for row in rows:
        value = row["price_value"]
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def attach_wheels(conn: DbConnection, items: List[Dict]) -> None:
    vins = [item["vin"] for item in items if item.get("vin")]
    if not vins:
        return
    placeholders = ",".join("?" for _ in vins)
    rows = conn.execute(
        f"""
        SELECT
            vo.vin,
            GROUP_CONCAT(o.marketing_name, ' | ') AS wheel_options
        FROM vehicle_options vo
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE vo.vin IN ({placeholders})
          AND (
            LOWER(COALESCE(o.marketing_name, '')) LIKE '%wheel%'
            OR LOWER(COALESCE(o.marketing_name, '')) LIKE '%inch%'
          )
        GROUP BY vo.vin
        """,
        vins,
    ).fetchall()
    wheel_map = {row["vin"]: row["wheel_options"] for row in rows}
    for item in items:
        item["wheel_options"] = wheel_map.get(item["vin"])


def attach_options(conn: DbConnection, items: List[Dict]) -> None:
    vins = [item["vin"] for item in items if item.get("vin")]
    options_map: Dict[str, List[Dict]] = {vin: [] for vin in vins}
    if not vins:
        return
    placeholders = ",".join("?" for _ in vins)
    option_rows = conn.execute(
        f"""
        SELECT vo.vin, o.option_cd, o.marketing_name
        FROM vehicle_options vo
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE vo.vin IN ({placeholders})
        ORDER BY vo.vin, o.option_cd
        """,
        vins,
    ).fetchall()
    for option_row in option_rows:
        options_map[option_row["vin"]].append(
            {
                "option_cd": option_row["option_cd"],
                "marketing_name": option_row["marketing_name"],
            }
        )
    for item in items:
        item["options"] = options_map.get(item["vin"], [])


def rows_to_items(rows: List[DbRow]) -> List[Dict]:
    return [dict(row) for row in rows]


def compute_numeric_stats(values: List[float]) -> Optional[Dict]:
    if not values:
        return None
    sorted_values = sorted(values)
    count = len(sorted_values)
    total = sum(sorted_values)
    mid = count // 2
    if count % 2 == 0:
        median = (sorted_values[mid - 1] + sorted_values[mid]) / 2
    else:
        median = sorted_values[mid]
    return {
        "min": sorted_values[0],
        "max": sorted_values[-1],
        "avg": total / count,
        "median": median,
        "count": count,
    }


def compute_histogram(values: List[float], bins: int = 16) -> Optional[Dict]:
    if len(values) < 3:
        return None
    minimum = min(values)
    maximum = max(values)
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std_dev = math.sqrt(max(variance, 1.0))
    bucket_count = max(8, min(24, bins))
    span = max(maximum - minimum, 1.0)
    step = span / bucket_count
    counts = [0] * bucket_count
    for value in values:
        index = min(bucket_count - 1, int((value - minimum) / step))
        counts[index] += 1
    bucket_rows = []
    for index, count in enumerate(counts):
        start = minimum + index * step
        end = maximum if index == bucket_count - 1 else minimum + (index + 1) * step
        bucket_rows.append({"start": start, "end": end, "count": count})
    return {
        "bins": bucket_rows,
        "min": minimum,
        "max": maximum,
        "mean": mean,
        "std_dev": std_dev,
        "max_bin_count": max(counts) if counts else 0,
    }


def build_vehicle_filter_sql(filters: InventoryFilters) -> Tuple[str, List]:
    where = ["1=1"]
    params: List = []
    if filters.series_codes:
        placeholders = ",".join("?" for _ in filters.series_codes)
        where.append(f"v.series_code IN ({placeholders})")
        params.extend(filters.series_codes)
    if filters.filter_mode == "grade" and filters.grade_values:
        placeholders = ",".join("?" for _ in filters.grade_values)
        where.append(f"v.grade IN ({placeholders})")
        params.extend(filters.grade_values)
    elif filters.filter_mode == "model" and filters.model_values:
        placeholders = ",".join("?" for _ in filters.model_values)
        where.append(f"v.model_marketing_name IN ({placeholders})")
        params.extend(filters.model_values)
    if filters.vin_query:
        where.append("v.vin LIKE ?")
        params.append(f"%{filters.vin_query}%")
    if filters.exterior_colors:
        placeholders = ",".join("?" for _ in filters.exterior_colors)
        where.append(f"COALESCE(v.exterior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(filters.exterior_colors)
    if filters.interior_colors:
        placeholders = ",".join("?" for _ in filters.interior_colors)
        where.append(f"COALESCE(v.interior_color_name, 'Unknown') IN ({placeholders})")
        params.extend(filters.interior_colors)
    if filters.drivetrain_codes:
        placeholders = ",".join("?" for _ in filters.drivetrain_codes)
        where.append(f"COALESCE(v.drivetrain_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(filters.drivetrain_codes)
    run_exists_filters: List[str] = []
    run_exists_params: List = []
    if filters.dealer_codes:
        placeholders = ",".join("?" for _ in filters.dealer_codes)
        run_exists_filters.append(f"vr.dealer_cd IN ({placeholders})")
        run_exists_params.extend(filters.dealer_codes)
    append_run_location_filters(
        run_exists_filters,
        run_exists_params,
        distance_max=filters.distance_max,
        distance_min=filters.distance_min,
        state_codes=filters.state_codes,
        search_zip=filters.search_zip,
    )
    if run_exists_filters:
        where.append(
            f"""
            EXISTS (
                SELECT 1
                FROM vehicle_runs vr
                WHERE vr.vin = v.vin
                  AND {" AND ".join(run_exists_filters)}
            )
            """
        )
        params.extend(run_exists_params)
    if filters.active_only:
        where.append("v.is_active = 1")
    if filters.option_codes:
        placeholders = ",".join("?" for _ in filters.option_codes)
        where.append(
            f"""
            (
                SELECT COUNT(DISTINCT vo.option_cd)
                FROM vehicle_options vo
                WHERE vo.vin = v.vin AND vo.option_cd IN ({placeholders})
            ) = ?
            """
        )
        params.extend(filters.option_codes)
        params.append(len(filters.option_codes))
    return " AND ".join(where), params


def _vehicle_run_filter_clauses(filters: InventoryFilters) -> Tuple[str, List]:
    clauses: List[str] = []
    params: List = []
    if filters.stage_codes:
        placeholders = ",".join("?" for _ in filters.stage_codes)
        clauses.append(f"COALESCE(vr.allocation_stage_code, 'UNKNOWN') IN ({placeholders})")
        params.extend(filters.stage_codes)
    if filters.stock_query:
        clauses.append("COALESCE(vr.stock_num, '') LIKE ?")
        params.append(f"%{filters.stock_query}%")
    if filters.dealer_codes:
        placeholders = ",".join("?" for _ in filters.dealer_codes)
        clauses.append(f"vr.dealer_cd IN ({placeholders})")
        params.extend(filters.dealer_codes)
    location_filters: List[str] = []
    location_params: List = []
    append_run_location_filters(
        location_filters,
        location_params,
        distance_max=filters.distance_max,
        distance_min=filters.distance_min,
        state_codes=filters.state_codes,
        search_zip=filters.search_zip,
    )
    clauses.extend(location_filters)
    params.extend(location_params)
    if not clauses:
        return "", params
    return "AND " + " AND ".join(clauses), params


EFFECTIVE_SALE_SQL = (
    "COALESCE(NULLIF(p.advertized_price, 0), NULLIF(p.non_sp_advertized_price, 0))"
)
EFFECTIVE_MSRP_SQL = "COALESCE(NULLIF(p.total_msrp, 0), NULLIF(p.base_msrp, 0))"
MSRP_DELTA_SQL = f"({EFFECTIVE_SALE_SQL} - {EFFECTIVE_MSRP_SQL})"
HAS_MSRP_PRICES_SQL = f"{EFFECTIVE_SALE_SQL} IS NOT NULL AND {EFFECTIVE_MSRP_SQL} IS NOT NULL"
HAS_MSRP_PRICES_SCOPED = "sale_price IS NOT NULL AND msrp_price IS NOT NULL"


def _geo_scoped_subquery(filters: InventoryFilters) -> Tuple[str, List]:
    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        filters,
        include_wheels=False,
    )
    sql = f"""
        SELECT
            v.vin,
            vr.dealer_cd,
            COALESCE(d.dealer_marketing_name, vr.dealer_cd) AS dealer_name,
            UPPER(TRIM(COALESCE(dgc.state, ''))) AS state_code,
            dgc.latitude,
            dgc.longitude,
            {EFFECTIVE_SALE_SQL} AS sale_price,
            {EFFECTIVE_MSRP_SQL} AS msrp_price,
            {MSRP_DELTA_SQL} AS msrp_delta
        {from_sql}
        WHERE {where_sql}
        {group_sql}
        {option_having}
    """
    return sql, params


def _materialize_geo_scope(conn: DbConnection, filters: InventoryFilters) -> None:
    scoped_sql, params = _geo_scoped_subquery(filters)
    conn.execute("DROP TABLE IF EXISTS _geo_scoped")
    conn.execute(f"CREATE TEMPORARY TABLE _geo_scoped AS {scoped_sql}", params)
    ensure_index(
        conn,
        name="idx_geo_scoped_state",
        table="_geo_scoped",
        columns="state_code(2)",
    )
    ensure_index(
        conn,
        name="idx_geo_scoped_dealer",
        table="_geo_scoped",
        columns="dealer_cd",
    )


def fetch_inventory_geo_map(
    conn: DbConnection, filters: InventoryFilters
) -> Dict:
    _materialize_geo_scope(conn, filters)

    summary_row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS vehicle_count,
            SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) AS mapped_count,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} THEN 1 ELSE 0 END) AS priced_count,
            SUM(
                CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta < 0 THEN 1 ELSE 0 END
            ) AS below_msrp_count,
            SUM(
                CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta > 0 THEN 1 ELSE 0 END
            ) AS above_msrp_count
        FROM _geo_scoped
        """
    ).fetchone()

    state_rows = conn.execute(
        f"""
        SELECT
            state_code,
            COUNT(*) AS vehicle_count,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} THEN 1 ELSE 0 END) AS priced_count,
            AVG(CASE WHEN {HAS_MSRP_PRICES_SCOPED} THEN msrp_delta END) AS avg_msrp_delta,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta < 0 THEN 1 ELSE 0 END) AS below_msrp_count,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta > 0 THEN 1 ELSE 0 END) AS above_msrp_count
        FROM _geo_scoped
        WHERE state_code != ''
        GROUP BY state_code
        ORDER BY vehicle_count DESC, state_code
        """
    ).fetchall()

    dealer_rows = conn.execute(
        f"""
        SELECT
            dealer_cd,
            dealer_name,
            state_code,
            latitude,
            longitude,
            COUNT(*) AS vehicle_count,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} THEN 1 ELSE 0 END) AS priced_count,
            AVG(CASE WHEN {HAS_MSRP_PRICES_SCOPED} THEN msrp_delta END) AS avg_msrp_delta,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta < 0 THEN 1 ELSE 0 END) AS below_msrp_count,
            SUM(CASE WHEN {HAS_MSRP_PRICES_SCOPED} AND msrp_delta > 0 THEN 1 ELSE 0 END) AS above_msrp_count
        FROM _geo_scoped
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        GROUP BY dealer_cd, dealer_name, state_code, latitude, longitude
        ORDER BY vehicle_count DESC, dealer_name
        LIMIT 400
        """
    ).fetchall()

    def _row_dict(row: DbRow) -> Dict:
        payload = dict(row)
        for key in ("avg_msrp_delta", "latitude", "longitude", "sale_price", "msrp_price", "msrp_delta"):
            if key in payload and payload[key] is not None:
                payload[key] = float(payload[key])
        return payload

    summary = dict(summary_row) if summary_row else {}
    for key in ("vehicle_count", "mapped_count", "priced_count", "below_msrp_count", "above_msrp_count"):
        summary[key] = int(summary.get(key) or 0)
    summary["unmapped_count"] = max(
        0, summary["vehicle_count"] - summary["mapped_count"]
    )

    return {
        "summary": summary,
        "states": [_row_dict(row) for row in state_rows],
        "dealers": [_row_dict(row) for row in dealer_rows],
    }


def build_analytics_payload(
    conn: DbConnection, filters: InventoryFilters
) -> Dict:
    from dataclasses import replace

    from vehicle_inventory.api.pricing import (
        _build_msrp_comparison,
        _fetch_option_membership_for_scope,
        _price_row_from_scoped,
        _scoped_price_sql,
        build_pricing_insights_from_rows,
    )

    insight_filters = replace(filters, option_codes=[])
    sql, params = _scoped_price_sql(insight_filters)
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    advertised_values: List[float] = []
    msrp_values: List[float] = []
    for row in rows:
        price = row.get("price")
        msrp = row.get("msrp")
        if price is not None:
            try:
                advertised_values.append(float(price))
            except (TypeError, ValueError):
                pass
        if msrp is not None:
            try:
                msrp_values.append(float(msrp))
            except (TypeError, ValueError):
                pass

    metric_key = "advertized_price"
    metric_values = advertised_values
    metric_label = "Advertised Price"
    if len(metric_values) < 3 and len(msrp_values) >= 3:
        metric_key = "total_msrp"
        metric_values = msrp_values
        metric_label = "MSRP"

    membership, option_names = _fetch_option_membership_for_scope(conn, insight_filters)
    insights = build_pricing_insights_from_rows(rows, membership, option_names)
    insights["msrp_comparison"] = _build_msrp_comparison(
        [_price_row_from_scoped(row) for row in rows]
    )

    total_count = count_inventory_rows(conn, filters) if filters.option_codes else len(rows)
    histogram = compute_histogram(metric_values)
    return {
        "total_count": total_count,
        "advertized_price": compute_numeric_stats(advertised_values),
        "total_msrp": compute_numeric_stats(msrp_values),
        "histogram": {
            **(histogram or {}),
            "metric": metric_key,
            "metric_label": metric_label,
        }
        if histogram
        else None,
        "insights": insights,
    }


CSV_EXPORT_COLUMNS: List[Tuple[str, str, Optional[Callable[[Dict], object]]]] = [
    ("vin", "VIN", None),
    ("stock_num", "Stock #", None),
    ("year", "Year", None),
    ("marketing_series", "Series", None),
    ("series_code", "Series Code", None),
    ("grade", "Grade", None),
    ("model_marketing_name", "Model", None),
    ("drivetrain_code", "Drivetrain Code", None),
    ("drivetrain_title", "Drivetrain", None),
    ("dealer_cd", "Dealer Code", None),
    ("dealer_marketing_name", "Dealer", None),
    ("allocation_stage_code", "Stage Code", None),
    ("allocation_stage_label", "Stage", None),
    ("advertized_price", "Advertised Price", None),
    ("total_msrp", "MSRP", None),
    ("base_msrp", "Base MSRP", None),
    ("wheel_options", "Wheels", None),
    ("distance", "Distance (mi)", None),
    ("exterior_color_name", "Exterior Color", None),
    ("interior_color_name", "Interior Color", None),
    ("inventory_status", "Inventory Status", None),
    ("vdp_url", "Listing URL", None),
    ("dealer_website", "Dealer Website", None),
    ("last_seen_at", "Last Seen", None),
    ("options", "Options", lambda item: _format_options_for_csv(item.get("options") or [])),
]


def _format_options_for_csv(options: List[Dict]) -> str:
    from vehicle_inventory.api.pricing import plain_text_from_html

    parts: List[str] = []
    for opt in options:
        code = opt.get("option_cd") or ""
        name = plain_text_from_html(opt.get("marketing_name") or "")
        parts.append(f"{code} - {name}".strip(" -") if code or name else "")
    return " | ".join(part for part in parts if part)


def build_inventory_csv(items: List[Dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for _, label, _ in CSV_EXPORT_COLUMNS])
    for item in items:
        row = []
        for key, _, formatter in CSV_EXPORT_COLUMNS:
            if formatter is not None:
                value = formatter(item)
            else:
                value = item.get(key)
            if value is None:
                row.append("")
            else:
                row.append(value)
        writer.writerow(row)
    return output.getvalue()
