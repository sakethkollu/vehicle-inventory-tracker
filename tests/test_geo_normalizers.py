from vehicle_inventory.geo.dealer_geo import (
    expand_state_filter_values,
    normalize_state_code,
    normalize_us_zip,
    state_label,
    _is_preferred_geo_query,
)


def test_is_preferred_geo_query_excludes_oem_provisional():
    assert _is_preferred_geo_query("oem:Mazda of Irvine, CA 92618") is False
    assert _is_preferred_geo_query("website:https://example.com") is True
    assert _is_preferred_geo_query("95132, Irvine, CA") is False


def test_normalize_us_zip():
    assert normalize_us_zip("95132") == "95132"
    assert normalize_us_zip("95132-1234") == "95132"
    assert normalize_us_zip("abc") is None
    assert normalize_us_zip("") is None


def test_normalize_state_code():
    assert normalize_state_code("ca") == "CA"
    assert normalize_state_code("California") == "CA"
    assert normalize_state_code("XX") == "XX"
    assert normalize_state_code(None) is None


def test_state_label():
    assert state_label("CA") == "California"
    assert state_label("California") == "California"


def test_expand_state_filter_values_includes_code_and_name():
    values = expand_state_filter_values(["CA"])
    assert "CA" in values
    assert "California" in values


def test_expand_state_filter_values_accepts_full_name():
    values = expand_state_filter_values(["California"])
    assert "CA" in values
    assert "California" in values
