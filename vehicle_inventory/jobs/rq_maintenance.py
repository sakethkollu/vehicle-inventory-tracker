"""RQ queue/worker maintenance helpers."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from vehicle_inventory.core.secrets import sanitize_secrets
from vehicle_inventory.core.logging import get_logger

log = get_logger(__name__)

_QUEUE_NAMES = ("ingest", "geocode", "default")
# RQ workers normally heartbeat about once a minute; treat older entries as dead containers.
STALE_WORKER_HEARTBEAT_SEC = 90


def _parse_timestamp(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def worker_heartbeat_age_sec(worker, *, now: Optional[datetime] = None) -> Optional[float]:
    heartbeat = _parse_timestamp(getattr(worker, "last_heartbeat", None))
    if heartbeat is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - heartbeat).total_seconds())


def is_worker_stale(worker, *, max_age_sec: int = STALE_WORKER_HEARTBEAT_SEC) -> bool:
    age = worker_heartbeat_age_sec(worker)
    if age is None:
        return True
    return age > max_age_sec


def split_workers_by_health(workers) -> Tuple[list, list]:
    active: list = []
    stale: list = []
    for worker in workers:
        if is_worker_stale(worker):
            stale.append(worker)
        else:
            active.append(worker)
    return active, stale


def cleanup_stale_workers(redis_url: str, *, max_age_sec: int = STALE_WORKER_HEARTBEAT_SEC) -> int:
    from redis import Redis
    from rq import Worker

    redis = Redis.from_url(redis_url)
    removed = 0
    for worker in Worker.all(connection=redis):
        if not is_worker_stale(worker, max_age_sec=max_age_sec):
            continue
        try:
            worker.register_death()
            removed += 1
            log.info("rq_stale_worker_removed", worker=worker.name)
        except Exception:
            log.exception("rq_stale_worker_remove_failed", worker=getattr(worker, "name", "?"))
    return removed


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
                    "description": sanitize_secrets(getattr(job, "description", None)),
                    "ended_at": getattr(job, "ended_at", None),
                    "error": sanitize_secrets(_job_error_snippet(job)),
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
    removed_workers = cleanup_stale_workers(redis_url)
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
        "removed_workers": removed_workers,
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
