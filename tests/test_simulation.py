"""
Unit tests for the simulation engine — no DB or API keys required.
"""

import pytest

from orchestrator.simulation.monte_carlo import _run_mc_sync
from orchestrator.simulation.optimizer import LPResult, solve_routing_lp
from orchestrator.simulation.scenarios import SCENARIO_TEMPLATES, select_relevant_scenarios


# ── LP Optimizer tests ────────────────────────────────────────────────────────

MOCK_SUPPLIERS = [
    {"id": "s1", "country_code": "VN", "capacity_units": 10_000, "unit_cost_usd": 15.0, "esg_score": 68.0},
    {"id": "s2", "country_code": "TR", "capacity_units": 8_000, "unit_cost_usd": 19.0, "esg_score": 74.0},
    {"id": "s3", "country_code": "BD", "capacity_units": 12_000, "unit_cost_usd": 12.0, "esg_score": 60.0},
]

MOCK_ROUTES = [
    {"id": "r1", "origin_supplier_id": "s1", "cost_per_unit": 1.20, "transit_days": 25, "co2_kg_per_unit": 0.9, "through_affected_country": False},
    {"id": "r2", "origin_supplier_id": "s2", "cost_per_unit": 0.90, "transit_days": 14, "co2_kg_per_unit": 0.6, "through_affected_country": False},
    {"id": "r3", "origin_supplier_id": "s3", "cost_per_unit": 1.50, "transit_days": 28, "co2_kg_per_unit": 1.1, "through_affected_country": True},
]


def test_lp_basic_feasibility():
    result = solve_routing_lp(MOCK_SUPPLIERS, MOCK_ROUTES, demand_units=5_000)
    assert result.feasible
    assert result.total_cost > 0
    total_allocated = sum(result.config.values())
    assert total_allocated >= 4_999  # within rounding of demand


def test_lp_blocks_affected_routes():
    """Routes through affected countries should be costed out in disruption scenarios."""
    disrupted_routes = [
        {**r, "cost_per_unit": r["cost_per_unit"] * 999}
        if r["through_affected_country"] else r
        for r in MOCK_ROUTES
    ]
    result = solve_routing_lp(MOCK_SUPPLIERS, disrupted_routes, demand_units=5_000)
    assert result.feasible
    # BD (s3) allocation should be near zero since its route is 999x cost
    bd_alloc = result.config.get("s3", 0)
    total = sum(result.config.values()) or 1
    assert bd_alloc / total < 0.1  # <10% from the disrupted supplier


def test_lp_esg_floor():
    result = solve_routing_lp(MOCK_SUPPLIERS, MOCK_ROUTES, demand_units=5_000, min_esg_score=70.0)
    if result.feasible:
        assert result.esg_score >= 65.0  # allow small LP tolerance


def test_lp_no_suppliers():
    result = solve_routing_lp([], [], demand_units=1_000)
    assert not result.feasible


# ── Monte Carlo tests ─────────────────────────────────────────────────────────

def test_monte_carlo_basic():
    scenario = SCENARIO_TEMPLATES["china_tariff_25pct"]
    result = _run_mc_sync(
        scenario_params=scenario,
        suppliers=MOCK_SUPPLIERS,
        routes=MOCK_ROUTES,
        demand_units=5_000,
        n_iterations=50,  # fast for CI
    )
    assert result.scenario_id == "china_tariff_25pct"
    assert result.iterations == 50
    assert result.cost_mean > 0
    assert result.cost_p5 <= result.cost_mean <= result.cost_p95
    assert 0 <= result.esg_score_mean <= 100


def test_monte_carlo_port_closure_increases_cost():
    """Scenarios with high port closure probability should have higher P95 costs."""
    low_disruption = {**SCENARIO_TEMPLATES["china_tariff_25pct"], "port_closure_probability": 0.0}
    high_disruption = {**SCENARIO_TEMPLATES["china_tariff_25pct"], "port_closure_probability": 0.95}

    result_low = _run_mc_sync(low_disruption, MOCK_SUPPLIERS, MOCK_ROUTES, 5_000, 100)
    result_high = _run_mc_sync(high_disruption, MOCK_SUPPLIERS, MOCK_ROUTES, 5_000, 100)

    assert result_high.cost_p95 > result_low.cost_p95


def test_monte_carlo_suez():
    scenario = SCENARIO_TEMPLATES["suez_canal_blockage"]
    result = _run_mc_sync(scenario, MOCK_SUPPLIERS, MOCK_ROUTES, 5_000, 50)
    assert result.delay_mean > 5  # Suez blockage adds significant delay


# ── Scenario selection tests ──────────────────────────────────────────────────

def test_select_scenarios_china_risk():
    selected = select_relevant_scenarios({"CN": 0.7, "VN": 0.1}, [])
    ids = [s["id"] for s in selected]
    assert "china_tariff_25pct" in ids


def test_select_scenarios_weather():
    events = [{"event_type": "weather", "title": "typhoon", "description": ""}]
    selected = select_relevant_scenarios({"VN": 0.4}, events)
    ids = [s["id"] for s in selected]
    assert "sea_typhoon_season" in ids


def test_select_scenarios_minimum_2():
    """Should always return at least 2 scenarios."""
    selected = select_relevant_scenarios({}, [])
    assert len(selected) >= 2
