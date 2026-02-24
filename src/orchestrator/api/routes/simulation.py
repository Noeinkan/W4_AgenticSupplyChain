"""
Simulation API routes.

POST /api/v1/simulation/trigger   — start agent pipeline async, returns run_id + thread_id
GET  /api/v1/simulation/{run_id}/status  — poll progress
GET  /api/v1/simulation/{run_id}/results — full results + recommendations
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.dependencies import get_db, get_graph
from orchestrator.api.schemas import (
    SimulationResultResponse,
    SimulationStartResponse,
    SimulationStatusResponse,
    TriggerSimulationRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["simulation"])

# In-memory run registry (replace with DB table in production)
_runs: dict[str, dict] = {}


@router.post("/trigger", response_model=SimulationStartResponse)
async def trigger_simulation(
    request: TriggerSimulationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_graph),
):
    """
    Start the full agent pipeline asynchronously.
    Returns run_id + thread_id immediately. Poll /status for progress.
    The thread_id is the LangGraph checkpoint ID used for HITL resume.
    """
    thread_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    initial_state = {
        "manufacturer_profile": request.manufacturer_profile.model_dump(),
        "trigger_event_id": None,
        "active_events": [],
        "risk_scores": {},
        "affected_suppliers": [],
        "affected_routes": [],
        "scenarios": [],
        "simulation_results": {},
        "recommendations": [],
        "selected_recommendation": None,
        "hitl_required": False,
        "hitl_decision": None,
        "hitl_notes": None,
        "approval_timeout_seconds": 86_400,
        "execution_status": "pending",
        "execution_log": [],
        "esg_baseline": {},
        "esg_projected": {},
        "thread_id": thread_id,
        "iteration_count": 0,
        "max_iterations": 3,
        "messages": [],
        "error": None,
    }

    _runs[run_id] = {
        "thread_id": thread_id,
        "status": "running",
        "progress_pct": 0.0,
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "final_state": None,
    }

    config = {"configurable": {"thread_id": thread_id}}
    background_tasks.add_task(_run_pipeline, graph, initial_state, config, run_id)

    return SimulationStartResponse(run_id=run_id, thread_id=thread_id)


@router.get("/{run_id}/status", response_model=SimulationStatusResponse)
async def get_simulation_status(run_id: str):
    """Poll simulation progress."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return SimulationStatusResponse(
        run_id=run_id,
        status=run["status"],
        progress_pct=run["progress_pct"],
        created_at=run.get("created_at"),
        completed_at=run.get("completed_at"),
        thread_id=run.get("thread_id"),
    )


@router.get("/{run_id}/results", response_model=SimulationResultResponse)
async def get_simulation_results(run_id: str):
    """Get full results after the pipeline completes."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run["status"] not in ("complete", "awaiting_approval"):
        raise HTTPException(
            status_code=202,
            detail=f"Simulation status: {run['status']} — check /status",
        )

    state = run.get("final_state") or {}
    return SimulationResultResponse(
        run_id=run_id,
        thread_id=run["thread_id"],
        status=run["status"],
        scenario_results=[
            {"scenario_id": k, **v}
            for k, v in (state.get("simulation_results") or {}).items()
        ],
        recommendations=state.get("recommendations") or [],
        esg_summary=state.get("esg_projected") or state.get("esg_baseline") or {},
        hitl_required=state.get("hitl_required", False),
    )


async def _run_pipeline(graph, initial_state: dict, config: dict, run_id: str) -> None:
    """Background task: streams the LangGraph pipeline and tracks progress."""
    node_progress = {
        "monitor": 15,
        "analyzer": 30,
        "simulator": 60,
        "recommender": 80,
        "hitl_gate": 90,
        "executor": 100,
    }
    try:
        final_state = initial_state.copy()
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            node_name = list(event.keys())[0] if event else ""
            pct = node_progress.get(node_name, _runs[run_id]["progress_pct"])
            _runs[run_id]["progress_pct"] = pct
            final_state.update(event.get(node_name, {}))

            # HITL interrupt: graph paused waiting for human decision
            if node_name == "hitl_gate" and final_state.get("hitl_required"):
                _runs[run_id]["status"] = "awaiting_approval"
                _runs[run_id]["final_state"] = final_state
                logger.info("Pipeline paused at HITL gate for run %s", run_id)
                return

        _runs[run_id].update(
            status="complete",
            progress_pct=100.0,
            completed_at=datetime.now(UTC),
            final_state=final_state,
        )
        logger.info("Pipeline complete for run %s", run_id)

    except Exception as exc:
        logger.exception("Pipeline failed for run %s", run_id)
        _runs[run_id].update(
            status="failed",
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
