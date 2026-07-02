import argparse
import os
from pathlib import Path
from typing import List

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.makes.toyota.ingest import LiveIngestSettings, run_live_ingest


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0"
)


def settings_from_args(args: argparse.Namespace) -> LiveIngestSettings:
    settings = get_settings()
    model_codes = None
    if getattr(args, "model_codes", ""):
        model_codes = [part.strip() for part in args.model_codes.split(",") if part.strip()]
    return LiveIngestSettings(
        database_url=settings.database_url,
        schema_path=settings.schema_path,
        zip_code=args.zip_code,
        distance=args.distance,
        page_size=args.page_size,
        lead_id=args.lead_id,
        series_code=args.series_code,
        model_codes=model_codes,
        all_models=getattr(args, "all_models", False),
        waf_token=getattr(args, "waf_token", "") or os.getenv("TOYOTA_WAF_TOKEN", ""),
        user_agent=getattr(args, "user_agent", DEFAULT_USER_AGENT),
        referer=getattr(args, "referer", "https://www.toyota.com/"),
        origin=getattr(args, "origin", "https://www.toyota.com"),
        x_api_key=getattr(args, "x_api_key", "undefined"),
        interior_media=not getattr(args, "no_interior_media", False),
        page_delay=getattr(args, "page_delay", 0.5),
        max_retries=getattr(args, "max_retries", 5),
        retry_backoff=getattr(args, "retry_backoff", 1.0),
        waf_refresh_cooldown=getattr(args, "waf_refresh_cooldown", 30.0),
        waf_post_refresh_delay=getattr(args, "waf_post_refresh_delay", 3.0),
        rate_limit_backoff=getattr(args, "rate_limit_backoff", 20.0),
    )


def run_live_ingest_cli(args: argparse.Namespace) -> None:
    settings = settings_from_args(args)
    if settings.all_models or settings.model_codes:
        target = "all models" if settings.all_models else ", ".join(settings.model_codes or [])
        print(
            f"Starting live ingest for {target} zip={settings.zip_code} "
            f"distance={settings.distance} page_size={settings.page_size}",
            flush=True,
        )
    else:
        print(
            f"Starting live ingest for series={settings.series_code} zip={settings.zip_code} "
            f"distance={settings.distance} page_size={settings.page_size}",
            flush=True,
        )

    if not settings.waf_token:
        print("[ingest] fetching WAF token via Playwright...", flush=True)

    def on_progress(progress) -> None:
        if progress.phase == "token":
            return
        print(f"[ingest] {progress.percent:.1f}% — {progress.message}", flush=True)

    run_live_ingest(settings, progress_callback=on_progress)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vehicle inventory ingester")
    parser.add_argument("--series-code", default="rav4pluginhybrid")
    parser.add_argument("--zip-code", default="95132")
    parser.add_argument("--distance", type=int, default=500)
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--lead-id", default="3807e828-1b31-4efa-962f-7646948b7d4b")
    parser.add_argument("--waf-token", default="")
    parser.add_argument("--all-models", action="store_true", help="Fetch model catalog and ingest every model")
    parser.add_argument(
        "--model-codes",
        default="",
        help="Comma-separated model codes to ingest (fetches catalog first)",
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--referer", default="https://www.toyota.com/")
    parser.add_argument("--origin", default="https://www.toyota.com")
    parser.add_argument("--x-api-key", default="undefined")
    parser.add_argument("--no-interior-media", action="store_true")
    parser.add_argument(
        "--page-delay",
        type=float,
        default=0.5,
        help="Seconds to wait between page requests (helps avoid rate limits)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Retry count for transient page failures (403/429, null payload, etc.)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=1.0,
        help="Base seconds for exponential backoff between non-rate-limit retries",
    )
    parser.add_argument(
        "--rate-limit-backoff",
        type=float,
        default=20.0,
        help="Base seconds for exponential backoff after HTTP 403/429",
    )
    parser.add_argument(
        "--waf-refresh-cooldown",
        type=float,
        default=30.0,
        help="Minimum seconds between Playwright WAF token refreshes",
    )
    parser.add_argument(
        "--waf-post-refresh-delay",
        type=float,
        default=3.0,
        help="Seconds to wait after refreshing WAF token before retrying API calls",
    )
    return parser


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "live":
        sys.argv.pop(1)
    run_live_ingest_cli(build_parser().parse_args())


if __name__ == "__main__":
    main()
