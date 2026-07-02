#!/usr/bin/env python3
"""Run RQ worker for ingest, geocode, and default queues."""

from __future__ import annotations

import os
from multiprocessing import Process

from redis import Redis
from rq import Worker

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger


def _run_worker(*, redis_url: str, log_level: str, log_json: bool) -> None:
    configure_logging(level=log_level, json_logs=log_json)
    log = get_logger(__name__)
    redis_conn = Redis.from_url(redis_url)
    worker = Worker(["ingest", "geocode", "default"], connection=redis_conn)
    log.info("worker_process_starting", queues=["ingest", "geocode", "default"], redis_url=redis_url)
    worker.work(with_scheduler=False)


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    log = get_logger(__name__)
    if not settings.use_redis_jobs:
        log.warning("worker_redis_disabled", message="USE_REDIS_JOBS is false; worker will idle.")

    concurrency = max(1, int(os.environ.get("WORKER_CONCURRENCY", "2")))
    log.info(
        "worker_starting",
        queues=["ingest", "geocode", "default"],
        redis_url=settings.redis_url,
        concurrency=concurrency,
    )

    if concurrency == 1:
        _run_worker(
            redis_url=settings.redis_url,
            log_level=settings.log_level,
            log_json=settings.log_json,
        )
        return

    processes: list[Process] = []
    for index in range(concurrency):
        proc = Process(
            target=_run_worker,
            kwargs={
                "redis_url": settings.redis_url,
                "log_level": settings.log_level,
                "log_json": settings.log_json,
            },
            name=f"rq-worker-{index + 1}",
            daemon=False,
        )
        proc.start()
        processes.append(proc)

    exit_code = 0
    for proc in processes:
        proc.join()
        if proc.exitcode not in (0, None):
            exit_code = proc.exitcode or 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
