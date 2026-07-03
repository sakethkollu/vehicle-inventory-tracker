from unittest.mock import patch

from vehicle_inventory.api.filters import FilterContext, _filter_reference_coords
from vehicle_inventory.geo.dealer_geo import append_run_location_filters


def test_filter_reference_coords_prefers_search_zip_over_browser():
    ctx = FilterContext(
        search_zip="95132",
        reference_lat=37.0,
        reference_lng=-122.0,
    )
    with patch(
        "vehicle_inventory.api.filters.geocode_postal_code",
        return_value=(37.3352, -121.8811),
    ) as geocode:
        coords = _filter_reference_coords(ctx)

    geocode.assert_called_once_with("95132")
    assert coords == (37.3352, -121.8811)


def test_filter_reference_coords_falls_back_to_browser_when_zip_geocode_fails():
    ctx = FilterContext(
        search_zip="95132",
        reference_lat=37.0,
        reference_lng=-122.0,
    )
    with patch("vehicle_inventory.api.filters.geocode_postal_code", return_value=None):
        coords = _filter_reference_coords(ctx)

    assert coords == (37.0, -122.0)


def test_append_run_location_filters_uses_only_haversine_with_search_zip():
    where: list[str] = []
    params: list = []
    with patch(
        "vehicle_inventory.geo.dealer_geo.geocode_postal_code",
        return_value=(37.3352, -121.8811),
    ):
        append_run_location_filters(
            where,
            params,
            distance_max=10,
            search_zip="95132",
        )

    assert len(where) == 1
    # OEM ingest distance is intentionally NOT part of the filter when we have
    # search coordinates: vr.distance is relative to the ingest ZIP, not the
    # user's location.
    assert "vr.distance" not in where[0]
    assert "dealer_geo_cache" in where[0]
    assert params == [37.3352, -121.8811, 37.3352, 10]


def test_append_run_location_filters_falls_back_to_oem_distance_when_zip_geocode_fails():
    where: list[str] = []
    params: list = []
    with patch("vehicle_inventory.geo.dealer_geo.geocode_postal_code", return_value=None):
        append_run_location_filters(
            where,
            params,
            distance_max=10,
            search_zip="95132",
        )

    assert where == ["vr.distance IS NOT NULL AND vr.distance <= ?"]
    assert params == [10]


def test_dealer_display_distance_sql_uses_only_haversine():
    from vehicle_inventory.geo.dealer_geo import (
        dealer_display_distance_sql,
        normalize_dealer_display_distance,
    )

    expr = "3959.0 * acos(...)"
    sql = dealer_display_distance_sql(expr)
    assert sql.count(expr) == 1
    # vr.distance is intentionally excluded so we never show a fake proximity
    # (e.g. Mazda's per-dealer refresh stores distance=1 for every row).
    assert "vr.distance" not in sql
    assert normalize_dealer_display_distance(12.4) == 12.4
    assert normalize_dealer_display_distance(5642.0) is None
