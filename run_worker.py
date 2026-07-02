#!/usr/bin/env python3
"""Run RQ worker for ingest, geocode, and default queues."""

from __future__ import annotations

from redis import Redis
from rq import Worker

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    log = get_logger(__name__)
    if not settings.use_redis_jobs:
        log.warning("worker_redis_disabled", message="USE_REDIS_JOBS is false; worker will idle.")
    redis_conn = Redis.from_url(settings.redis_url)
    worker = Worker(["ingest", "geocode", "default"], connection=redis_conn)
    log.info("worker_starting", queues=["ingest", "geocode", "default"], redis_url=settings.redis_url)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
