from pathlib import Path

import pytest

from vehicle_inventory.makes.mazda.adapter import MazdaAdapter
from vehicle_inventory.makes.toyota.adapter import ToyotaAdapter


@pytest.fixture
def schema_path(project_root):
    return project_root / "vehicle_inventory" / "db" / "schema_mysql.sql"


def test_toyota_adapter_build_ingest_request(schema_path, test_database_url):
    adapter = ToyotaAdapter()
    request = adapter.build_ingest_request(
        {"zip_code": "90210", "distance": 100, "all_models": True},
        database_url=test_database_url,
        schema_path=schema_path,
    )
    assert request.zip_code == "90210"
    assert request.distance == 100
    assert request.page_size == 250
    assert request.all_models is True
    assert adapter.requires_model_selection() is True
    assert adapter.supports_catalog_sync() is True
    assert ".toyota.com" in adapter.image_host_suffixes()


def test_mazda_adapter_build_ingest_request_defaults(schema_path, test_database_url):
    adapter = MazdaAdapter()
    request = adapter.build_ingest_request(
        {},
        database_url=test_database_url,
        schema_path=schema_path,
    )
    assert request.zip_code == "95101"
    assert request.distance == 50
    assert request.page_size == 100
    assert request.all_models is False
    assert adapter.requires_model_selection() is True
    assert adapter.supports_catalog_sync() is True


def test_mazda_adapter_all_models_false_when_model_codes_provided(schema_path, test_database_url):
    adapter = MazdaAdapter()
    request = adapter.build_ingest_request(
        {"model_codes": ["cx-5", "cx-30"]},
        database_url=test_database_url,
        schema_path=schema_path,
    )
    assert request.all_models is False
    assert request.model_codes == ["cx-5", "cx-30"]


def test_mazda_sync_catalog(monkeypatch, schema_path, test_database_url):
    adapter = MazdaAdapter()
    captured = {}

    class FakeClient:
        def validate_zip(self, zip_code):
            return True

        def fetch_dealers(self, zip_code, *, max_distance):
            captured["distance"] = max_distance
            captured["zip_code"] = zip_code
            from vehicle_inventory.makes.mazda.client import MazdaDealer

            return [
                MazdaDealer(
                    dealer_id=42004,
                    name="STEVENS CREEK MAZDA",
                    city="San Jose",
                    state="CA",
                    zip_code="95129",
                    distance_mi=9.0,
                    lat=37.32,
                    lon=-121.97,
                )
            ]

        def fetch_model_catalog(self, dealer_ids):
            from vehicle_inventory.makes.mazda.client import MazdaCatalogModel

            return [
                MazdaCatalogModel(
                    model_code="CX5",
                    title="MAZDA CX-5",
                    series="CX5",
                    year="2026",
                    image="https://example/cx5.png",
                    inventory_count=12,
                )
            ]

        def search_inventory(self, *args, **kwargs):
            return {"response": {"TotalVehicles": 0, "Vehicles": []}}

        def parse_vehicles(self, payload):
            return []

    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.adapter.MazdaInventoryClient",
        lambda *args, **kwargs: FakeClient(),
    )
    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.adapter.resolve_mazda_cookies",
        lambda: {},
    )

    class FakeDb:
        def __init__(self, *args, **kwargs):
            self.rows = None
            self.conn = object()

        def initialize(self):
            return None

        def upsert_dealer(self, dealer, ts):
            return None

        def upsert_model_catalog(self, rows, ts):
            self.rows = list(rows)

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("vehicle_inventory.makes.mazda.adapter.InventoryDb", FakeDb)
    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.ingest.ensure_dealer_geo_cache_table",
        lambda conn: None,
    )
    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.ingest.store_dealer_geo_coordinates",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.ingest._backfill_catalog_images_from_db",
        lambda db, models: None,
    )

    result = adapter.sync_catalog(
        database_url=test_database_url,
        schema_path=schema_path,
        zip_code="95101",
        distance=50,
        nationwide=False,
    )
    assert captured["distance"] == 50
    assert captured["zip_code"] == "95101"
    assert result["count"] == 1
    assert result["models"][0]["model_code"] == "CX5"
    assert result["models"][0]["top_label"] == "12 in dealer radius"
