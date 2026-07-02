from vehicle_inventory.makes.mazda.client import MazdaDealer, MazdaInventoryClient
from vehicle_inventory.makes.mazda.dealers import (
    MAZDA_DISCOVERY_MAX_DISTANCE,
    discover_nationwide_dealers,
    list_dealer_refresh_zips,
    mazda_discovery_seed_zips,
)


def test_mazda_discovery_seed_zips_are_unique_five_digit_codes():
    seeds = mazda_discovery_seed_zips()
    assert len(seeds) >= 40
    assert len(seeds) == len(set(seeds))
    assert all(len(zip_code) == 5 and zip_code.isdigit() for zip_code in seeds)


def test_list_dealer_refresh_zips_deduplicates_and_normalizes():
    class FakeConn:
        def execute(self, *_args, **_kwargs):
            class Result:
                def fetchall(self):
                    return [
                        {"postal_code": "94103"},
                        {"postal_code": "94103-1234"},
                        {"postal_code": " 02108 "},
                        {"postal_code": ""},
                    ]

            return Result()

    zips = list_dealer_refresh_zips(FakeConn())
    assert zips == ["02108", "94103"]


def test_discover_nationwide_dealers_deduplicates_by_id():
    client = MazdaInventoryClient.__new__(MazdaInventoryClient)
    calls: list[str] = []

    def fake_fetch_dealers(zip_code: str, *, max_distance: int = 250):
        calls.append(zip_code)
        if zip_code == "10001":
            return [
                MazdaDealer(
                    dealer_id=42004,
                    name="A",
                    city="San Jose",
                    state="CA",
                    zip_code="95129",
                    distance_mi=9.0,
                    lat=37.0,
                    lon=-122.0,
                )
            ]
        if zip_code == "60601":
            return [
                MazdaDealer(
                    dealer_id=42004,
                    name="A",
                    city="San Jose",
                    state="CA",
                    zip_code="95129",
                    distance_mi=5.0,
                    lat=37.0,
                    lon=-122.0,
                ),
                MazdaDealer(
                    dealer_id=41178,
                    name="B",
                    city="San Jose",
                    state="CA",
                    zip_code="95136",
                    distance_mi=12.0,
                    lat=37.1,
                    lon=-121.8,
                ),
            ]
        return []

    client.fetch_dealers = fake_fetch_dealers
    dealers = discover_nationwide_dealers(
        client,
        seed_zips=["10001", "60601"],
        max_distance=MAZDA_DISCOVERY_MAX_DISTANCE,
        zip_delay=0,
    )
    assert calls == ["10001", "60601"]
    assert [dealer.dealer_id for dealer in dealers] == [41178, 42004]
