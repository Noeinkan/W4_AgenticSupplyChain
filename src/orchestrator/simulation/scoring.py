"""
Scenario scoring utilities used by the recommender to rank simulation results.
"""


def score_scenario_risk(sim_result: dict) -> float:
    """
    Composite risk score 0–1 for a simulation result dict.
    Higher = riskier. Weights: cost variance 40%, delay 30%, infeasibility 30%.
    """
    cost_mean = sim_result.get("cost_mean", 0) or 1
    cost_p95 = sim_result.get("cost_p95", 0) or cost_mean
    delay = sim_result.get("delay_mean", 0)
    infeasible_pct = sim_result.get("infeasible_pct", 0)

    cost_variance_score = min(1.0, (cost_p95 - cost_mean) / (cost_mean + 1))
    delay_score = min(1.0, delay / 60.0)  # 60 days = max score
    infeasible_score = min(1.0, infeasible_pct / 100.0)

    return round(
        0.40 * cost_variance_score + 0.30 * delay_score + 0.30 * infeasible_score,
        4,
    )


def rank_scenarios(simulation_results: dict[str, dict]) -> list[tuple[str, dict, float]]:
    """
    Rank scenarios by composite risk score (highest risk first).
    Returns list of (scenario_id, result_dict, risk_score) tuples.
    """
    ranked = []
    for sid, result in simulation_results.items():
        risk = score_scenario_risk(result)
        ranked.append((sid, result, risk))
    return sorted(ranked, key=lambda x: x[2], reverse=True)
