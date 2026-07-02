from vehicle_inventory.makes.mazda.client import MazdaClientConfig, MazdaInventoryClient, MazdaVehicle


SAMPLE_VEHICLE_PAYLOAD = {
    "response": {
        "TotalVehicles": 2,
        "Vehicles": [
            {
                "Vin": "JM1BPBDL0R1234567",
                "Carline": "CX-5",
                "ModelName": "CX-5 2.5 S Select",
                "Price": "32990",
                "BaseMsrp": "33100",
                "DealerId": 12345,
                "DetailsPageURL": "/inventory/vehicle/2025/cx-5/details",
                "Colors": {
                    "ExteriorDescription": "Soul Red",
                    "InteriorDescription": "Black",
                },
                "VehicleLocation": "02",
                "Status": "11",
                "ImagesListInfo": [{"Url": "/images/cx5.png"}],
            },
            {"VIN": "", "Carline": "ignored"},
        ],
    }
}


def test_mazda_inventory_client_accepts_config_with_cookies(monkeypatch):
    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.client.resolve_mazda_cookies",
        lambda: {},
    )
    client = MazdaInventoryClient(MazdaClientConfig(cookies={"session": "abc"}, page_size=24))
    assert client.config.page_size == 24
    assert client.session.cookies.get("session") == "abc"


def test_parse_vehicles_extracts_fields():
    client = MazdaInventoryClient.__new__(MazdaInventoryClient)
    vehicles = client.parse_vehicles(SAMPLE_VEHICLE_PAYLOAD)
    assert len(vehicles) == 1
    vehicle = vehicles[0]
    assert isinstance(vehicle, MazdaVehicle)
    assert vehicle.vin == "JM1BPBDL0R1234567"
    assert vehicle.carline == "CX-5"
    assert vehicle.price == 32990.0
    assert vehicle.base_msrp == 33100.0
    assert vehicle.year == 2025
    assert vehicle.exterior_color == "Soul Red"
    assert vehicle.dealer_id == 12345
    assert vehicle.image_url == "/images/cx5.png"
    assert vehicle.vehicle_location == "02"
    assert vehicle.status_code == "11"


def test_total_vehicle_count():
    client = MazdaInventoryClient.__new__(MazdaInventoryClient)
    assert client.total_vehicle_count(SAMPLE_VEHICLE_PAYLOAD) == 2
    assert client.total_vehicle_count({}) == 0


def test_results_start_for_page_uses_page_number_not_offset():
    assert MazdaInventoryClient.results_start_for_page(1) == 1
    assert MazdaInventoryClient.results_start_for_page(2) == 2
    assert MazdaInventoryClient.results_start_for_page(3) == 3
    # Old offset-based pagination would have sent 13 for page 2 with page_size=12.
    assert (2 - 1) * 12 + 1 == 13


def test_near_results_start_for_page():
    assert MazdaInventoryClient.near_results_start_for_page(1) == "1"
    assert MazdaInventoryClient.near_results_start_for_page(2) == ""
    assert MazdaInventoryClient.near_results_start_for_page(3) == ""


def test_search_inventory_sends_page_number_and_near_start(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": {"TotalVehicles": 0, "Vehicles": []}}

    def fake_post(self, url, data, headers, timeout):
        captured["data"] = data
        return FakeResponse()

    monkeypatch.setattr(
        "vehicle_inventory.makes.mazda.client.resolve_mazda_cookies",
        lambda: {},
    )
    client = MazdaInventoryClient(MazdaClientConfig(page_size=12))
    monkeypatch.setattr(client.session, "post", lambda *args, **kwargs: fake_post(client.session, *args, **kwargs))

    client.search_inventory([42004], results_start=2, carlines=["C50"])
    params = dict(x.split("=", 1) for x in captured["data"].split("&") if "=" in x)
    assert params["ResultsStart"] == "2"
    assert params.get("NearResultsStart", "") == ""
    assert params["ResultsPageSize"] == "12"


SAMPLE_DEALER_ROW = {
    "id": 42004,
    "name": "STEVENS CREEK MAZDA",
    "webUrl": "http://www.stevenscreekmazda.com/",
    "city": "San Jose",
    "state": "CA",
}


def test_dealer_row_to_payload():
    payload = MazdaInventoryClient.dealer_row_to_payload(SAMPLE_DEALER_ROW)
    assert payload == {
        "dealerCd": "42004",
        "dealerMarketingName": "STEVENS CREEK MAZDA",
        "dealerWebsite": "http://www.stevenscreekmazda.com/",
    }


def test_fetch_dealer_by_id(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "header": {"status": "success"},
                "body": {"results": [SAMPLE_DEALER_ROW], "total": 1},
            }

    client = MazdaInventoryClient.__new__(MazdaInventoryClient)
    client.session = type("Session", (), {"get": lambda self, *args, **kwargs: FakeResponse()})()
    payload = client.fetch_dealer_by_id(42004)
    assert payload["dealerMarketingName"] == "STEVENS CREEK MAZDA"


def test_fetch_dealers_paginates_until_total_reached(monkeypatch):
    calls: list[int] = []

    class FakeResponse:
        def __init__(self, page: int):
            self.page = page

        def raise_for_status(self):
            return None

        def json(self):
            if self.page == 1:
                return {
                    "header": {"status": "success"},
                    "body": {
                        "total": 2,
                        "results": [
                            {"id": 42004, "name": "A", "city": "X", "state": "CA", "zip": "95101", "driveDistMi": 1.0, "lat": 0.0, "long": 0.0},
                        ],
                    },
                }
            return {
                "header": {"status": "success"},
                "body": {
                    "total": 2,
                    "results": [
                        {"id": 42167, "name": "B", "city": "Y", "state": "CA", "zip": "94560", "driveDistMi": 2.0, "lat": 0.0, "long": 0.0},
                    ],
                },
            }

    def fake_get(self, url, params=None, timeout=None):
        calls.append(int((params or {}).get("p", 1)))
        return FakeResponse(calls[-1])

    client = MazdaInventoryClient.__new__(MazdaInventoryClient)
    client.session = type("Session", (), {"get": fake_get})()
    dealers = client.fetch_dealers("95101", max_distance=100)
    assert calls == [1, 2]
    assert [dealer.dealer_id for dealer in dealers] == [42004, 42167]
