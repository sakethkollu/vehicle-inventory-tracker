import re
from dataclasses import replace
from html import unescape
from typing import Dict, List, Optional, Sequence, Tuple

from vehicle_inventory.db.backend import DbConnection

from vehicle_inventory.api.inventory import InventoryFilters, build_inventory_query, compute_numeric_stats


def plain_text_from_html(value: Optional[str]) -> str:
    if not value:
        return ""
    if "<" not in value:
        return value.strip()
    list_items = re.findall(r"<li[^>]*>(.*?)</li>", value, flags=re.IGNORECASE | re.DOTALL)
    if list_items:
        cleaned = [
            re.sub(r"<[^>]+>", "", unescape(item)).strip()
            for item in list_items
        ]
        return "; ".join(item for item in cleaned if item)
    text = re.sub(r"<[^>]+>", " ", value)
    return unescape(re.sub(r"\s+", " ", text)).strip()


DISTANCE_BANDS: List[Tuple[int, int, str]] = [
    (0, 50, "0-49 mi"),
    (50, 100, "50-99 mi"),
    (100, 200, "100-199 mi"),
    (200, 10_000, "200+ mi"),
]

MIN_MODEL_SAMPLES = 3
MIN_OPTION_SAMPLES = 12
MIN_DEALER_SAMPLES = 5
MIN_MSRP_TRIM_SAMPLES = 3
MIN_MSRP_SUMMARY_SAMPLES = 1
MSRP_MATCH_TOLERANCE = 1.0


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    sorted_values = sorted(values)
    mid = len(sorted_values) // 2
    if len(sorted_values) % 2 == 0:
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2
    return sorted_values[mid]


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _distance_band_label(distance: Optional[int]) -> str:
    if distance is None:
        return "Unknown distance"
    for low, high, label in DISTANCE_BANDS:
        if low <= distance < high:
            return label
    return "Unknown distance"


def _float_price(value) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coalesce_sale_price(row: Dict) -> Optional[float]:
    for key in ("price", "advertized_price", "non_sp_advertized_price"):
        value = _float_price(row.get(key))
        if value is not None:
            return value
    return None


def _coalesce_msrp(row: Dict) -> Optional[float]:
    for key in ("msrp", "total_msrp", "base_msrp"):
        value = _float_price(row.get(key))
        if value is not None:
            return value
    return None


def _price_row_from_scoped(row: Dict) -> Dict:
    return {
        "vin": row.get("vin"),
        "model_marketing_name": row.get("model_marketing_name"),
        "drivetrain_code": row.get("drivetrain_code"),
        "grade": row.get("grade"),
        "price": row.get("price"),
        "msrp": row.get("msrp"),
        "dealer_cd": row.get("dealer_cd"),
        "dealer_marketing_name": row.get("dealer_marketing_name"),
        "distance": row.get("distance"),
    }


def _inventory_item_to_price_row(item: Dict) -> Dict:
    return {
        "vin": item.get("vin"),
        "model_marketing_name": item.get("model_marketing_name"),
        "drivetrain_code": item.get("drivetrain_code"),
        "grade": item.get("grade"),
        "price": _coalesce_sale_price(item),
        "msrp": _coalesce_msrp(item),
        "dealer_cd": item.get("dealer_cd"),
        "dealer_marketing_name": item.get("dealer_marketing_name"),
        "distance": item.get("distance"),
    }


def _scoped_price_sql(filters: InventoryFilters) -> Tuple[str, List]:
    from vehicle_inventory.api.inventory import (
        _distance_select_sql,
        _inventory_scope,
        _resolve_search_coords,
    )

    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        filters,
        include_wheels=False,
    )
    distance_expr, distance_params = _distance_select_sql(
        _resolve_search_coords(filters.search_zip)
    )
    sql = f"""
        SELECT
            v.vin,
            v.model_marketing_name,
            v.drivetrain_code,
            v.grade,
            COALESCE(p.advertized_price, p.non_sp_advertized_price) AS price,
            COALESCE(p.total_msrp, p.base_msrp) AS msrp,
            vr.dealer_cd,
            {distance_expr} AS distance,
            d.dealer_marketing_name
        {from_sql}
        WHERE {where_sql}
        {group_sql}
        {option_having}
    """
    return sql, [*distance_params, *params]


def _pick_metric(rows: List[Dict]) -> Tuple[str, List[float]]:
    advertised = [float(row["price"]) for row in rows if row.get("price") is not None]
    msrp = [float(row["msrp"]) for row in rows if row.get("msrp") is not None]
    if len(advertised) >= MIN_MODEL_SAMPLES:
        return "advertized_price", advertised
    if len(msrp) >= MIN_MODEL_SAMPLES:
        return "total_msrp", [float(row["msrp"]) for row in rows if row.get("msrp") is not None]
    return "advertized_price", advertised


def _price_value(row: Dict, metric: str) -> Optional[float]:
    raw = row.get("price") if metric == "advertized_price" else row.get("msrp")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _group_stats(
    rows: List[Dict],
    metric: str,
    key_fn,
    baseline_median: float,
    min_samples: int,
) -> List[Dict]:
    buckets: Dict[str, List[float]] = {}
    meta: Dict[str, Dict] = {}
    for row in rows:
        price = _price_value(row, metric)
        if price is None:
            continue
        key, payload = key_fn(row)
        if not key:
            continue
        buckets.setdefault(key, []).append(price)
        meta.setdefault(key, payload)

    items: List[Dict] = []
    for key, prices in buckets.items():
        if len(prices) < min_samples:
            continue
        stats = compute_numeric_stats(prices)
        if not stats:
            continue
        median_price = stats["median"]
        items.append(
            {
                **meta[key],
                "count": stats["count"],
                "median_price": median_price,
                "avg_price": stats["avg"],
                "min_price": stats["min"],
                "max_price": stats["max"],
                "delta_vs_baseline": median_price - baseline_median,
            }
        )
    items.sort(key=lambda item: (item["median_price"], -item["count"]))
    return items


def _fetch_option_membership_for_scope(
    conn: DbConnection, filters: InventoryFilters
) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    from dataclasses import replace

    from vehicle_inventory.api.inventory import _inventory_scope

    scoped_filters = replace(filters, option_codes=[])
    from_sql, where_sql, params, group_sql, option_having, _option_join = _inventory_scope(
        scoped_filters,
        include_wheels=False,
    )
    rows = conn.execute(
        f"""
        SELECT vo.vin, vo.option_cd, o.marketing_name
        FROM vehicle_options vo
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE vo.vin IN (
            SELECT v.vin
            {from_sql}
            WHERE {where_sql}
            {group_sql}
            {option_having}
        )
        ORDER BY vo.option_cd
        """,
        params,
    ).fetchall()
    membership: Dict[str, List[str]] = {}
    option_names: Dict[str, str] = {}
    for row in rows:
        membership.setdefault(row["vin"], []).append(row["option_cd"])
        if row["marketing_name"]:
            option_names[row["option_cd"]] = plain_text_from_html(row["marketing_name"])
    return membership, option_names


def _fetch_option_membership(
    conn: DbConnection, vins: List[str]
) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    if not vins:
        return {}, {}
    placeholders = ",".join("?" for _ in vins)
    rows = conn.execute(
        f"""
        SELECT vo.vin, vo.option_cd, o.marketing_name
        FROM vehicle_options vo
        JOIN options o ON o.option_cd = vo.option_cd
        WHERE vo.vin IN ({placeholders})
        ORDER BY vo.option_cd
        """,
        vins,
    ).fetchall()
    membership: Dict[str, List[str]] = {}
    option_names: Dict[str, str] = {}
    for row in rows:
        membership.setdefault(row["vin"], []).append(row["option_cd"])
        if row["marketing_name"]:
            option_names[row["option_cd"]] = plain_text_from_html(row["marketing_name"])
    return membership, option_names


def _option_impact_rows(
    rows: List[Dict],
    metric: str,
    baseline_median: float,
    membership: Dict[str, List[str]],
    option_names: Dict[str, str],
) -> List[Dict]:
    from collections import defaultdict

    option_prices: Dict[str, List[float]] = defaultdict(list)
    priced_entries: List[float] = []
    for row in rows:
        price = _price_value(row, metric)
        if price is None:
            continue
        priced_entries.append(price)
        for option_cd in membership.get(row.get("vin"), []):
            option_prices[option_cd].append(price)

    if len(priced_entries) < MIN_OPTION_SAMPLES:
        return []

    total_count = len(priced_entries)
    total_sum = sum(priced_entries)
    overall_avg = total_sum / total_count if total_count else baseline_median

    impacts: List[Dict] = []
    for option_cd in sorted(option_prices.keys()):
        with_prices = option_prices[option_cd]
        count_with = len(with_prices)
        count_without = total_count - count_with
        if count_with < MIN_OPTION_SAMPLES or count_without < MIN_OPTION_SAMPLES:
            continue
        sum_with = sum(with_prices)
        avg_with = sum_with / count_with
        avg_without = (total_sum - sum_with) / count_without
        median_with = _median(with_prices)
        if median_with is None:
            continue
        impacts.append(
            {
                "option_cd": option_cd,
                "marketing_name": plain_text_from_html(option_names.get(option_cd) or option_cd),
                "count_with": count_with,
                "count_without": count_without,
                "avg_with": avg_with,
                "avg_without": avg_without,
                "median_with": median_with,
                "delta_vs_without": avg_with - avg_without,
                "delta_vs_baseline": avg_with - overall_avg,
            }
        )

    impacts.sort(key=lambda item: (item["delta_vs_without"], -item["count_with"]))
    return impacts


def _trim_key(row: Dict) -> Tuple[str, Dict]:
    model = row.get("model_marketing_name") or "Unknown"
    grade = row.get("grade") or "-"
    drive = row.get("drivetrain_code") or "-"
    key = f"{model}|{grade}|{drive}"
    return key, {
        "trim_label": f"{grade} {model} ({drive})",
        "model_marketing_name": model,
        "grade": grade,
        "drivetrain_code": drive,
    }


def _priced_msrp_rows(rows: List[Dict]) -> List[Dict]:
    priced: List[Dict] = []
    for row in rows:
        price = _coalesce_sale_price(row)
        msrp = _coalesce_msrp(row)
        if price is None or msrp is None:
            continue
        delta = price - msrp
        priced.append(
            {
                **row,
                "_price": price,
                "_msrp": msrp,
                "_delta": delta,
                "_delta_pct": (delta / msrp) * 100,
            }
        )
    return priced


def _vehicle_msrp_snapshot(row: Dict) -> Dict:
    return {
        "vin": row.get("vin") or "",
        "trim_label": _trim_key(row)[1]["trim_label"],
        "model_marketing_name": row.get("model_marketing_name") or "Unknown",
        "grade": row.get("grade") or "-",
        "drivetrain_code": row.get("drivetrain_code") or "-",
        "dealer_marketing_name": row.get("dealer_marketing_name") or row.get("dealer_cd") or "-",
        "sale_price": row["_price"],
        "msrp": row["_msrp"],
        "delta": row["_delta"],
        "delta_pct": row["_delta_pct"],
    }


def _build_msrp_comparison(rows: List[Dict]) -> Optional[Dict]:
    priced_rows = _priced_msrp_rows(rows)
    if len(priced_rows) < MIN_MSRP_SUMMARY_SAMPLES:
        return None

    all_deltas = [row["_delta"] for row in priced_rows]
    all_pcts = [row["_delta_pct"] for row in priced_rows]
    below_rows = [row for row in priced_rows if row["_delta"] < -MSRP_MATCH_TOLERANCE]
    above_rows = [row for row in priced_rows if row["_delta"] > MSRP_MATCH_TOLERANCE]
    at_msrp_count = len(priced_rows) - len(below_rows) - len(above_rows)

    buckets: Dict[str, Dict] = {}
    for row in priced_rows:
        key, meta = _trim_key(row)
        bucket = buckets.setdefault(
            key,
            {
                **meta,
                "deltas": [],
                "pcts": [],
                "prices": [],
                "msrps": [],
            },
        )
        bucket["deltas"].append(row["_delta"])
        bucket["pcts"].append(row["_delta_pct"])
        bucket["prices"].append(row["_price"])
        bucket["msrps"].append(row["_msrp"])

    trim_items: List[Dict] = []
    for bucket in buckets.values():
        if len(bucket["deltas"]) < MIN_MSRP_TRIM_SAMPLES:
            continue
        avg_delta = _mean(bucket["deltas"])
        avg_delta_pct = _mean(bucket["pcts"])
        if avg_delta is None or avg_delta_pct is None:
            continue
        below_count = sum(1 for delta in bucket["deltas"] if delta < -MSRP_MATCH_TOLERANCE)
        above_count = sum(1 for delta in bucket["deltas"] if delta > MSRP_MATCH_TOLERANCE)
        trim_items.append(
            {
                "trim_label": bucket["trim_label"],
                "model_marketing_name": bucket["model_marketing_name"],
                "grade": bucket["grade"],
                "drivetrain_code": bucket["drivetrain_code"],
                "count": len(bucket["deltas"]),
                "avg_sale_price": _mean(bucket["prices"]),
                "avg_msrp": _mean(bucket["msrps"]),
                "avg_delta": avg_delta,
                "avg_delta_pct": avg_delta_pct,
                "median_delta": _median(bucket["deltas"]),
                "below_msrp_count": below_count,
                "above_msrp_count": above_count,
                "below_msrp_pct": (below_count / len(bucket["deltas"])) * 100,
            }
        )

    trims_below = sorted(
        [item for item in trim_items if item["avg_delta"] < 0],
        key=lambda item: (item["avg_delta"], -item["count"]),
    )
    trims_above = sorted(
        [item for item in trim_items if item["avg_delta"] > 0],
        key=lambda item: (item["avg_delta"], -item["count"]),
        reverse=True,
    )

    vehicles_most_below = [
        _vehicle_msrp_snapshot(row)
        for row in sorted(priced_rows, key=lambda item: item["_delta"])[:8]
        if row["_delta"] < 0
    ]
    vehicles_most_above = [
        _vehicle_msrp_snapshot(row)
        for row in sorted(priced_rows, key=lambda item: item["_delta"], reverse=True)[:8]
        if row["_delta"] > 0
    ]

    avg_delta = _mean(all_deltas)
    avg_delta_pct = _mean(all_pcts)
    if avg_delta is None or avg_delta_pct is None:
        return None

    return {
        "summary": {
            "vehicle_count": len(priced_rows),
            "avg_sale_price": _mean([row["_price"] for row in priced_rows]),
            "avg_msrp": _mean([row["_msrp"] for row in priced_rows]),
            "avg_delta": avg_delta,
            "median_delta": _median(all_deltas),
            "avg_delta_pct": avg_delta_pct,
            "below_msrp_count": len(below_rows),
            "above_msrp_count": len(above_rows),
            "at_msrp_count": max(0, at_msrp_count),
            "below_msrp_pct": (len(below_rows) / len(priced_rows)) * 100,
        },
        "trims_below_msrp": trims_below[:15],
        "trims_above_msrp": trims_above[:15],
        "vehicles_most_below": vehicles_most_below,
        "vehicles_most_above": vehicles_most_above,
    }


def _insights_with_msrp(rows: List[Dict]) -> Dict:
    payload = _empty_insights()
    payload["msrp_comparison"] = _build_msrp_comparison(rows)
    return payload


def build_pricing_insights_from_rows(
    rows: List[Dict],
    membership: Optional[Dict[str, List[str]]] = None,
    option_names: Optional[Dict[str, str]] = None,
) -> Dict:
    if not rows:
        return _insights_with_msrp(rows)

    metric, baseline_values = _pick_metric(rows)
    baseline_stats = compute_numeric_stats(baseline_values)
    if not baseline_stats:
        return _insights_with_msrp(rows)

    baseline_median = baseline_stats["median"]
    priced_rows = [row for row in rows if _price_value(row, metric) is not None]
    if len(priced_rows) < MIN_MODEL_SAMPLES:
        return _insights_with_msrp(rows)

    models = _group_stats(
        priced_rows,
        metric,
        key_fn=lambda row: (
            f"{row.get('model_marketing_name') or 'Unknown'}|{row.get('drivetrain_code') or '-'}",
            {
                "model_marketing_name": row.get("model_marketing_name") or "Unknown",
                "drivetrain_code": row.get("drivetrain_code") or "-",
                "grade": row.get("grade") or "-",
            },
        ),
        baseline_median=baseline_median,
        min_samples=MIN_MODEL_SAMPLES,
    )

    distance_bands = _group_stats(
        priced_rows,
        metric,
        key_fn=lambda row: (
            _distance_band_label(row.get("distance")),
            {"label": _distance_band_label(row.get("distance"))},
        ),
        baseline_median=baseline_median,
        min_samples=MIN_MODEL_SAMPLES,
    )
    distance_order = {label: index for index, (_, _, label) in enumerate(DISTANCE_BANDS)}
    distance_bands.sort(
        key=lambda item: (distance_order.get(item["label"], 99), item["median_price"])
    )

    dealers = _group_stats(
        priced_rows,
        metric,
        key_fn=lambda row: (
            row.get("dealer_cd") or "",
            {
                "dealer_cd": row.get("dealer_cd") or "",
                "dealer_marketing_name": row.get("dealer_marketing_name") or row.get("dealer_cd") or "Unknown",
            },
        ),
        baseline_median=baseline_median,
        min_samples=MIN_DEALER_SAMPLES,
    )

    options: List[Dict] = []
    if membership is not None and option_names is not None:
        options = _option_impact_rows(
            priced_rows,
            metric,
            baseline_median,
            membership,
            option_names,
        )

    return {
        "metric": metric,
        "metric_label": "Advertised Price" if metric == "advertized_price" else "MSRP",
        "baseline": baseline_stats,
        "msrp_comparison": _build_msrp_comparison(rows),
        "models": models[:15],
        "options": options[:20],
        "distance_bands": distance_bands,
        "dealers_below_baseline": [d for d in dealers if d["delta_vs_baseline"] < 0][:12],
        "dealers_above_baseline": sorted(
            [d for d in dealers if d["delta_vs_baseline"] > 0],
            key=lambda item: item["delta_vs_baseline"],
            reverse=True,
        )[:12],
        "notes": [
            "Sale vs MSRP compares advertised price to total MSRP for vehicles with both values.",
            "Trim averages require at least 3 listings with both advertised price and MSRP.",
            "Deltas compare median or average price within your current filters.",
            "Option effects are correlational: an option may appear on cheaper trims rather than causing a lower price.",
            "Distance bands are miles from the ingestion search ZIP, not vehicle location precision.",
        ],
    }


def _empty_insights() -> Dict:
    return {
        "metric": "advertized_price",
        "metric_label": "Advertised Price",
        "baseline": None,
        "msrp_comparison": _build_msrp_comparison([]),
        "models": [],
        "options": [],
        "distance_bands": [],
        "dealers_below_baseline": [],
        "dealers_above_baseline": [],
        "notes": [],
    }


def build_msrp_comparison_for_filters(
    conn: DbConnection, filters: InventoryFilters
) -> Optional[Dict]:
    from vehicle_inventory.api.inventory import fetch_inventory_rows, rows_to_items

    db_rows = fetch_inventory_rows(conn, filters)
    items = rows_to_items(db_rows)
    rows = [_inventory_item_to_price_row(item) for item in items]
    return _build_msrp_comparison(rows)


def build_pricing_insights(
    conn: DbConnection, filters: InventoryFilters
) -> Dict:
    insight_filters = replace(filters, option_codes=[])
    sql, params = _scoped_price_sql(insight_filters)
    db_rows = conn.execute(sql, params).fetchall()
    rows = [dict(row) for row in db_rows]
    vins = [row["vin"] for row in rows if row.get("vin")]
    membership, option_names = _fetch_option_membership(conn, vins)
    payload = build_pricing_insights_from_rows(rows, membership, option_names)
    payload["msrp_comparison"] = _build_msrp_comparison(
        [_price_row_from_scoped(row) for row in rows]
    )
    return payload


def build_pricing_insights_from_items(items: List[Dict]) -> Dict:
    rows = [_inventory_item_to_price_row(item) for item in items]
    membership: Dict[str, List[str]] = {}
    option_names: Dict[str, str] = {}
    for item in items:
        vin = item.get("vin")
        if not vin:
            continue
        opts = item.get("options") or []
        membership[vin] = [opt.get("option_cd") for opt in opts if opt.get("option_cd")]
        for opt in opts:
            code = opt.get("option_cd")
            if code and opt.get("marketing_name"):
                option_names[code] = plain_text_from_html(opt["marketing_name"])
    return build_pricing_insights_from_rows(rows, membership, option_names)
