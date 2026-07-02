from pathlib import Path

from vehicle_inventory.makes.mazda.ingest import (
    MazdaIngestSettings,
    _absolute_image_url,
    _estimate_carline_total,
    _estimated_total_pages,
    _pagination_should_stop,
    _pick_best_catalog_image_url,
    _slugify,
    _vehicle_payload,
    resolve_ingest_carlines,
    resolve_target_carlines,
)
from vehicle_inventory.makes.mazda.client import MazdaVehicle, MAZDA_ORIGIN


def test_slugify():
    assert _slugify("CX-5 Turbo") == "cx-5-turbo"
    assert _slugify("   ") == "unknown"


def test_absolute_image_url():
    assert _absolute_image_url("/images/a.png") == f"{MAZDA_ORIGIN}/images/a.png"
    assert _absolute_image_url("https://cdn.example/x.jpg") == "https://cdn.example/x.jpg"
    assert _absolute_image_url("") == ""
    assert (
        _absolute_image_url("https://www.mazdausa.com:443/siteassets/mx5.png")
        == "https://www.mazdausa.com/siteassets/mx5.png"
    )


def test_pick_best_catalog_image_url_prefers_profile_jellies():
    chosen = _pick_best_catalog_image_url(
        [
            "https://www.mazdausa.com/siteassets/vehicles/2026/mx-5-st/jellies/sport.png",
            "https://www.mazdausa.com/syssiteassets/vehicles/2026/mx-5-st/profile-jellies/profile.png",
        ]
    )
    assert "profile-jellies" in chosen


def test_vehicle_payload_maps_mazda_fields():
    vehicle = MazdaVehicle(
        vin="JM1TEST",
        carline="CX-5",
        price=32000.0,
        base_msrp=33000.0,
        year=2025,
        model_name="CX-5 Select",
        exterior_color="Red",
        interior_color="Black",
        dealer_id=99,
        details_url="/inventory/vehicle/2025/cx-5/details",
        image_url="/img.png",
        vehicle_location="01",
        status_code="06",
        eta_date="2026-07-17T00:00:00",
    )
    payload = _vehicle_payload(vehicle)
    assert payload["vin"] == "JM1TEST"
    assert payload["brand"] == "Mazda"
    assert payload["marketingSeries"] == "CX-5"
    assert payload["model"]["marketingName"] == "CX-5 Select"
    assert payload["dealerCategory"] == "01"
    assert payload["etaDate"] == "2026-07-17T00:00:00"
    assert payload["dealerCd"] == "99"
    assert payload["vdpUrl"].startswith(MAZDA_ORIGIN)
    assert payload["price"]["advertizedPrice"] == 32000.0


def test_resolve_target_carlines_all_models():
    settings = MazdaIngestSettings(
        database_url="sqlite:///:memory:",
        schema_path=Path("unused"),
        all_models=True,
    )

    class FakeDb:
        def list_model_catalog(self):
            return []

    assert resolve_target_carlines(settings, client=None, db=FakeDb(), ts="now") is None


def test_resolve_target_carlines_requires_catalog():
    settings = MazdaIngestSettings(
        database_url="sqlite:///:memory:",
        schema_path=Path("unused"),
        all_models=False,
        model_codes=["CX5"],
    )

    class FakeDb:
        def list_model_catalog(self):
            return []

    try:
        resolve_target_carlines(settings, client=None, db=FakeDb(), ts="now")
    except RuntimeError as exc:
        assert "Model catalog is empty" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_resolve_ingest_carlines_all_models():
    settings = MazdaIngestSettings(
        database_url="sqlite:///:memory:",
        schema_path=Path("unused"),
        all_models=True,
    )

    class FakeDb:
        def list_model_catalog(self):
            return [
                {"model_code": "CX5", "title": "MAZDA CX-5"},
                {"model_code": "50H", "title": "MAZDA CX-50 HYBRID"},
            ]

    assert resolve_ingest_carlines(settings, FakeDb()) == ["CX5", "50H"]


def test_estimate_carline_total_prefers_api_total():
    assert _estimate_carline_total(813, 382) == 813
    assert _estimate_carline_total(960, 378) == 960
    assert _estimate_carline_total(72, 378) == 72
    assert _estimate_carline_total(0, 150) == 150


def test_estimated_total_pages():
    assert _estimated_total_pages(72, 12) == 6
    assert _estimated_total_pages(813, 12) == 68
    assert _estimated_total_pages(0, 12) == 1


def test_pagination_should_stop_uses_api_total_not_catalog():
    page_size = 12
    estimated_total = 813
    total_pages = _estimated_total_pages(estimated_total, page_size)
    assert total_pages == 68

    # Mid-run: keep going.
    assert not _pagination_should_stop(
        vehicles_on_page=12,
        new_on_page=12,
        model_saved=382,
        estimated_total=estimated_total,
        page_no=32,
        total_pages=total_pages,
        page_size=page_size,
    )

    # Last full page.
    assert _pagination_should_stop(
        vehicles_on_page=12,
        new_on_page=12,
        model_saved=813,
        estimated_total=estimated_total,
        page_no=68,
        total_pages=total_pages,
        page_size=page_size,
    )

    # Short final page (50H ends with 9 vehicles on page 68).
    assert _pagination_should_stop(
        vehicles_on_page=9,
        new_on_page=9,
        model_saved=809,
        estimated_total=estimated_total,
        page_no=68,
        total_pages=total_pages,
        page_size=page_size,
    )
