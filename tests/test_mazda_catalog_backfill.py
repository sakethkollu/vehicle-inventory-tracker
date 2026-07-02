from vehicle_inventory.makes.mazda.client import MazdaCatalogModel, MazdaInventoryClient
from vehicle_inventory.makes.mazda.ingest import _backfill_catalog_images


def test_backfill_catalog_images_uses_first_vehicle_image():
    models = [
        MazdaCatalogModel(
            model_code="CX5",
            title="MAZDA CX-5",
            series="CX5",
            inventory_count=12,
            image=None,
        )
    ]

    class FakeClient:
        def search_inventory(self, dealer_ids, *, results_start, page_size, carlines):
            assert carlines == ["CX5"]
            assert page_size == 12
            return {"response": {"Vehicles": [{"Vin": "VIN1", "ImagesListInfo": [{"Url": "/img/cx5.png"}]}]}}

        def parse_vehicles(self, payload):
            client = MazdaInventoryClient.__new__(MazdaInventoryClient)
            return client.parse_vehicles(payload)

    _backfill_catalog_images(FakeClient(), [1, 2], models)
    assert models[0].image == "https://www.mazdausa.com/img/cx5.png"


def test_backfill_catalog_images_skips_models_with_image():
    models = [
        MazdaCatalogModel(
            model_code="CX5",
            title="MAZDA CX-5",
            series="CX5",
            inventory_count=12,
            image="https://example.com/existing.png",
        )
    ]

    class FakeClient:
        def search_inventory(self, *args, **kwargs):
            raise AssertionError("should not search when image already present")

    _backfill_catalog_images(FakeClient(), [1], models)
    assert models[0].image == "https://example.com/existing.png"
