from vehicle_inventory.makes.mazda.client import MazdaInventoryClient

SAMPLE_DETAIL = {
    "body": {
        "vehicle": {
            "vin": "7MMVAABW6TN178738",
            "carlineName": "CX-50 Hybrid",
            "dealerId": "42004",
            "dealerSiteUrl": "https://www.stevenscreekmazda.com/inventory/new-2026-mazda-cx-50-hybrid-preferred-awd-suv-7mmvaabw6tn178738/",
            "trimName": "Hybrid Preferred",
            "modelTitle": "MAZDA CX-50 HYBRID",
            "vehicleCode": "2650H",
            "year": "2026",
            "transmission": "Automatic",
            "engine": "2.5L Hybrid SKYACTIV-G 4-cyl",
            "drivetrain": "AWD",
            "status": "In-stock",
            "msrp": 36370,
            "baseMSRP": 34750,
            "destinationFee": 1495,
            "extColor": {"code": "48B", "description": "Ingot Blue Metallic", "price": 0},
            "intColor": {"code": "V_VA5", "description": "Black Leatherette with Gray", "price": 0},
            "engineFuelType": {"code": "EHB", "title": "Hybrid", "price": 0},
            "images": {
                "colorSwatch": "https://www.mazdausa.com/siteassets/vehicles/interior-swatches/mazda-interiorswatch-blackleatherette.png",
                "vehicle": [
                    "https://www.mazdausa.com/siteassets/vehicles/exterior.png",
                ],
            },
            "interiorColorSwatch": "https://www.mazdausa.com/siteassets/vehicles/interior-swatches/mazda-interiorswatch-blackleatherette.png",
            "location": {"Code": "02", "EtaDate": None},
            "accessories": [{"code": "CGM", "description": None, "name": "CARGO MAT", "price": 125}],
            "packages": [{"code": "1PF", "description": None, "name": "PREFERRED", "options": None, "price": 0}],
        }
    },
    "header": {"status": "success"},
}


def test_parse_detail_options_extracts_accessories_and_packages():
    options = MazdaInventoryClient.parse_detail_options(SAMPLE_DETAIL)
    codes = {option["optionCd"] for option in options}
    assert codes == {"CGM", "1PF"}
    accessory = next(option for option in options if option["optionCd"] == "CGM")
    assert accessory["marketingName"] == "CARGO MAT"
    assert accessory["optionType"] == "accessory"
    assert accessory["packageInd"] is False
    assert "$125" in accessory["marketingLongName"]
    package = next(option for option in options if option["optionCd"] == "1PF")
    assert package["optionType"] == "package"
    assert package["packageInd"] is True


def test_enrich_vehicle_payload_merges_detail_fields():
    base = {
        "vin": "7MMVAABW6TN178738",
        "brand": "Mazda",
        "grade": "CX-50 2.5 S Select",
        "model": {"modelCd": "cx-50", "marketingName": "Old Name"},
        "extColor": {"marketingName": "Blue"},
        "intColor": {"marketingName": "Black"},
        "dealerWebsite": "http://www.stevenscreekmazda.com/",
        "price": {"advertizedPrice": 32000, "baseMsrp": 32000, "totalMsrp": 32000},
    }
    enriched = MazdaInventoryClient.enrich_vehicle_payload(base, SAMPLE_DETAIL)
    assert enriched["grade"] == "Hybrid Preferred"
    assert enriched["marketingSeries"] == "CX-50 Hybrid"
    assert enriched["model"]["marketingName"] == "CX-50 Hybrid · Hybrid Preferred"
    assert enriched["drivetrain"]["title"] == "AWD"
    assert enriched["fuelType"]["name"] == "Hybrid"
    assert enriched["dealerCd"] == "42004"
    assert enriched["dealerWebsite"] == "http://www.stevenscreekmazda.com/"
    assert enriched["vdpUrl"].startswith("https://www.stevenscreekmazda.com/inventory/")
    assert "7mmvaabw6tn178738" in enriched["vdpUrl"].lower()
    assert enriched["price"]["totalMsrp"] == 36370
    assert enriched["price"]["dph"] == 1495
    assert enriched["extColor"]["marketingName"] == "Ingot Blue Metallic"
    assert enriched["extColor"]["colorHexCd"] == "4d7fa6"
    assert "colorSwatch" not in enriched["extColor"]
    assert enriched["intColor"]["colorSwatch"].endswith("blackleatherette.png")
    assert enriched["dealerCategory"] == "02"
    assert len(enriched["options"]) == 2
    assert len(enriched["media"]) == 1
    assert enriched["media"][0]["type"] == "exterior"


def test_detail_referer_builds_absolute_inventory_url():
    from vehicle_inventory.makes.mazda.client import MazdaVehicle

    vehicle = MazdaVehicle(
        vin="7MMVAABW6TN178738",
        carline="CX-50 Hybrid",
        price=None,
        base_msrp=None,
        year=2026,
        model_name="Hybrid Preferred",
        exterior_color="",
        interior_color="",
        dealer_id=42004,
        details_url="/shopping-tools/inventory/new/2026-mazda-cx-50-hybrid?vin=7MMVAABW6TN178738",
        image_url="",
    )
    referer = MazdaInventoryClient.detail_referer(vehicle)
    assert referer.startswith("https://www.mazdausa.com/")
    assert "cx-50-hybrid" in referer


def test_compose_mazda_listing_url_from_details_path():
    from vehicle_inventory.makes.mazda.client import compose_mazda_listing_url

    url = compose_mazda_listing_url(
        details_url="/shopping-tools/inventory/new/2026-mazda-cx-50-hybrid?vin=7MMVAABW6TN178738"
    )
    assert url == (
        "https://www.mazdausa.com/shopping-tools/inventory/new/"
        "2026-mazda-cx-50-hybrid?vin=7MMVAABW6TN178738"
    )


def test_compose_mazda_listing_url_falls_back_to_vin_search():
    from vehicle_inventory.makes.mazda.client import compose_mazda_listing_url

    url = compose_mazda_listing_url(vin="7MMVAABW6TN178738")
    assert url == (
        "https://www.mazdausa.com/shopping-tools/inventory/results?vin=7MMVAABW6TN178738"
    )
