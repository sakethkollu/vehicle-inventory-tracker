from unittest.mock import patch

from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.geo.dealer_geo import ensure_dealer_geo_cache_table, regeocode_dealer_by_cd


def _seed_dealer(conn, dealer_cd: str = "D001", name: str = "Test Motors") -> None:
    ensure_dealer_geo_cache_table(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dealers (
            dealer_cd TEXT PRIMARY KEY,
            dealer_marketing_name TEXT,
            dealer_website TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO dealers (dealer_cd, dealer_marketing_name, dealer_website)
        VALUES (?, ?, ?)
        """,
        (dealer_cd, name, "https://example.com"),
    )
    conn.commit()


def test_regeocode_dealer_by_cd_not_found():
    conn = open_db_connection("sqlite:///:memory:")
    try:
        ensure_dealer_geo_cache_table(conn)
        result = regeocode_dealer_by_cd(conn, "MISSING")
    finally:
        conn.close()
    assert result == {"ok": False, "error": "Dealer MISSING not found"}


def test_regeocode_dealer_by_cd_stores_coords():
    conn = open_db_connection("sqlite:///:memory:")
    try:
        _seed_dealer(conn)
        geo = (37.3352, -121.8811, "95132", "San Jose", "CA")
        with patch(
            "vehicle_inventory.geo.dealer_geo.geocode_dealer_record",
            return_value=("photon:test", geo),
        ):
            result = regeocode_dealer_by_cd(conn, "D001")

        assert result["ok"] is True
        assert result["geocoded"] is True
        assert result["latitude"] == 37.3352
        assert result["longitude"] == -121.8811
        assert result["postal_code"] == "95132"
        assert result["state"] == "CA"
    finally:
        conn.close()
