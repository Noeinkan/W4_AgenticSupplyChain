"""
Live-feed control surface.

GET  /api/v1/ingestion/status    which sources exist, which are usable, last run
POST /api/v1/ingestion/run       fetch now and publish into the catalog

``run`` exists so a live feed can be demonstrated without waiting for a scheduler
tick, and so ingestion works at all when APScheduler is not installed. It calls
the same collector the scheduled jobs call.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from orchestrator.ingestion import collector

router = APIRouter(tags=["ingestion"])


@router.get("/status")
async def ingestion_status():
    return collector.status()


@router.post("/run")
async def run_ingestion(sources: list[str] | None = Body(default=None, embed=True)):
    """
    Run the named sources, or every keyless source when none are named.

    Returns per-source outcomes plus the batch total. A source that is down or
    missing its key is reported as ``error``/``skipped`` rather than failing the
    request, because one dead feed should not block the others.
    """
    unknown = [s for s in (sources or []) if s not in collector.SOURCES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown source(s): {', '.join(unknown)}. "
                   f"Available: {', '.join(collector.SOURCES)}",
        )

    return await collector.collect_all(sources)
