#!/usr/bin/env python3
"""One-time or manual bulk geocode of Toyota dealers into dealer_geo_cache."""

import argparse

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.db.backend import open_db_connection
from vehicle_inventory.geo.dealer_geo import (
    dealer_geo_stats,
    geocode_all_dealers,
    normalize_cached_states,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Geocode Toyota dealers into dealer_geo_cache")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max dealers to geocode this run (default: all remaining)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.1,
        help="Seconds between Nominatim requests (default: 1.1)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-geocode all dealers in inventory, not just missing/failed rows",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel geocoding workers (default: 8; use 1 for sequential)",
    )
    args = parser.parse_args()

    settings = get_settings()
    conn = open_db_connection(settings.database_url)
    try:
        normalized = normalize_cached_states(conn)
        if normalized:
            print(f"Normalized {normalized} cached state value(s) to 2-letter codes.")

        before = dealer_geo_stats(conn)
        print(
            "Before: "
            f"{before['geocoded']}/{before['dealers_in_inventory']} geocoded "
            f"({before['remaining']} remaining)"
        )
        if before["remaining"] == 0 and not args.force:
            print("Nothing to geocode.")
            return

        def progress(done: int, total: int, dealer_cd: str) -> None:
            print(f"[{done}/{total}] {dealer_cd}", flush=True)

        result = geocode_all_dealers(
            conn,
            limit=args.limit,
            delay_sec=args.delay,
            progress_callback=progress,
            force=args.force,
            workers=args.workers,
        )
        after = dealer_geo_stats(conn)
        print(
            "Done: "
            f"processed={result['processed']} "
            f"geocoded={result['batch_geocoded']} "
            f"failed={result['batch_failed']} "
            f"remaining={after['remaining']}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
