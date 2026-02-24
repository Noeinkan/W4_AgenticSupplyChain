"""
HITL Gate node: decides whether to auto-approve or interrupt for human review.

LangGraph compiles the graph with interrupt_before=["hitl_gate"].
That means this node is reached but PAUSED before execution.
The graph resumes when the governance API calls graph.aupdate_state()
with the human's decision, then graph.astream(None, config).

This node itself handles the auto-approve logic and storing pending approvals.
"""

import logging

from orchestrator.agents.state import SupplyChainState
from orchestrator.config import settings

logger = logging.getLogger(__name__)

# Auto-approve thresholds — adjust per enterprise risk appetite
AUTO_APPROVE_RULES: dict[str, callable] = {
    "inventory_adj": lambda rec: abs(rec.get("cost_delta_usd", 999_999)) < 5_000,
    "reroute": lambda rec: (
        rec.get("risk_delta", 0) <= -0.05
        and abs(rec.get("cost_delta_usd", 999_999)) < settings.auto_approve_cost_threshold_usd
        and rec.get("confidence_pct", 0) >= 90
    ),
    # supplier_switch always requires human approval
    "supplier_switch": lambda rec: False,
}

# Escalation tiers (for setting approval_timeout)
def _escalation_tier(rec: dict) -> tuple[str, int]:
    cost = abs(rec.get("cost_delta_usd", 0) or 0)
    if cost < 10_000:
        return "auto", 0
    if cost < 100_000:
        return "manager", 24 * 3600
    return "c_suite", 48 * 3600


async def run(state: SupplyChainState) -> dict:
    """
    HITL Gate node.

    Note: LangGraph's interrupt_before=["hitl_gate"] means graph execution
    pauses BEFORE this node runs. The governance API resumes it by calling:
        await graph.aupdate_state(config, {"hitl_decision": "approve"}, as_node="hitl_gate")
        async for _ in graph.astream(None, config): ...

    This node runs AFTER the human has decided (or is auto-approved).
    It checks the decision and routes accordingly.
    """
    recommendations = state.get("recommendations", [])
    hitl_decision = state.get("hitl_decision")

    if not recommendations:
        return {
            "hitl_required": False,
            "hitl_decision": "end",
            "selected_recommendation": None,
        }

    selected = state.get("selected_recommendation") or recommendations[0]
    rec_type = selected.get("rec_type", "reroute")

    # Check auto-approve rules (evaluated before the interrupt fires)
    auto_rule = AUTO_APPROVE_RULES.get(rec_type, lambda _: False)
    can_auto_approve = auto_rule(selected)

    if can_auto_approve and hitl_decision is None:
        logger.info(
            "HITL Gate: AUTO-APPROVE rec_type=%s cost_delta=$%.0f",
            rec_type,
            selected.get("cost_delta_usd", 0),
        )
        return {
            "hitl_required": False,
            "hitl_decision": "approve",
            "selected_recommendation": selected,
        }

    # If we reach here without a human decision, store pending and signal interrupt
    if hitl_decision is None:
        tier, timeout = _escalation_tier(selected)
        logger.info(
            "HITL Gate: INTERRUPT required — tier=%s rec_type=%s cost_delta=$%.0f",
            tier,
            rec_type,
            selected.get("cost_delta_usd", 0),
        )
        # Store recommendations in DB for the governance API to surface
        from orchestrator.db.engine import AsyncSessionLocal
        from orchestrator.db.repositories.scenario_repo import store_pending_approval

        async with AsyncSessionLocal() as db:
            await store_pending_approval(
                db=db,
                scenario_id=selected.get("scenario_id"),
                recommendations=recommendations[:5],
                thread_id=state.get("thread_id"),
            )

        return {
            "hitl_required": True,
            "hitl_decision": None,  # will be set by governance API
            "approval_timeout_seconds": timeout,
            "selected_recommendation": selected,
        }

    # Human decision has been set by the governance API
    logger.info("HITL Gate: human decision = %s", hitl_decision)
    return {
        "hitl_required": False,
        "hitl_decision": hitl_decision,
        "selected_recommendation": selected,
    }
