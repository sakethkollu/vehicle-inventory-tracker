"""RQ worker fleet visibility for the admin UI."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from vehicle_inventory.makes.registry import list_makes

_JOB_ID_RE = re.compile(
    r"^(?P<make>[a-z0-9_-]+)-(?P<job_type>ingest|geocode|dealer-refresh)-(?P<job_run_id>\d+)$",
    re.IGNORECASE,
)

_TASK_LABELS = {
    "run_ingest_task": "Ingest",
    "run_geocode_task": "Geocode",
    "run_dealer_vehicle_refresh_task": "Dealer ZIP refresh",
}

_QUEUE_NAMES = ("ingest", "geocode", "default")


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(value)


def parse_rq_job_id(job_id: str) -> Dict[str, Any]:
    """Parse ``{make}-{job_type}-{job_run_id}`` ids assigned at enqueue time."""
    match = _JOB_ID_RE.match(str(job_id or "").strip())
    if not match:
        return {}
    job_type = match.group("job_type").replace("-", "_")
    if job_type == "dealer_refresh":
        job_type = "dealer_vehicle_refresh"
    return {
        "make": match.group("make").lower(),
        "job_type": job_type,
        "job_run_id": int(match.group("job_run_id")),
    }


def _task_label(func_name: str) -> str:
    short = str(func_name or "").rsplit(".", 1)[-1]
    return _TASK_LABELS.get(short, short or "Task")


def _live_key_for_job(make_slug: str, job_type: str) -> Optional[str]:
    if job_type in {"ingest", "dealer_vehicle_refresh", "dealer_refresh"}:
        return f"vit:{make_slug}:job:live:ingest"
    if job_type == "geocode":
        return f"vit:{make_slug}:job:live:geocode"
    return None


def _load_live_progress(redis, *, make_slug: str, job_type: str, job_run_id: int) -> dict:
    key = _live_key_for_job(make_slug, job_type)
    if not key or redis is None:
        return {}
    raw = redis.get(key)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if int(payload.get("job_run_id") or 0) != int(job_run_id):
        return {}
    return payload


def _serialize_current_job(redis, job) -> Optional[dict]:
    if job is None:
        return None
    func_name = getattr(job, "func_name", None) or ""
    parsed = parse_rq_job_id(getattr(job, "id", "") or "")
    payload: Dict[str, Any] = {
        "id": getattr(job, "id", None),
        "status": job.get_status(),
        "func_name": func_name,
        "task_label": _task_label(func_name),
        "description": getattr(job, "description", None),
        "created_at": _iso(getattr(job, "created_at", None)),
        "started_at": _iso(getattr(job, "started_at", None)),
    }
    if parsed:
        payload.update(parsed)
        live = _load_live_progress(
            redis,
            make_slug=parsed["make"],
            job_type=parsed["job_type"],
            job_run_id=parsed["job_run_id"],
        )
        if live:
            payload["live_status"] = live.get("status")
            payload["message"] = live.get("message")
            payload["percent"] = live.get("percent")
            payload["phase"] = live.get("phase")
            if live.get("current_model_title") or live.get("current_model"):
                payload["detail"] = live.get("current_model_title") or live.get("current_model")
    return payload


def _serialize_worker(redis, worker) -> dict:
    current_job = None
    try:
        current_job = worker.get_current_job()
    except Exception:
        current_job = getattr(worker, "current_job", None)

    state_raw = worker.get_state()
    state = getattr(state_raw, "value", state_raw)
    state = str(state).lower()
    try:
        queues = list(worker.queue_names())
    except Exception:
        queues = [q.name for q in getattr(worker, "queues", []) or []]

    return {
        "name": worker.name,
        "state": state,
        "pid": getattr(worker, "pid", None),
        "hostname": getattr(worker, "hostname", None),
        "queues": queues,
        "birth_date": _iso(getattr(worker, "birth_date", None)),
        "last_heartbeat": _iso(getattr(worker, "last_heartbeat", None)),
        "current_job": _serialize_current_job(redis, current_job),
    }


def _queue_stats(redis) -> List[dict]:
    from rq import Queue

    rows: List[dict] = []
    for name in _QUEUE_NAMES:
        queue = Queue(name, connection=redis)
        started = 0
        try:
            started = queue.started_job_registry.count
        except Exception:
            started = 0
        rows.append(
            {
                "name": name,
                "queued": int(queue.count),
                "started": int(started),
                "failed": int(len(queue.failed_job_registry)),
            }
        )
    return rows


def get_worker_fleet_status(*, redis_url: str, use_redis_jobs: bool) -> dict:
    expected_workers = max(1, int(os.environ.get("WORKER_CONCURRENCY", "2")))
    if not use_redis_jobs:
        return {
            "enabled": False,
            "expected_workers": expected_workers,
            "queues": [],
            "workers": [],
            "summary": {"total": 0, "busy": 0, "idle": 0, "suspended": 0},
            "message": "Redis job queue is disabled (USE_REDIS_JOBS=0).",
        }

    from redis import Redis
    from rq import Worker

    redis = Redis.from_url(redis_url)
    workers = Worker.all(connection=redis)
    serialized = [_serialize_worker(redis, worker) for worker in workers]
    serialized.sort(key=lambda row: str(row.get("name") or ""))

    summary = {
        "total": len(serialized),
        "busy": sum(1 for row in serialized if row.get("state") == "busy"),
        "idle": sum(1 for row in serialized if row.get("state") == "idle"),
        "suspended": sum(1 for row in serialized if row.get("state") == "suspended"),
    }
    queues = _queue_stats(redis)
    queued_total = sum(int(row.get("queued") or 0) for row in queues)

    message = None
    if summary["total"] == 0:
        message = "No RQ workers are connected to Redis."
    elif summary["total"] < expected_workers:
        message = (
            f"{summary['total']} of {expected_workers} expected worker(s) online."
        )
    elif queued_total > 0 and summary["busy"] == summary["total"]:
        message = f"{queued_total} job(s) queued — all workers are busy."

    return {
        "enabled": True,
        "expected_workers": expected_workers,
        "queues": queues,
        "workers": serialized,
        "summary": summary,
        "message": message,
        "makes": [
            {"slug": profile.slug, "display_name": profile.display_name}
            for profile in list_makes()
        ],
    }
