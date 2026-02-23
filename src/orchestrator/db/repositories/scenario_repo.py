from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Recommendation, Scenario, SimulationRun


async def create_scenario(db: AsyncSession, scenario: Scenario) -> Scenario:
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return scenario


async def save_simulation_run(db: AsyncSession, run: SimulationRun) -> SimulationRun:
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def save_recommendation(db: AsyncSession, rec: Recommendation) -> Recommendation:
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


async def get_pending_approvals(db: AsyncSession) -> list[Recommendation]:
    result = await db.execute(
        select(Recommendation)
        .where(Recommendation.status == "pending")
        .order_by(Recommendation.created_at.desc())
    )
    return list(result.scalars().all())


async def update_recommendation_status(
    db: AsyncSession,
    rec_id: str,
    status: str,
    approved_by: str | None = None,
    notes: str | None = None,
) -> Recommendation | None:
    result = await db.execute(
        select(Recommendation).where(Recommendation.id == rec_id)
    )
    rec = result.scalar_one_or_none()
    if rec:
        rec.status = status
        if approved_by:
            rec.approved_by = approved_by
        if notes:
            rec.approval_notes = notes
        await db.commit()
        await db.refresh(rec)
    return rec


async def store_pending_approval(
    db: AsyncSession,
    scenario_id: str | None,
    recommendations: list[dict],
    thread_id: str | None,
) -> list[Recommendation]:
    """Persist all pending recommendations to DB so governance API can list them."""
    saved = []
    for rec_data in recommendations:
        rec = Recommendation(
            scenario_id=scenario_id,
            thread_id=thread_id,
            rec_type=rec_data.get("rec_type", "reroute"),
            description=rec_data.get("description"),
            proposed_config=rec_data.get("proposed_config"),
            cost_delta_usd=rec_data.get("cost_delta_usd"),
            risk_delta=rec_data.get("risk_delta"),
            esg_delta=rec_data.get("esg_delta"),
            confidence_pct=rec_data.get("confidence_pct"),
            status="pending",
        )
        db.add(rec)
        saved.append(rec)
    await db.commit()
    return saved
