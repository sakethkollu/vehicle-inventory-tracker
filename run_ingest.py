from datetime import datetime, timezone
from time import perf_counter

from vehicle_inventory.ingest.cli import main


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _print_failure_hint(exc: Exception) -> None:
    message = str(exc)
    if "403" in message or "Forbidden" in message:
        print(
            "[ingest] hint: Toyota API returned 403. This is often AWS WAF rate limiting "
            "after many requests, not just an expired token. Retry later, increase "
            "--page-delay (default 0.5), --rate-limit-backoff (default 20), or "
            "--waf-refresh-cooldown (default 30).",
            flush=True,
        )
        return
    if "locateVehiclesByZip` is null" in message:
        print(
            "[ingest] hint: API returned null search results mid-run. This is usually "
            "rate limiting or token fatigue after many rapid requests. Retry with a "
            "fresh token, keep the default --page-delay 0.25, or increase --max-retries.",
            flush=True,
        )
        return
    if "Unexpected GraphQL payload" in message or "locateVehiclesByZip" in message:
        print(
            "[ingest] hint: GraphQL response shape was not usable. Check series code, "
            "query compatibility, and token validity.",
            flush=True,
        )


if __name__ == "__main__":
    started = perf_counter()
    print(f"[ingest] started at {_now_iso()}", flush=True)
    try:
        main()
    except Exception as exc:
        elapsed_sec = perf_counter() - started
        print(f"[ingest] failed after {elapsed_sec:.1f}s: {exc}", flush=True)
        _print_failure_hint(exc)
        raise
    elapsed_sec = perf_counter() - started
    print(f"[ingest] finished in {elapsed_sec:.1f}s", flush=True)
