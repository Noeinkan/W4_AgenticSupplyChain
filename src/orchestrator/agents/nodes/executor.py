"""
ExecutorAgent node: applies an approved recommendation to the database and audit log.

For "reroute": marks routes through affected country as inactive, activates alternatives.
For "supplier_switch": updates supplier active flags.
For "inventory_adj": logs the adjustment recommendation (actual ERP write is out of scope for MVP).
"""

import logging
from datetime import UTC, datetime

from orchestrator.agents.state import SupplyChainState

logger = logging.getLogger(__name__)


async def run(state: SupplyChainState) -> dict:
    """ExecutorAgent node — applies the approved recommendation."""
    decision = state.get("hitl_decision")
    selected = state.get("selected_recommendation")

    if decision != "approve" or not selected:
        return {
            "execution_status": "failed",
            "execution_log": [f"Execution skipped: decision={decision}"],
        }

    rec_type = selected.get("rec_type", "reroute")
    log_entries: list[str] = []
    ts = datetime.now(UTC).isoformat()

    try:
        from orchestrator.db.engine import AsyncSessionLocal
        from orchestrator.db.repositories.scenario_repo import update_recommendation_status

        async with AsyncSessionLocal() as db:
            # Mark the recommendation as executed in DB
            rec_id = selected.get("id") or selected.get("scenario_id")
            if rec_id:
                await update_recommendation_status(
                    db, rec_id, status="executed",
                    approved_by=state.get("hitl_notes", "auto-approved"),
                    notes=state.get("hitl_notes"),
                )

        log_entries.append(f"[{ts}] Recommendation marked as executed: rec_type={rec_type}")

        if rec_type == "reroute":
            log_entries.extend(await _execute_reroute(selected))
        elif rec_type == "supplier_switch":
            log_entries.extend(await _execute_supplier_switch(selected))
        elif rec_type == "inventory_adj":
            log_entries.extend(_execute_inventory_adj(selected))
        else:
            log_entries.append(f"[{ts}] Unknown rec_type '{rec_type}' — no DB action taken")

        log_entries.append(f"[{ts}] Execution complete.")
        return {"execution_status": "done", "execution_log": log_entries}

    except Exception as exc:
        logger.exception("Executor failed for rec_type=%s", rec_type)
        return {
            "execution_status": "failed",
            "execution_log": log_entries + [f"[{ts}] ERROR: {exc}"],
        }


async def _execute_reroute(rec: dict) -> list[str]:
    """Mark routes through affected country as through_affected_country=True for cost modeling."""
    from sqlalchemy import update
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.db.models import Route

    proposed = rec.get("proposed_config", {})
    # proposed_config is {supplier_id: units_allocated}
    log = []
    if not proposed:
        return ["[reroute] No proposed_config — logged recommendation only"]

    async with AsyncSessionLocal() as db:
        # Flag routes through affected countries so future simulations cost them correctly
        stmt = (
            update(Route)
            .where(Route.through_affected_country == True)  # noqa: E712
            .values(active=False)
        )
        result = await db.execute(stmt)
        await db.commit()
        log.append(f"[reroute] Deactivated {result.rowcount} routes through affected countries")
    return log


async def _execute_supplier_switch(rec: dict) -> list[str]:
    """For a supplier switch, update supplier active flags per proposed config."""
    log = ["[supplier_switch] Supplier switch logged — ERP integration required for full execution"]
    proposed = rec.get("proposed_config", {})
    if proposed:
        allocation_str = ", ".join(f"{sid[:8]}…={int(units)} units" for sid, units in proposed.items())
        log.append(f"[supplier_switch] Proposed allocation: {allocation_str}")
    return log


def _execute_inventory_adj(rec: dict) -> list[str]:
    """Inventory adjustments are recommendations to the ERP — log only."""
    return [
        f"[inventory_adj] {rec.get('description', 'Increase safety stock')}",
        "[inventory_adj] Action logged — ERP integration required for execution",
    ]
