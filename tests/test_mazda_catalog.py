from vehicle_inventory.makes.mazda.client import MazdaInventoryClient

SAMPLE_CATALOG_PAYLOAD = {
    "response": {
        "TotalVehicles": 100,
        "Filters": {
            "Models": [
                {
                    "Code": "CX5",
                    "Name": "MAZDA CX-5",
                    "Image": "https://www.mazdausa.com/siteassets/vehicles/2026/cx-5/profile.png",
                    "Count": 501,
                    "IsEnabled": True,
                },
                {
                    "Code": "C30",
                    "Name": "MAZDA CX-30",
                    "Image": "https://www.mazdausa.com/siteassets/vehicles/2026/cx-30/profile.png",
                    "Count": 150,
                    "IsEnabled": True,
                },
                {"Code": "", "Name": "ignored"},
            ]
        },
    }
}


def test_parse_catalog_models_extracts_mazda_models():
    models = MazdaInventoryClient.parse_catalog_models(SAMPLE_CATALOG_PAYLOAD)
    assert len(models) == 2
    cx5 = models[0]
    assert cx5.model_code == "CX5"
    assert cx5.title == "MAZDA CX-5"
    assert cx5.year == "2026"
    assert cx5.inventory_count == 501
    assert cx5.image.endswith("profile.png")


def test_parse_catalog_models_empty_payload():
    assert MazdaInventoryClient.parse_catalog_models({}) == []
