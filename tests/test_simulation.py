"""
Simulation tests: the allocator against an exact LP oracle, then the engine.

The allocator is the piece most worth testing hard - it replaced a per-iteration
CBC subprocess call with a vectorised Lagrangian solve, so "is it still exactly
optimal?" is the question that matters. PuLP is used purely as the oracle and is
skipped when unavailable; nothing at runtime depends on it.
"""

import numpy as np
import pytest

from orchestrator.simulation.allocator import greedy_fill, is_feasible, solve_batch
from orchestrator.simulation.engine import run_scenario
from orchestrator.simulation.scenarios import SCENARIO_TEMPLATES, select_relevant_scenarios

pulp = pytest.importorskip("pulp", reason="PuLP is only needed as a test oracle")


def _suppliers(cost, cap, esg):
    return [
        {"id": f"s{i:02d}", "name": f"Supplier {i}", "country_code": "XX",
         "capacity_units": float(cap[i]), "unit_cost_usd": float(cost[i]),
         "esg_score": float(esg[i])}
        for i in range(len(cost))
    ]


def _routes(n, cost_per_unit=0.0, affected=False):
    return [
        {"id": f"r{i:02d}", "origin_supplier_id": f"s{i:02d}", "cost_per_unit": cost_per_unit,
         "transit_days": 20, "co2_kg_per_unit": 1.0, "through_affected_country": affected}
        for i in range(n)
    ]


# -- allocator ----------------------------------------------------------------


def test_greedy_fill_uses_cheapest_first():
    cost = np.array([[9.0, 1.0, 5.0]])
    cap = np.array([[100.0, 40.0, 100.0]])
    alloc = greedy_fill(cost, cap, np.array([60.0]))

    assert alloc[0, 1] == pytest.approx(40.0)   # cheapest, filled to capacity
    assert alloc[0, 2] == pytest.approx(20.0)   # next cheapest takes the remainder
    assert alloc[0, 0] == pytest.approx(0.0)    # dearest untouched


def test_greedy_fill_never_exceeds_capacity_or_demand():
    rng = np.random.default_rng(0)
    cost = rng.uniform(1, 50, (200, 8))
    cap = rng.uniform(10, 500, (200, 8))
    demand = rng.uniform(100, 2000, 200)

    alloc = greedy_fill(cost, cap, demand)
    assert (alloc <= cap + 1e-9).all()
    assert (alloc >= -1e-9).all()

    feasible = is_feasible(cap, demand)
    served = alloc.sum(axis=1)
    assert served[feasible] == pytest.approx(demand[feasible], rel=1e-9)


@pytest.mark.parametrize("min_esg", [0.0, 40.0, 60.0, 75.0])
def test_allocator_matches_pulp_optimum(min_esg):
    """The vectorised solve must equal the LP optimum, not merely approach it."""
    rng = np.random.default_rng(42)

    for _ in range(12):
        n = 10
        cost = rng.uniform(5, 90, n)
        cap = rng.uniform(1_000, 40_000, n)
        esg = rng.uniform(20, 95, n)
        demand = float(rng.uniform(5_000, cap.sum() * 0.9))

        batch = solve_batch(cost[None, :], cap[None, :], esg, np.array([demand]),
                            min_esg_score=min_esg)

        from orchestrator.simulation.optimizer import solve_routing_lp

        lp = solve_routing_lp(_suppliers(cost, cap, esg), _routes(n), demand, min_esg_score=min_esg)

        if not lp.feasible:
            assert not batch.feasible[0]
            continue

        assert batch.feasible[0]
        # CBC carries its own tolerance, so compare at 1e-4 relative, not exactly.
        assert batch.total_cost[0] == pytest.approx(lp.total_cost, rel=1e-4)


def test_esg_floor_is_actually_enforced():
    """The floor must bind. The old engine never passed it through at all."""
    cost = np.array([1.0, 50.0])          # cheap+dirty, dear+clean
    cap = np.array([10_000.0, 10_000.0])
    esg = np.array([10.0, 90.0])
    demand = np.array([5_000.0])

    free = solve_batch(cost[None, :], cap[None, :], esg, demand)
    assert free.esg_score[0] == pytest.approx(10.0)      # all from the dirty supplier

    floored = solve_batch(cost[None, :], cap[None, :], esg, demand, min_esg_score=50.0)
    assert floored.esg_score[0] == pytest.approx(50.0, abs=1e-6)
    assert floored.total_cost[0] > free.total_cost[0]    # buying ESG costs money
    # The floor binds exactly, never overshoots into needless expense.
    assert floored.allocation[0].sum() == pytest.approx(5_000.0)


def test_allocator_reports_infeasible_when_capacity_short():
    batch = solve_batch(
        np.array([[10.0, 12.0]]), np.array([[100.0, 100.0]]), np.array([50.0, 50.0]),
        np.array([500.0]),
    )
    assert not batch.feasible[0]


def test_unreachable_esg_floor_is_infeasible():
    """No allocation can average 90 when the best supplier scores 60."""
    batch = solve_batch(
        np.array([[10.0, 12.0]]), np.array([[9_000.0, 9_000.0]]), np.array([40.0, 60.0]),
        np.array([5_000.0]), min_esg_score=90.0,
    )
    assert not batch.feasible[0]


# -- engine -------------------------------------------------------------------


def _demo_inputs(n=6):
    rng = np.random.default_rng(7)
    cost = rng.uniform(10, 60, n)
    cap = np.full(n, 50_000.0)
    esg = rng.uniform(40, 90, n)
    return _suppliers(cost, cap, esg), _routes(n, cost_per_unit=2.0)


def test_run_scenario_shapes_and_percentile_ordering():
    suppliers, routes = _demo_inputs()
    result = run_scenario(SCENARIO_TEMPLATES["china_tariff_25pct"], suppliers, routes,
                          demand_units=100_000, n_iterations=500, seed=1)

    assert result.iterations == 500
    assert result.cost_p5 <= result.cost_p50 <= result.cost_p95
    assert 0.0 <= result.risk_score <= 1.0
    assert 0.0 <= result.service_level_pct <= 100.0
    assert sum(result.cost_histogram["counts"]) == 500
    assert len(result.cost_histogram["centres"]) == len(result.cost_histogram["counts"])


def test_run_scenario_is_reproducible_for_a_seed():
    suppliers, routes = _demo_inputs()
    kwargs = dict(scenario=SCENARIO_TEMPLATES["sea_typhoon_season"], suppliers=suppliers,
                  routes=routes, demand_units=80_000, n_iterations=400, seed=99)
    assert run_scenario(**kwargs).cost_mean == run_scenario(**kwargs).cost_mean


def test_port_closure_raises_cost_versus_calm_baseline():
    suppliers, routes = _demo_inputs()
    routes = [{**r, "through_affected_country": True} for r in routes]
    # Give every supplier an unaffected fallback lane so demand stays servable.
    routes += [
        {"id": f"alt{i}", "origin_supplier_id": f"s{i:02d}", "cost_per_unit": 25.0,
         "transit_days": 40, "co2_kg_per_unit": 3.0, "through_affected_country": False}
        for i in range(6)
    ]

    calm = run_scenario({"id": "calm", "name": "Calm", "event_type": "none"},
                        suppliers, routes, demand_units=60_000, n_iterations=400, seed=5)
    strike = run_scenario(SCENARIO_TEMPLATES["west_coast_port_strike"],
                          suppliers, routes, demand_units=60_000, n_iterations=400, seed=5)

    assert strike.cost_mean > calm.cost_mean
    assert strike.delay_mean >= calm.delay_mean


def test_suez_closure_adds_transit_days():
    suppliers, routes = _demo_inputs()
    routes = [{**r, "through_affected_country": True} for r in routes]

    calm = run_scenario({"id": "calm", "name": "Calm", "event_type": "none"},
                        suppliers, routes, demand_units=60_000, n_iterations=300, seed=2)
    suez = run_scenario(SCENARIO_TEMPLATES["suez_canal_blockage"],
                        suppliers, routes, demand_units=60_000, n_iterations=300, seed=2)

    assert suez.delay_mean > calm.delay_mean


def test_efficient_frontier_is_monotonically_more_expensive():
    """Raising the ESG floor can never make the optimum cheaper."""
    suppliers, routes = _demo_inputs(8)
    result = run_scenario(SCENARIO_TEMPLATES["china_tariff_25pct"], suppliers, routes,
                          demand_units=100_000, n_iterations=400, min_esg_score=50.0, seed=11)

    frontier = result.efficient_frontier
    assert len(frontier) >= 3
    costs = [p["cost_mean"] for p in frontier]
    assert costs == sorted(costs), "cost must not fall as the ESG floor rises"
    floors = [p["min_esg_score"] for p in frontier]
    assert floors == sorted(floors)
    for point in frontier:
        assert point["achieved_esg"] >= point["min_esg_score"] - 1e-3


def test_supplier_mix_shares_sum_to_one_hundred():
    suppliers, routes = _demo_inputs()
    result = run_scenario(SCENARIO_TEMPLATES["china_tariff_25pct"], suppliers, routes,
                          demand_units=90_000, n_iterations=300, seed=4)
    assert sum(m["share_pct"] for m in result.supplier_mix) == pytest.approx(100.0, abs=0.5)


def test_run_scenario_rejects_empty_supplier_list():
    with pytest.raises(ValueError):
        run_scenario(SCENARIO_TEMPLATES["china_tariff_25pct"], [], [], 1000, 10)


# -- scenario selection -------------------------------------------------------


def test_scenario_selection_reacts_to_country_risk():
    selected = select_relevant_scenarios({"CN": 0.9}, [])
    assert any(s["id"] == "china_tariff_25pct" for s in selected)


def test_scenario_selection_always_returns_at_least_two():
    assert len(select_relevant_scenarios({}, [])) >= 2


def test_scenario_selection_matches_event_text():
    events = [{"event_type": "geopolitical", "description": "Suez transits down", "title": ""}]
    selected = select_relevant_scenarios({}, events)
    assert any(s["id"] == "suez_canal_blockage" for s in selected)
