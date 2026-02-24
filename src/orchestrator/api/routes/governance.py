"""
Governance (HITL) API routes.

POST /api/v1/governance/decision   — submit human approve/reject/modify
GET  /api/v1/governance/pending    — list all recommendations awaiting approval
GET  /api/v1/governance/audit-log  — full audit trail
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.dependencies import get_db, get_graph
from orchestrator.api.schemas import (
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
    PendingApproval,
)
from orchestrator.db.repositories.scenario_repo import (
    get_pending_approvals,
    update_recommendation_status,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["governance"])


@router.post("/decision", response_model=GovernanceDecisionResponse)
async def submit_governance_decision(
    request: GovernanceDecisionRequest,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_graph),
):
    """
    Inject a human decision into a paused LangGraph pipeline.

    Implementation (LangGraph interrupt/resume pattern):
    1. graph.aupdate_state() injects the human decision into the checkpointed state
    2. graph.astream(None, config) resumes from the hitl_gate node
    3. The graph routes to executor (approve) or analyzer (reject)
    """
    config = {"configurable": {"thread_id": request.thread_id}}

    try:
        # 1. Update the checkpointed state with the human decision
        await graph.aupdate_state(
            config,
            {
                "hitl_decision": request.decision,
                "hitl_notes": request.notes,
                "hitl_required": False,
            },
            as_node="hitl_gate",
        )

        # 2. Resume graph in background (non-blocking)
        asyncio.create_task(_resume_graph(graph, config, request))

        # 3. Update DB recommendation status
        await update_recommendation_status(
            db,
            rec_id=request.recommendation_id,
            status=request.decision,
            approved_by=request.approver,
            notes=request.notes,
        )

        status_msg = "resumed" if request.decision == "approve" else f"graph will {request.decision}"
        return GovernanceDecisionResponse(
            thread_id=request.thread_id,
            decision=request.decision,
            status=status_msg,
            message=f"Decision '{request.decision}' recorded. Pipeline {status_msg}.",
        )

    except Exception as exc:
        logger.exception("Governance decision failed for thread %s", request.thread_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/pending", response_model=list[PendingApproval])
async def get_pending(db: AsyncSession = Depends(get_db)):
    """Return all recommendations currently awaiting human approval."""
    recs = await get_pending_approvals(db)
    return [
        PendingApproval(
            recommendation_id=r.id,
            thread_id=r.thread_id,
            rec_type=r.rec_type,
            description=r.description,
            cost_delta_usd=float(r.cost_delta_usd) if r.cost_delta_usd else None,
            risk_delta=float(r.risk_delta) if r.risk_delta else None,
            esg_delta=float(r.esg_delta) if r.esg_delta else None,
            confidence_pct=float(r.confidence_pct) if r.confidence_pct else None,
            created_at=r.created_at,
        )
        for r in recs
    ]


@router.get("/audit-log")
async def get_audit_log(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Full audit trail — all decisions (approved, rejected, executed, pending)."""
    from sqlalchemy import select
    from orchestrator.db.models import Recommendation

    result = await db.execute(
        select(Recommendation).order_by(Recommendation.created_at.desc()).limit(limit)
    )
    recs = result.scalars().all()
    return [
        {
            "id": r.id,
            "rec_type": r.rec_type,
            "status": r.status,
            "description": r.description,
            "cost_delta_usd": float(r.cost_delta_usd) if r.cost_delta_usd else None,
            "approved_by": r.approved_by,
            "approved_at": r.approved_at.isoformat() if r.approved_at else None,
            "approval_notes": r.approval_notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recs
    ]


async def _resume_graph(graph, config: dict, request: GovernanceDecisionRequest) -> None:
    """Resume the paused LangGraph after HITL decision is injected."""
    try:
        async for event in graph.astream(None, config, stream_mode="updates"):
            node = list(event.keys())[0] if event else ""
            logger.debug("Graph resumed — node: %s", node)
        logger.info("Graph resume complete for thread %s", request.thread_id)
    except Exception:
        logger.exception("Graph resume failed for thread %s", request.thread_id)
