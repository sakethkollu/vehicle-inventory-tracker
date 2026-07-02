from vehicle_inventory.geo.dealer_geo import parse_google_maps_coords


def test_parse_google_maps_coords_from_at_pattern():
    url = "https://www.google.com/maps/place/Toyota/@37.8044,-122.2712,14z"
    assert parse_google_maps_coords(url) == (37.8044, -122.2712)


def test_parse_google_maps_coords_from_data_pattern():
    url = "https://www.google.com/maps/place/x/data=!3d33.4484!4d-112.0740"
    assert parse_google_maps_coords(url) == (33.4484, -112.074)


def test_parse_google_maps_coords_from_center_json():
    html = '{"center":{"lat":34.0522,"lng":-118.2437}}'
    assert parse_google_maps_coords(html) == (34.0522, -118.2437)


def test_parse_google_maps_coords_returns_none_for_garbage():
    assert parse_google_maps_coords("") is None
    assert parse_google_maps_coords("no coordinates here") is None
