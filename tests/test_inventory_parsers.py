from werkzeug.datastructures import ImmutableMultiDict

from vehicle_inventory.api.filters import FilterContext, parse_filter_context
from vehicle_inventory.api.inventory import (
    InventoryFilters,
    compute_histogram,
    compute_numeric_stats,
    parse_inventory_filters,
    rows_to_items,
)
from vehicle_inventory.db.backend import DbRow


def test_parse_inventory_filters_defaults():
    args = ImmutableMultiDict([])
    filters = parse_inventory_filters(args)
    assert filters.page == 1
    assert filters.page_size == 20
    assert filters.active_only is True
    assert filters.sort_key == "advertized_price"


def test_parse_inventory_filters_parses_lists_and_zip():
    args = ImmutableMultiDict(
        [
            ("series_codes", "camry,rav4"),
            ("model_marketing_names", "Camry SE"),
            ("drivetrain_codes", "awd, fwd"),
            ("search_zip", "95132-1234"),
            ("page_size", "50"),
            ("sort_dir", "desc"),
            ("active_only", "0"),
        ]
    )
    filters = parse_inventory_filters(args)
    assert filters.series_codes == ["camry", "rav4"]
    assert filters.model_values == ["Camry SE"]
    assert filters.drivetrain_codes == ["AWD", "FWD"]
    assert filters.search_zip == "95132"
    assert filters.page_size == 50
    assert filters.active_only is False


def test_parse_inventory_filters_caps_page_size():
    args = ImmutableMultiDict([("page_size", "999")])
    filters = parse_inventory_filters(args)
    assert filters.page_size == 100


def test_parse_inventory_filters_vin_list_allows_larger_page_size():
    args = ImmutableMultiDict([("vins", "ABC123"), ("page_size", "150")])
    filters = parse_inventory_filters(args)
    assert filters.page_size == 150


def test_parse_filter_context():
    args = ImmutableMultiDict(
        [
            ("series_code", "camry"),
            ("state_codes", "ca, nv"),
            ("reference_lat", "37.4"),
            ("reference_lng", "-121.8"),
            ("distance_max", "100"),
        ]
    )
    ctx = parse_filter_context(args)
    assert isinstance(ctx, FilterContext)
    assert ctx.series_codes == ["camry"]
    assert ctx.state_codes == ["CA", "NV"]
    assert ctx.reference_lat == 37.4
    assert ctx.distance_max == 100


def test_rows_to_items():
    rows = [DbRow({"vin": "1"}), DbRow({"vin": "2"})]
    items = rows_to_items(rows)
    assert items == [{"vin": "1"}, {"vin": "2"}]


def test_compute_numeric_stats():
    stats = compute_numeric_stats([10, 20, 30])
    assert stats == {
        "min": 10,
        "max": 30,
        "avg": 20.0,
        "median": 20,
        "count": 3,
    }
    assert compute_numeric_stats([]) is None


def test_compute_histogram():
    hist = compute_histogram([10, 20, 30, 40, 50, 60])
    assert hist is not None
    assert len(hist["bins"]) >= 8
    assert hist["min"] == 10
    assert hist["max"] == 60
    assert compute_histogram([1, 2]) is None
