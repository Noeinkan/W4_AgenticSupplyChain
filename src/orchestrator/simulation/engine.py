"""
Monte Carlo disruption engine.

Samples every stochastic parameter for all iterations up front, builds the
resulting cost/capacity matrices, and solves the whole batch in one call to
:mod:`orchestrator.simulation.allocator`. Nothing is looped per iteration, so a
1,000-iteration scenario finishes in milliseconds instead of minutes.

Model per iteration:
  * tariff shock       - multiplies cost on routes through the affected country
  * port closure       - blocks those routes outright (Bernoulli draw)
  * weather delay      - multiplies transit days, plus fixed re-routing days
  * demand shock       - scales the units that must be sourced
  * capacity reduction - cuts supplier capacity in the affected country

Each supplier is costed on its cheapest *adjusted* route for that iteration, so
a tariff or closure can flip a supplier onto a different lane mid-simulation.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field

import numpy as np

from orchestrator.simulation.allocator import solve_batch, weighted_average

_INFEASIBLE_DELAY_DAYS = 999.0
_INFEASIBLE_CO2 = 999.0


@dataclass
class ScenarioResult:
    """Aggregate statistics for one scenario across all Monte Carlo iterations."""

    scenario_id: str
    scenario_name: str
    event_type: str
    iterations: int

    cost_mean: float
    cost_p5: float
    cost_p50: float
    cost_p95: float
    cost_std: float
    cost_per_unit_mean: float

    delay_mean: float
    delay_p95: float
    co2_mean: float

    risk_score: float
    esg_score_mean: float
    service_level_pct: float
    infeasible_pct: float

    cost_histogram: dict = field(default_factory=dict)
    pareto_front: list[dict] = field(default_factory=list)
    efficient_frontier: list[dict] = field(default_factory=list)
    best_config: dict = field(default_factory=dict)
    supplier_mix: list[dict] = field(default_factory=list)
    baseline_cost_mean: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _supplier_arrays(suppliers: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    ids = [s["id"] for s in suppliers]
    capacity = np.array([float(s.get("capacity_units") or 10_000) for s in suppliers])
    unit_cost = np.array([float(s.get("unit_cost_usd") or 0.0) for s in suppliers])
    esg = np.array([float(s.get("esg_score") or 50.0) for s in suppliers])
    return capacity, unit_cost, esg, ids


def _route_arrays(
    suppliers: list[dict], routes: list[dict]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Pack routes into (n_suppliers, max_routes) matrices with a validity mask."""
    by_supplier: dict[str, list[dict]] = {s["id"]: [] for s in suppliers}
    for r in routes:
        sid = r.get("origin_supplier_id")
        if sid in by_supplier:
            by_supplier[sid].append(r)

    width = max((len(v) for v in by_supplier.values()), default=1) or 1
    n = len(suppliers)

    cost = np.full((n, width), np.inf)
    days = np.full((n, width), 30.0)
    co2 = np.full((n, width), 1.0)
    affected = np.zeros((n, width), dtype=bool)
    valid = np.zeros((n, width), dtype=bool)

    for i, s in enumerate(suppliers):
        for j, r in enumerate(by_supplier[s["id"]]):
            cost[i, j] = float(r.get("cost_per_unit") or 0.0)
            days[i, j] = float(r.get("transit_days") or 30.0)
            co2[i, j] = float(r.get("co2_kg_per_unit") or 1.0)
            affected[i, j] = bool(r.get("through_affected_country", False))
            valid[i, j] = True
        if not by_supplier[s["id"]]:
            # Supplier with no modelled lane: treat as a zero-cost direct lane.
            cost[i, 0] = 0.0
            valid[i, 0] = True

    return cost, days, co2, affected, valid


def run_scenario(
    scenario: dict,
    suppliers: list[dict],
    routes: list[dict],
    demand_units: int,
    n_iterations: int = 1000,
    min_esg_score: float = 0.0,
    seed: int | None = None,
) -> ScenarioResult:
    """Run one scenario end to end. Pure numpy, no I/O - safe to call in a thread."""
    if not suppliers:
        raise ValueError("run_scenario requires at least one supplier")

    rng = np.random.default_rng(seed)
    m = int(n_iterations)
    n = len(suppliers)

    capacity, unit_cost, esg, ids = _supplier_arrays(suppliers)
    r_cost, r_days, r_co2, r_affected, r_valid = _route_arrays(suppliers, routes)

    # Sample stochastic parameters for every iteration at once.
    tariff = _uniform(rng, scenario.get("tariff_shock", {}).get("rate_range", [0.0, 0.0]), m)
    delay_mult = _uniform(
        rng, scenario.get("weather_impact", {}).get("delay_multiplier_range", [1.0, 1.0]), m
    )
    demand_shift = _uniform(rng, scenario.get("demand_shock", {}).get("change_range", [0.0, 0.0]), m)
    cap_cut = _uniform(rng, scenario.get("capacity_reduction", {}).get("range", [0.0, 0.0]), m)
    closed = rng.random(m) < float(scenario.get("port_closure_probability", 0.0))
    extra_days = float(scenario.get("extra_transit_days", 0.0))
    cut_country = scenario.get("capacity_reduction", {}).get("country", "NONE")

    # Apply the disruption to every route, per iteration. Shapes: (m, n, width)
    aff = r_affected[None, :, :]
    blocked = aff & closed[:, None, None]
    surcharge = np.where(aff, 1.0 + tariff[:, None, None], 1.0)

    lane_cost = r_cost[None, :, :] * surcharge
    lane_cost = np.where(blocked, np.inf, lane_cost)
    lane_cost = np.where(r_valid[None, :, :], lane_cost, np.inf)

    lane_days = np.where(
        aff, r_days[None, :, :] * delay_mult[:, None, None] + extra_days, r_days[None, :, :]
    )

    # Cheapest surviving lane per supplier per iteration.
    all_blocked = ~np.isfinite(lane_cost).any(axis=2)
    safe_cost = np.where(np.isfinite(lane_cost), lane_cost, np.inf)
    pick = np.argmin(safe_cost, axis=2)
    route_cost = np.take_along_axis(safe_cost, pick[:, :, None], axis=2)[:, :, 0]
    route_days = np.take_along_axis(lane_days, pick[:, :, None], axis=2)[:, :, 0]
    route_co2 = np.take_along_axis(
        np.broadcast_to(r_co2[None, :, :], lane_cost.shape), pick[:, :, None], axis=2
    )[:, :, 0]

    eff_capacity = np.broadcast_to(capacity, (m, n)).copy()
    if cut_country != "NONE":
        in_country = np.array(
            [cut_country == "ALL" or s.get("country_code") == cut_country for s in suppliers]
        )
        eff_capacity = eff_capacity * np.where(in_country[None, :], 1.0 - cap_cut[:, None], 1.0)

    # A supplier whose every lane is blocked contributes no capacity this iteration.
    eff_capacity = np.where(all_blocked, 0.0, eff_capacity)
    route_cost = np.where(all_blocked, 0.0, route_cost)
    route_days = np.where(all_blocked, 0.0, route_days)

    landed_cost = unit_cost[None, :] + route_cost
    demand = np.maximum(1.0, demand_units * (1.0 + demand_shift))

    batch = solve_batch(landed_cost, eff_capacity, esg, demand, min_esg_score=min_esg_score)

    # Undisrupted reference run, for the "cost of the disruption" delta.
    calm_cost = np.where(r_valid, r_cost, np.inf).min(axis=1)
    baseline = solve_batch(
        (unit_cost + calm_cost)[None, :],
        capacity[None, :],
        esg,
        np.array([float(demand_units)]),
        min_esg_score=min_esg_score,
    )

    feasible = batch.feasible
    n_feasible = int(feasible.sum())

    cost = batch.total_cost.copy()
    delay = weighted_average(batch.allocation, route_days)
    co2 = weighted_average(batch.allocation, route_co2)
    esg_iter = batch.esg_score.copy()

    if n_feasible < m:
        # Unserved demand is penalised at three times the feasible mean rather
        # than propagated as inf, so percentiles stay interpretable.
        penalty = float(np.mean(cost[feasible])) * 3.0 if n_feasible else float(demand_units * 999)
        cost = np.where(feasible, cost, penalty)
        delay = np.where(feasible, delay, _INFEASIBLE_DELAY_DAYS)
        co2 = np.where(feasible, co2, _INFEASIBLE_CO2)
        esg_iter = np.where(feasible, esg_iter, 0.0)

    served = batch.allocation.sum(axis=1) / np.maximum(demand, 1.0)

    best_idx = int(np.argmin(np.where(feasible, cost, np.inf))) if n_feasible else 0
    best_alloc = batch.allocation[best_idx]

    return ScenarioResult(
        scenario_id=scenario["id"],
        scenario_name=scenario.get("name", scenario["id"]),
        event_type=scenario.get("event_type", "unknown"),
        iterations=m,
        cost_mean=float(np.mean(cost)),
        cost_p5=float(np.percentile(cost, 5)),
        cost_p50=float(np.percentile(cost, 50)),
        cost_p95=float(np.percentile(cost, 95)),
        cost_std=float(np.std(cost)),
        cost_per_unit_mean=float(np.mean(cost / np.maximum(demand, 1.0))),
        delay_mean=float(np.mean(delay)),
        delay_p95=float(np.percentile(delay, 95)),
        co2_mean=float(np.mean(co2)),
        risk_score=_risk_score(cost, delay, feasible),
        esg_score_mean=float(np.mean(esg_iter)),
        service_level_pct=float(np.mean(np.minimum(served, 1.0)) * 100.0),
        infeasible_pct=round(100.0 * (m - n_feasible) / m, 2),
        cost_histogram=_histogram(cost),
        pareto_front=_pareto_front(cost, esg_iter, feasible),
        efficient_frontier=_efficient_frontier(
            landed_cost, eff_capacity, esg, demand, rng, min_esg_score
        ),
        best_config={ids[i]: float(best_alloc[i]) for i in range(n) if best_alloc[i] > 1e-6},
        supplier_mix=_supplier_mix(batch.allocation, feasible, suppliers, ids),
        baseline_cost_mean=float(baseline.total_cost[0]) if baseline.feasible[0] else 0.0,
    )


async def run_scenario_async(*args, **kwargs) -> ScenarioResult:
    """Off-thread wrapper so a large batch never blocks the event loop."""
    return await asyncio.to_thread(run_scenario, *args, **kwargs)


def _uniform(rng: np.random.Generator, rng_range: list, m: int) -> np.ndarray:
    lo, hi = (list(rng_range) + [0.0, 0.0])[:2]
    if hi < lo:
        lo, hi = hi, lo
    if hi == lo:
        return np.full(m, float(lo))
    return rng.uniform(float(lo), float(hi), m)


def _risk_score(cost: np.ndarray, delay: np.ndarray, feasible: np.ndarray) -> float:
    """0-1 composite: cost tail dispersion 40%, delay 30%, unserved demand 30%."""
    mean = float(np.mean(cost)) or 1.0
    p95 = float(np.percentile(cost, 95))
    tail = min(1.0, max(0.0, (p95 - mean) / mean))
    delay_score = min(1.0, float(np.mean(delay)) / 60.0)
    infeasible = 1.0 - float(np.mean(feasible))
    return round(0.40 * tail + 0.30 * delay_score + 0.30 * infeasible, 4)


def _histogram(cost: np.ndarray, bins: int = 24) -> dict:
    counts, edges = np.histogram(cost, bins=bins)
    return {
        "counts": counts.tolist(),
        "edges": edges.tolist(),
        "centres": ((edges[:-1] + edges[1:]) / 2).tolist(),
    }


def _pareto_front(
    cost: np.ndarray, esg: np.ndarray, feasible: np.ndarray, limit: int = 40
) -> list[dict]:
    """Non-dominated (min cost, max ESG) iterations, cheapest first."""
    idx = np.flatnonzero(feasible)
    if idx.size == 0:
        return []
    c, e = cost[idx], esg[idx]
    order = np.argsort(c, kind="stable")
    front, best_esg = [], -np.inf
    for k in order:
        if e[k] > best_esg + 1e-9:
            best_esg = e[k]
            front.append({"cost": float(c[k]), "esg_score": float(e[k]), "iteration": int(idx[k])})
    step = max(1, len(front) // limit)
    return front[::step][:limit]


def _efficient_frontier(
    cost: np.ndarray,
    capacity: np.ndarray,
    esg: np.ndarray,
    demand: np.ndarray,
    rng: np.random.Generator,
    current_floor: float,
    levels: int = 14,
    sample: int = 250,
) -> list[dict]:
    """Cost of buying ESG, swept across the achievable range of the floor.

    The per-iteration Pareto front collapses to a single point whenever an ESG
    floor binds - every iteration lands on the constraint. The trade-off worth
    showing is what a *higher* floor would cost, so this re-solves the batch at
    a series of floor levels and reports mean and P95 cost at each.

    Runs on a random subsample of iterations to stay in the tens of milliseconds
    while still pricing the floor under uncertainty rather than at the mean.
    """
    m = cost.shape[0]
    if m == 0:
        return []

    idx = rng.choice(m, size=min(sample, m), replace=False)
    c, cap, d = cost[idx], capacity[idx], demand[idx]

    # Highest floor that is reachable: allocate greedily by ESG instead of cost.
    from orchestrator.simulation.allocator import greedy_fill

    richest = greedy_fill(-np.broadcast_to(esg, c.shape), cap, d)
    units = richest.sum(axis=1)
    ceiling = float(np.median(np.einsum("ij,j->i", richest, esg) / np.where(units > 0, units, 1.0)))

    floor_lo = float(np.min(esg))
    if ceiling - floor_lo < 1e-6:
        return []

    frontier = []
    for raw_level in np.linspace(floor_lo, ceiling * 0.999, levels):
        # Round before solving, so the floor reported is exactly the one enforced.
        level = round(float(raw_level), 2)
        batch = solve_batch(c, cap, esg, d, min_esg_score=level)
        if not batch.feasible.any():
            continue
        costs = batch.total_cost[batch.feasible]
        frontier.append({
            "min_esg_score": level,
            "cost_mean": float(np.mean(costs)),
            "cost_p95": float(np.percentile(costs, 95)),
            "achieved_esg": float(np.mean(batch.esg_score[batch.feasible])),
            "feasible_pct": round(100.0 * float(np.mean(batch.feasible)), 1),
            "is_current": bool(abs(level - current_floor) < (ceiling - floor_lo) / (2 * levels)),
        })

    return _trim_frontier(frontier, current_floor)


def _trim_frontier(frontier: list[dict], current_floor: float, blowup: float = 4.0) -> list[dict]:
    """Drop the runaway tail so the decision-relevant range stays readable.

    Past a certain floor the optimiser is forced onto whatever supplier has the
    highest ESG at any price, and cost goes near-vertical. Plotting the whole
    sweep flattens the part anyone actually chooses between into a straight line,
    so keep one point past the blow-up (which shows the cliff) and drop the rest.
    The run's own floor is always retained.
    """
    if len(frontier) < 3:
        return frontier

    base = frontier[0]["cost_mean"] or 1.0
    keep = []
    for point in frontier:
        keep.append(point)
        past_cliff = point["cost_mean"] > base * blowup
        if past_cliff and len(keep) >= 3 and point["min_esg_score"] > current_floor:
            break
    return keep


def _supplier_mix(
    allocation: np.ndarray, feasible: np.ndarray, suppliers: list[dict], ids: list[str]
) -> list[dict]:
    """Mean allocation share per supplier across feasible iterations."""
    if not feasible.any():
        return []
    alloc = allocation[feasible]
    totals = alloc.sum(axis=0)
    grand = totals.sum() or 1.0
    mix = [
        {
            "supplier_id": ids[i],
            "name": suppliers[i].get("name", ids[i]),
            "country_code": suppliers[i].get("country_code", "??"),
            "esg_score": float(suppliers[i].get("esg_score") or 0.0),
            "mean_units": float(alloc[:, i].mean()),
            "share_pct": round(100.0 * totals[i] / grand, 2),
        }
        for i in range(len(ids))
    ]
    mix.sort(key=lambda d: d["share_pct"], reverse=True)
    return [m for m in mix if m["share_pct"] > 0.01]
