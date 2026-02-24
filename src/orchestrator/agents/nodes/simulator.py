"""
SimulatorAgent node: runs Monte Carlo simulations for all relevant scenario templates.

For each affected country/event type, selects matching scenario templates,
runs the MC engine, and stores results in state.simulation_results.
"""

import logging

from orchestrator.agents.state import SupplyChainState

logger = logging.getLogger(__name__)


async def run(state: SupplyChainState) -> dict:
    """SimulatorAgent node — returns partial state update."""
    from orchestrator.config import settings
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.db.repositories.route_repo import get_all_active
    from orchestrator.db.repositories.supplier_repo import get_all_active as get_suppliers
    from orchestrator.simulation.monte_carlo import run_monte_carlo
    from orchestrator.simulation.scenarios import (
        SCENARIO_TEMPLATES,
        select_relevant_scenarios,
    )

    risk_scores = state.get("risk_scores", {})
    active_events = state.get("active_events", [])
    profile = state.get("manufacturer_profile", {})
    n_iter = min(
        profile.get("n_iterations", settings.default_mc_iterations),
        settings.max_mc_iterations,
    )

    # Select scenario templates relevant to current risk profile
    relevant = select_relevant_scenarios(risk_scores, active_events)
    if not relevant:
        logger.info("Simulator: no relevant scenarios — using all templates")
        relevant = list(SCENARIO_TEMPLATES.values())[:3]

    # Load suppliers + routes
    async with AsyncSessionLocal() as db:
        all_suppliers = await get_suppliers(db)
        all_routes = await get_all_active(db)

    supplier_dicts = [
        {
            "id": s.id,
            "name": s.name,
            "country_code": s.country_code,
            "capacity_units": s.capacity_units or 10_000,
            "unit_cost_usd": float(s.unit_cost_usd or 50),
            "esg_score": float(s.esg_score or 50),
            "lead_time_days": s.lead_time_days or 30,
        }
        for s in all_suppliers
        if s.active
    ]
    route_dicts = [
        {
            "id": r.id,
            "origin_supplier_id": r.origin_supplier_id,
            "mode": r.mode,
            "transit_days": r.transit_days or 30,
            "cost_per_unit": float(r.cost_per_unit or 5),
            "co2_kg_per_unit": float(r.co2_kg_per_unit or 1),
            "through_affected_country": r.through_affected_country,
        }
        for r in all_routes
        if r.active
    ]

    demand_units = profile.get("annual_volume_units", 100_000) // 12  # monthly demand

    simulation_results: dict[str, dict] = {}
    scenario_list: list[dict] = []

    for scenario_params in relevant:
        sid = scenario_params["id"]
        logger.info("Simulator: running %d iterations for scenario '%s'", n_iter, scenario_params["name"])
        try:
            result = await run_monte_carlo(
                scenario_params=scenario_params,
                suppliers=supplier_dicts,
                routes=route_dicts,
                demand_units=demand_units,
                n_iterations=n_iter,
            )
            simulation_results[sid] = result.__dict__
            scenario_list.append(scenario_params)
            logger.info(
                "Simulator: %s → mean_cost=$%.0f  delay=%.1fd  esg=%.1f",
                scenario_params["name"],
                result.cost_mean,
                result.delay_mean,
                result.esg_score_mean,
            )
        except Exception:
            logger.exception("Simulation failed for scenario %s", sid)

    return {
        "scenarios": scenario_list,
        "simulation_results": simulation_results,
    }
