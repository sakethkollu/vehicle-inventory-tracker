"""Nationwide Mazda dealer discovery via ``dealer.ajax`` seed ZIP grid."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Sequence

from vehicle_inventory.db.backend import DbConnection
from vehicle_inventory.geo.dealer_geo import ensure_dealer_geo_cache_table, normalize_us_zip
from vehicle_inventory.makes.mazda.client import MazdaDealer, MazdaInventoryClient

# Curated metro / regional anchors — ~250 mi radius each covers the continental US.
MAZDA_DISCOVERY_SEED_ZIPS: tuple[str, ...] = (
    "10001",  # New York
    "02108",  # Boston
    "19103",  # Philadelphia
    "20001",  # Washington DC
    "21201",  # Baltimore
    "23219",  # Richmond
    "25301",  # Charleston WV
    "27601",  # Raleigh
    "28202",  # Charlotte
    "29401",  # Charleston SC
    "30301",  # Atlanta
    "32202",  # Jacksonville
    "32801",  # Orlando
    "33101",  # Miami
    "33607",  # Tampa
    "35203",  # Birmingham
    "37203",  # Nashville
    "38103",  # Memphis
    "72201",  # Little Rock
    "70112",  # New Orleans
    "73102",  # Oklahoma City
    "75201",  # Dallas
    "76102",  # Fort Worth
    "77002",  # Houston
    "78205",  # San Antonio
    "78701",  # Austin
    "80202",  # Denver
    "82001",  # Cheyenne
    "84101",  # Salt Lake City
    "85001",  # Phoenix
    "87101",  # Albuquerque
    "89101",  # Las Vegas
    "90001",  # Los Angeles
    "92101",  # San Diego
    "94103",  # San Francisco
    "95101",  # San Jose
    "95814",  # Sacramento
    "97201",  # Portland
    "98101",  # Seattle
    "99201",  # Spokane
    "55401",  # Minneapolis
    "58102",  # Fargo
    "57104",  # Sioux Falls
    "60601",  # Chicago
    "43215",  # Columbus
    "44114",  # Cleveland
    "46204",  # Indianapolis
    "48226",  # Detroit
    "53202",  # Milwaukee
    "63101",  # St Louis
    "64106",  # Kansas City
    "68102",  # Omaha
    "50309",  # Des Moines
    "59101",  # Billings
    "83702",  # Boise
    "96813",  # Honolulu
    "99501",  # Anchorage
    "02903",  # Providence
    "06103",  # Hartford
    "04101",  # Portland ME
    "15222",  # Pittsburgh
    "37902",  # Knoxville
)

MAZDA_DISCOVERY_MAX_DISTANCE = 250


def mazda_discovery_seed_zips() -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for zip_code in MAZDA_DISCOVERY_SEED_ZIPS:
        cleaned = str(zip_code or "").strip()
        if len(cleaned) == 5 and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered


def discover_nationwide_dealers(
    client: MazdaInventoryClient,
    *,
    seed_zips: Optional[Sequence[str]] = None,
    max_distance: int = MAZDA_DISCOVERY_MAX_DISTANCE,
    zip_delay: float = 0.15,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[MazdaDealer]:
    """Query ``dealer.ajax`` from seed ZIPs and return deduplicated US dealers."""
    seeds = list(seed_zips) if seed_zips else mazda_discovery_seed_zips()
    by_id: Dict[int, MazdaDealer] = {}
    total_seeds = len(seeds)

    for index, zip_code in enumerate(seeds, start=1):
        if index > 1 and zip_delay > 0:
            time.sleep(zip_delay)
        if progress_callback:
            progress_callback(
                f"Scanning dealers near {zip_code} ({index}/{total_seeds}, {len(by_id)} found)..."
            )
        try:
            rows = client.fetch_dealers(zip_code, max_distance=max_distance)
        except Exception as exc:
            print(f"[mazda] dealer discovery skipped {zip_code}: {exc}", flush=True)
            continue
        for dealer in rows:
            existing = by_id.get(dealer.dealer_id)
            if existing is None or dealer.distance_mi < existing.distance_mi:
                by_id[dealer.dealer_id] = dealer

    return sorted(by_id.values(), key=lambda row: row.dealer_id)


def list_dealer_refresh_zips(conn: DbConnection) -> List[str]:
    """Return unique 5-digit ZIPs from synced dealer geo records."""
    ensure_dealer_geo_cache_table(conn)
    rows = conn.execute(
        """
        SELECT DISTINCT dgc.postal_code
        FROM dealer_geo_cache dgc
        WHERE dgc.postal_code IS NOT NULL AND TRIM(dgc.postal_code) != ''
        ORDER BY dgc.postal_code
        """
    ).fetchall()
    zips: List[str] = []
    seen: set[str] = set()
    for row in rows:
        normalized = normalize_us_zip(str(row["postal_code"] or ""))
        if normalized and normalized not in seen:
            seen.add(normalized)
            zips.append(normalized)
    return sorted(zips)
