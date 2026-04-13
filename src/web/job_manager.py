"""Shared background-job store for sync, reply, and memory synthesis workers.

A single module-level dict keyed by UUID job ID avoids copy-pasting the same
boilerplate (_jobs, _jobs_lock, TTL cleanup) across every route file.

Usage:
    from src.web.job_manager import create_job, get_job, update_job

    job_id = create_job(status="queued", corpus="personal")
    update_job(job_id, status="running", message="Fetching…")
    job = get_job(job_id)   # → dict snapshot, {} if expired/not found
"""
import threading
import time
import uuid
from typing import Any, Dict

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_JOB_TTL_SECS = 1800  # discard completed/errored jobs after 30 minutes


def create_job(**initial_fields: Any) -> str:
    """Allocate a new job entry, run TTL cleanup, and return the job ID."""
    _cleanup()
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"_created_at": time.time(), **initial_fields}
    return job_id


def get_job(job_id: str) -> Dict[str, Any]:
    """Return a snapshot of the job dict, or an empty dict if not found/expired."""
    with _jobs_lock:
        return dict(_jobs.get(job_id, {}))


def update_job(job_id: str, **kwargs: Any) -> None:
    """Merge kwargs into an existing job (no-op if the job is not found)."""
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _cleanup() -> None:
    """Remove completed/errored jobs that have exceeded the TTL."""
    cutoff = time.time() - _JOB_TTL_SECS
    with _jobs_lock:
        expired = [
            jid for jid, j in _jobs.items()
            if j.get("status") in ("done", "error") and j.get("_created_at", 0) < cutoff
        ]
        for jid in expired:
            del _jobs[jid]
