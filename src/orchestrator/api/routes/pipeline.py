"""
Pipeline routes - what the dashboard drives.

POST /api/v1/pipeline/runs              start a run, returns immediately
GET  /api/v1/pipeline/runs              recent runs
GET  /api/v1/pipeline/runs/{id}         full detail incl. scenario results
GET  /api/v1/pipeline/runs/{id}/stream  server-sent events, live node progress
POST /api/v1/pipeline/runs/{id}/decision  approve / reject a paused run
GET  /api/v1/pipeline/pending           runs blocked on a human decision
GET  /api/v1/pipeline/audit             governance audit trail
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from orchestrator.api.schemas import (
    DecisionRequest,
    DecisionResponse,
    RunDetail,
    RunStartResponse,
    RunSummary,
    TriggerRunRequest,
)
from orchestrator.pipeline import get_store

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pipeline"])

_SSE_KEEPALIVE_SECONDS = 15.0


@router.post("/runs", response_model=RunStartResponse, status_code=202)
async def start_run(request: TriggerRunRequest):
    """Kick off the agent pipeline. Watch /stream for progress."""
    store = get_store()
    run = store.create(request.manufacturer_profile.model_dump())
    store.start(run)
    return RunStartResponse(run_id=run.run_id, thread_id=run.thread_id)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(limit: int = 25):
    return [RunSummary(**r.summary()) for r in get_store().list(limit)]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str):
    run = get_store().get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return RunDetail(**run.detail())


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """Server-sent events for one run.

    Replays everything that already happened, then streams live. A late-joining
    browser tab therefore renders the full pipeline, not just the tail.
    """
    store = get_store()
    if not store.get(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def pump():
            try:
                async for event in store.subscribe(run_id):
                    await queue.put(event.to_dict())
            finally:
                await queue.put(None)

        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if item is None:
                    run = store.get(run_id)
                    final = run.summary() if run else {"run_id": run_id, "status": "gone"}
                    yield f"event: end\ndata: {json.dumps(final)}\n\n"
                    return
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/runs/{run_id}/decision", response_model=DecisionResponse)
async def submit_decision(run_id: str, request: DecisionRequest):
    """Release a run paused at the HITL gate."""
    run = get_store().get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.status != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is '{run.status}', not awaiting approval",
        )

    run.decide(request.decision, request.approver, request.notes)
    return DecisionResponse(
        run_id=run_id,
        thread_id=run.thread_id,
        decision=request.decision,
        status="resumed",
        message=f"Decision '{request.decision}' recorded by {request.approver}; pipeline resumed.",
    )


@router.get("/pending", response_model=list[RunSummary])
async def pending_approvals():
    return [RunSummary(**r.summary()) for r in get_store().pending_approvals()]


@router.get("/audit")
async def audit_log(limit: int = 100):
    return get_store().audit_log(limit)
