"""
PuLP Linear Program: minimize total landed cost subject to demand + ESG constraints.

Decision variables: x[supplier_id] = units allocated from supplier i
Objective: minimize Σ(x_i × (unit_cost_i + route_cost_i))
Constraints:
  Σ(x_i) >= demand_units        — fulfill demand
  x_i <= capacity_i             — supplier capacity
  x_i >= 0                      — non-negativity
  (optional) weighted ESG ≥ min_esg_score

Typical solve time: <50ms for 20 suppliers (CBC solver bundled with PuLP).
"""

import logging
from dataclasses import dataclass, field

import pulp

logger = logging.getLogger(__name__)

# Suppress PuLP's verbose CBC output
pulp.LpSolverDefault.msg = 0


@dataclass
class LPResult:
    total_cost: float
    avg_delay_days: float
    avg_co2_per_unit: float
    config: dict[str, float] = field(default_factory=dict)  # {supplier_id: units}
    feasible: bool = True
    esg_score: float = 0.0


def solve_routing_lp(
    suppliers: list[dict],
    routes: list[dict],
    demand_units: int,
    min_esg_score: float = 0.0,
) -> LPResult:
    """
    Solve the multi-supplier routing LP.

    suppliers: list of supplier dicts with keys id, capacity_units, unit_cost_usd, esg_score
    routes: list of route dicts with keys origin_supplier_id, cost_per_unit, transit_days,
            co2_kg_per_unit, through_affected_country
    demand_units: total units to fulfill
    min_esg_score: minimum weighted portfolio ESG (0 = no constraint)
    """
    if not suppliers:
        return LPResult(total_cost=float("inf"), avg_delay_days=999, avg_co2_per_unit=99, feasible=False)

    prob = pulp.LpProblem("supply_chain_routing", pulp.LpMinimize)

    # Best (cheapest active) route cost per supplier
    route_cost: dict[str, float] = {}
    route_delay: dict[str, float] = {}
    route_co2: dict[str, float] = {}
    for s in suppliers:
        sid = s["id"]
        supplier_routes = [r for r in routes if r.get("origin_supplier_id") == sid]
        active_routes = [r for r in supplier_routes if not r.get("through_affected_country", False)]
        if not active_routes:
            active_routes = supplier_routes  # all routes may be affected — use all
        if active_routes:
            best = min(active_routes, key=lambda r: r.get("cost_per_unit", 9999))
            route_cost[sid] = float(best.get("cost_per_unit", 0))
            route_delay[sid] = float(best.get("transit_days", 30))
            route_co2[sid] = float(best.get("co2_kg_per_unit", 1.0))
        else:
            route_cost[sid] = 0.0
            route_delay[sid] = 30.0
            route_co2[sid] = 1.0

    # Decision variables
    x = {
        s["id"]: pulp.LpVariable(
            f"x_{s['id'][:8]}",
            lowBound=0,
            upBound=float(s.get("capacity_units") or 999_999),
        )
        for s in suppliers
    }

    # Objective: minimize total landed cost
    prob += pulp.lpSum(
        x[s["id"]] * (float(s.get("unit_cost_usd") or 0) + route_cost[s["id"]])
        for s in suppliers
    )

    # Demand fulfillment constraint
    # Use equality when an ESG floor is set to prevent LP from satisfying the
    # ESG sum constraint by over-allocating a low-ESG supplier beyond demand.
    total_supply = pulp.lpSum(x[s["id"]] for s in suppliers)
    if min_esg_score > 0:
        prob += total_supply == demand_units
    else:
        prob += total_supply >= demand_units

    # Optional ESG floor: weighted avg ESG ≥ min_esg_score
    # Constraint: sum(x_i * esg_i) >= min_esg_score * demand_units
    # With the equality demand constraint above this correctly enforces the per-unit average.
    if min_esg_score > 0:
        prob += (
            pulp.lpSum(
                x[s["id"]] * float(s.get("esg_score") or 0) for s in suppliers
            )
            >= min_esg_score * demand_units
        )

    # Solve with CBC (bundled, no extra system deps)
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=5)
    status = prob.solve(solver)

    if pulp.LpStatus[prob.status] != "Optimal":
        logger.warning("LP status: %s — returning infeasible result", pulp.LpStatus[prob.status])
        return LPResult(total_cost=float("inf"), avg_delay_days=999, avg_co2_per_unit=99, feasible=False)

    allocation = {s["id"]: max(0.0, pulp.value(x[s["id"]]) or 0.0) for s in suppliers}
    total_units = sum(allocation.values()) or 1

    avg_delay = sum(allocation[s["id"]] * route_delay[s["id"]] for s in suppliers) / total_units
    avg_co2 = sum(allocation[s["id"]] * route_co2[s["id"]] for s in suppliers) / total_units
    weighted_esg = sum(
        allocation[s["id"]] * float(s.get("esg_score") or 0) for s in suppliers
    ) / total_units

    return LPResult(
        total_cost=float(pulp.value(prob.objective) or 0),
        avg_delay_days=avg_delay,
        avg_co2_per_unit=avg_co2,
        config=allocation,
        feasible=True,
        esg_score=weighted_esg,
    )
