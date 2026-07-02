"""RQ queue/worker maintenance helpers."""

from __future__ import annotations

import os
import socket
from typing import List

from vehicle_inventory.core.logging import get_logger

log = get_logger(__name__)

_QUEUE_NAMES = ("ingest", "geocode", "default")


def _job_error_snippet(rq_job) -> str:
    exc_info = getattr(rq_job, "exc_info", None)
    if exc_info:
        lines = str(exc_info).strip().splitlines()
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                return stripped[:500]
    return str(getattr(rq_job, "meta", {}).get("failure_reason") or "Worker job failed.")


def list_failed_jobs(redis_url: str, *, limit: int = 10) -> List[dict]:
    from redis import Redis
    from rq import Queue

    redis = Redis.from_url(redis_url)
    rows: List[dict] = []
    for name in _QUEUE_NAMES:
        queue = Queue(name, connection=redis)
        job_ids = queue.failed_job_registry.get_job_ids(0, max(0, limit - 1))
        for job_id in job_ids:
            try:
                job = queue.job_class.fetch(job_id, connection=redis)
            except Exception:
                rows.append({"queue": name, "id": job_id, "error": "Failed to load job record."})
                continue
            rows.append(
                {
                    "queue": name,
                    "id": job.id,
                    "func_name": getattr(job, "func_name", None),
                    "description": getattr(job, "description", None),
                    "ended_at": getattr(job, "ended_at", None),
                    "error": _job_error_snippet(job),
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def repair_rq_fleet(redis_url: str) -> dict:
    """Reclaim jobs stuck in RQ intermediate queues back onto the main queues."""
    from redis import Redis
    from rq import Queue
    from rq.intermediate_queue import IntermediateQueue

    redis = Redis.from_url(redis_url)
    reclaimed_jobs = 0
    queue_stats: List[dict] = []

    for name in _QUEUE_NAMES:
        queue = Queue(name, connection=redis)
        intermediate = IntermediateQueue(queue.key, redis)
        intermediate_ids = intermediate.get_job_ids()
        reclaimed_here = 0
        for job_id in intermediate_ids:
            intermediate.remove(job_id)
            if queue.job_class.exists(job_id, redis):
                queue.push_job_id(job_id, at_front=True)
                reclaimed_here += 1
        reclaimed_jobs += reclaimed_here
        queue_stats.append(
            {
                "name": name,
                "queued": int(queue.count),
                "intermediate": len(intermediate_ids),
                "reclaimed": reclaimed_here,
                "failed": int(len(queue.failed_job_registry)),
            }
        )

    payload = {
        "reclaimed_jobs": reclaimed_jobs,
        "queues": queue_stats,
    }
    log.info("rq_fleet_repaired", **payload)
    return payload


def remove_failed_job(redis_url: str, *, queue_name: str, job_id: str) -> bool:
    from redis import Redis
    from rq import Queue

    redis = Redis.from_url(redis_url)
    queue = Queue(queue_name, connection=redis)
    queue.failed_job_registry.remove(job_id, delete_job=True)
    return True


def prepare_job_enqueue(queue, job_id: str) -> None:
    """Drop stale failed/canceled job records that block re-use of a custom job id."""
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    try:
        existing = Job.fetch(job_id, connection=queue.connection)
    except NoSuchJobError:
        return

    status = existing.get_status()
    if status in {"failed", "canceled", "stopped"}:
        existing.delete(remove_from_queue=True, remove_from_registries=True)
        return
    if status in {"queued", "deferred", "scheduled"}:
        return
    if status in {"started", "finished"}:
        raise RuntimeError(f"Queue job {job_id} already exists with status {status}.")


def default_worker_name(*, index: int | None = None) -> str:
    host = socket.gethostname().split(".")[0] or "host"
    pid = os.getpid()
    if index is not None:
        return f"vit-{host}-{index}-{pid}"
    return f"vit-{host}-{pid}"
