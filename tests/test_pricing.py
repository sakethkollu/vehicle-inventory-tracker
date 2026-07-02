from vehicle_inventory.api.pricing import (
    _distance_band_label,
    _float_price,
    _mean,
    _median,
    plain_text_from_html,
)


def test_plain_text_from_html_list_items():
    html = "<ul><li>Apple CarPlay</li><li>Heated seats</li></ul>"
    assert plain_text_from_html(html) == "Apple CarPlay; Heated seats"


def test_plain_text_from_html_strips_tags():
    assert plain_text_from_html("<p>Hello <strong>world</strong></p>") == "Hello world"


def test_plain_text_from_html_plain_string():
    assert plain_text_from_html("already plain") == "already plain"


def test_median_and_mean():
    assert _median([1, 2, 3, 4]) == 2.5
    assert _median([5]) == 5
    assert _median([]) is None
    assert _mean([2, 4, 6]) == 4.0
    assert _mean([]) is None


def test_float_price():
    assert _float_price("25999") == 25999.0
    assert _float_price(0) is None
    assert _float_price("bad") is None
    assert _float_price(None) is None


def test_distance_band_label():
    assert _distance_band_label(25) == "0-49 mi"
    assert _distance_band_label(75) == "50-99 mi"
    assert _distance_band_label(500) == "200+ mi"
    assert _distance_band_label(None) == "Unknown distance"
