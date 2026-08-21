"""
Whether the APScheduler ingestion loop is currently running.

Kept apart from :mod:`orchestrator.ingestion.scheduler` so the status endpoint can
answer the question without importing ``apscheduler``, which is optional.
"""

from __future__ import annotations

_running = False
_job_ids: list[str] = []


def mark_started(job_ids: list[str]) -> None:
    global _running
    _running = True
    _job_ids[:] = job_ids


def mark_stopped() -> None:
    global _running
    _running = False
    _job_ids.clear()


def is_running() -> bool:
    return _running


def job_ids() -> list[str]:
    return list(_job_ids)
