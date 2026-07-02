import pytest

from vehicle_inventory.ingest.router import build_ingest_request, sync_make_catalog
from vehicle_inventory.ingest.types import IngestRequest


def test_build_ingest_request_dispatches_by_make(schema_path, test_database_url):
    toyota = build_ingest_request(
        "toyota",
        {"zip_code": "95132"},
        database_url=test_database_url,
        schema_path=schema_path,
    )
    mazda = build_ingest_request(
        "mazda",
        {"zip_code": "95101"},
        database_url=test_database_url,
        schema_path=schema_path,
    )
    assert isinstance(toyota, IngestRequest)
    assert toyota.zip_code == "95132"
    assert mazda.zip_code == "95101"
    assert mazda.page_size == 100


def test_sync_make_catalog_mazda(monkeypatch, schema_path, test_database_url):
    adapter_result = {"count": 2, "models": [{"model_code": "CX5"}, {"model_code": "C30"}]}

    class FakeAdapter:
        slug = "mazda"
        display_name = "Mazda"

        def supports_catalog_sync(self):
            return True

        def sync_catalog(self, **kwargs):
            assert kwargs["zip_code"] == "95101"
            assert kwargs["distance"] == 50
            return adapter_result

    monkeypatch.setattr(
        "vehicle_inventory.ingest.router.get_make_adapter",
        lambda slug: FakeAdapter(),
    )
    result = sync_make_catalog(
        "mazda",
        database_url=test_database_url,
        schema_path=schema_path,
        zip_code="95101",
        distance=50,
    )
    assert result["count"] == 2
