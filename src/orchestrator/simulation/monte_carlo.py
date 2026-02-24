"""
Monte Carlo simulation engine.

Runs N iterations of stochastic disruption scenarios, each time:
  1. Sample tariff rate, delay multiplier, demand change, port closure (numpy vectorized)
  2. Apply to routes → adjusted_routes
  3. Solve LP for optimal supplier allocation
  4. Score result (cost, delay, ESG)

1,000 iterations typically complete in 2–5 seconds on a modern laptop.

Key outputs: cost distribution percentiles, Pareto front (cost vs. ESG),
best_config (supplier allocation for the minimum-cost feasible run).
"""

import asyncio
import logging
from dataclasses import dataclass, field

import numpy as np

from orchestrator.simulation.optimizer import LPResult, solve_routing_lp

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    scenario_id: str
    scenario_name: str
    iterations: int
    # Cost distribution
    cost_mean: float
    cost_p5: float       # 5th percentile (best case)
    cost_p95: float      # 95th percentile (tail risk)
    # Operational
    delay_mean: float
    co2_mean: float
    # Scores
    risk_score_mean: float   # 0–1 (higher = riskier)
    esg_score_mean: float    # 0–100
    # Optimal routing
    pareto_front: list[dict] = field(default_factory=list)
    best_config: dict = field(default_factory=dict)
    infeasible_pct: float = 0.0


async def run_monte_carlo(
    scenario_params: dict,
    suppliers: list[dict],
    routes: list[dict],
    demand_units: int,
    n_iterations: int = 1000,
) -> SimulationResult:
    """
    Async wrapper: runs the synchronous MC loop in a thread pool
    so it doesn't block the event loop.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        _run_mc_sync,
        scenario_params,
        suppliers,
        routes,
        demand_units,
        n_iterations,
    )
    return result


def _run_mc_sync(
    scenario_params: dict,
    suppliers: list[dict],
    routes: list[dict],
    demand_units: int,
    n_iterations: int,
) -> SimulationResult:
    """Synchronous Monte Carlo — runs in thread pool executor."""
    n = n_iterations
    sid = scenario_params["id"]
    logger.debug("MC start: scenario=%s n=%d suppliers=%d", sid, n, len(suppliers))

    # --- Sample stochastic parameters (all n iterations at once) ---
    tariff_range = scenario_params.get("tariff_shock", {}).get("rate_range", [0.0, 0.0])
    delay_range = scenario_params.get("weather_impact", {}).get(
        "delay_multiplier_range", [1.0, 1.0]
    )
    demand_range = scenario_params.get("demand_shock", {}).get("change_range", [0.0, 0.0])
    port_closure_prob = float(scenario_params.get("port_closure_probability", 0.0))
    cap_reduction_range = scenario_params.get("capacity_reduction", {}).get("range", [0.0, 0.0])
    cap_reduction_country = scenario_params.get("capacity_reduction", {}).get("country", "NONE")
    extra_days = float(scenario_params.get("extra_transit_days", 0))

    tariff_rates = np.random.uniform(tariff_range[0], tariff_range[1], n)
    delay_mults = np.random.uniform(delay_range[0], delay_range[1], n)
    demand_changes = np.random.uniform(demand_range[0], demand_range[1], n)
    port_closures = np.random.binomial(1, port_closure_prob, n)
    cap_reductions = np.random.uniform(cap_reduction_range[0], cap_reduction_range[1], n)

    # --- Run LP for each iteration ---
    costs = np.zeros(n)
    delays = np.zeros(n)
    co2s = np.zeros(n)
    esg_scores = np.zeros(n)
    infeasible_count = 0
    sample_configs: list[dict] = []   # store first 20 for Pareto analysis

    for i in range(n):
        adj_routes = _apply_disruption(
            routes,
            tariff_rate=tariff_rates[i],
            delay_mult=delay_mults[i],
            port_closed=bool(port_closures[i]),
            extra_days=extra_days,
        )
        adj_suppliers = _apply_capacity_cut(
            suppliers,
            country=cap_reduction_country,
            reduction=cap_reductions[i],
        )
        iter_demand = max(1, int(demand_units * (1.0 + demand_changes[i])))

        lp: LPResult = solve_routing_lp(
            suppliers=adj_suppliers,
            routes=adj_routes,
            demand_units=iter_demand,
        )

        if not lp.feasible:
            infeasible_count += 1
            costs[i] = costs[i - 1] * 3 if i > 0 else demand_units * 999
            delays[i] = 999
            co2s[i] = 999
            esg_scores[i] = 0.0
        else:
            costs[i] = lp.total_cost
            delays[i] = lp.avg_delay_days
            co2s[i] = lp.avg_co2_per_unit
            esg_scores[i] = lp.esg_score
            if i < 20:
                sample_configs.append({"cost": lp.total_cost, "esg": lp.esg_score, "config": lp.config})

    # --- Aggregate ---
    risk_scores = 1.0 - np.clip(esg_scores / 100.0, 0.0, 1.0)

    best_idx = int(np.argmin(costs))
    best_config = sample_configs[min(best_idx, len(sample_configs) - 1)].get("config", {}) if sample_configs else {}

    result = SimulationResult(
        scenario_id=sid,
        scenario_name=scenario_params.get("name", sid),
        iterations=n,
        cost_mean=float(np.mean(costs)),
        cost_p5=float(np.percentile(costs, 5)),
        cost_p95=float(np.percentile(costs, 95)),
        delay_mean=float(np.mean(delays)),
        co2_mean=float(np.mean(co2s)),
        risk_score_mean=float(np.mean(risk_scores)),
        esg_score_mean=float(np.mean(esg_scores)),
        pareto_front=_pareto_front(sample_configs),
        best_config=best_config,
        infeasible_pct=round(100.0 * infeasible_count / n, 2),
    )
    logger.debug(
        "MC done: scenario=%s cost_mean=%.0f p95=%.0f delay=%.1fd infeasible=%.1f%%",
        sid,
        result.cost_mean,
        result.cost_p95,
        result.delay_mean,
        result.infeasible_pct,
    )
    return result


def _apply_disruption(
    routes: list[dict],
    tariff_rate: float,
    delay_mult: float,
    port_closed: bool,
    extra_days: float,
) -> list[dict]:
    """
    Returns adjusted route dicts for a single MC iteration.
    Routes through affected countries get tariff surcharge + delay multiplier.
    Port closure makes through-affected-country routes prohibitively expensive.
    """
    adjusted = []
    for r in routes:
        rc = dict(r)
        if rc.get("through_affected_country"):
            if port_closed:
                rc["cost_per_unit"] = rc.get("cost_per_unit", 0) * 999  # effectively blocked
            else:
                rc["cost_per_unit"] = rc.get("cost_per_unit", 0) * (1 + tariff_rate)
            rc["transit_days"] = (rc.get("transit_days", 30) * delay_mult) + extra_days
        adjusted.append(rc)
    return adjusted


def _apply_capacity_cut(
    suppliers: list[dict],
    country: str,
    reduction: float,
) -> list[dict]:
    """Apply a fractional capacity reduction to suppliers in the affected country."""
    if country == "ALL":
        return [
            {**s, "capacity_units": max(1, int((s.get("capacity_units") or 10_000) * (1 - reduction)))}
            for s in suppliers
        ]
    return [
        {
            **s,
            "capacity_units": max(
                1,
                int((s.get("capacity_units") or 10_000) * (1 - reduction))
                if s.get("country_code") == country
                else (s.get("capacity_units") or 10_000),
            ),
        }
        for s in suppliers
    ]


def _pareto_front(configs: list[dict]) -> list[dict]:
    """
    Extract Pareto-optimal (minimize cost, maximize ESG) points from sample configs.
    A point is Pareto-optimal if no other point is simultaneously cheaper AND higher ESG.
    """
    if not configs:
        return []
    pareto = []
    for i, p in enumerate(configs):
        dominated = any(
            c["cost"] <= p["cost"] and c["esg"] >= p["esg"] and (c["cost"] < p["cost"] or c["esg"] > p["esg"])
            for j, c in enumerate(configs)
            if j != i
        )
        if not dominated:
            pareto.append({"cost": p["cost"], "esg_score": p["esg"], "index": i})
    return sorted(pareto, key=lambda x: x["cost"])[:10]
