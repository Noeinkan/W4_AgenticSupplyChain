"""
RecommenderAgent node: ranks simulation results and generates actionable recommendations.

For each scenario result, uses the Pareto front (cost vs. ESG) to identify the
best_config, then asks the LLM to produce a human-readable recommendation with
rec_type, description, cost_delta, risk_delta, and confidence_pct.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from orchestrator.agents.state import SupplyChainState
from orchestrator.esg.calculator import score_portfolio_from_config

logger = logging.getLogger(__name__)

_RECOMMENDER_SYSTEM_PROMPT = """You are a supply chain optimization expert.
Given simulation results for several disruption scenarios, produce the top 3 recommended
actions for the manufacturer.

Each recommendation must have:
- rec_type: one of "reroute", "supplier_switch", "inventory_adj"
- description: 1–2 sentence plain English explanation
- rationale: why this specific action (what scenario it addresses)
- estimated_savings_usd: rough annual cost savings (can be negative = cost increase)
- risk_reduction: qualitative ("high", "medium", "low")
- esg_impact: "improve", "neutral", or "degrade"

Respond ONLY with valid JSON: {"recommendations": [...]}
"""


def _get_llm():
    from orchestrator.config import settings

    if settings.sovereign_mode:
        from langchain_community.chat_models import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
        )
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
        temperature=0,
        max_tokens=1024,
    )


async def run(state: SupplyChainState) -> dict:
    """RecommenderAgent node — returns partial state update."""
    simulation_results = state.get("simulation_results", {})
    scenarios = state.get("scenarios", [])
    profile = state.get("manufacturer_profile", {})

    if not simulation_results:
        logger.warning("Recommender: no simulation results to rank")
        return {"recommendations": [], "selected_recommendation": None}

    # Build a summary of simulation results for the LLM
    scenario_map = {s["id"]: s for s in scenarios}
    results_summary = []
    for sid, result in simulation_results.items():
        scenario = scenario_map.get(sid, {})
        results_summary.append(
            {
                "scenario": scenario.get("name", sid),
                "event_type": scenario.get("event_type", "unknown"),
                "cost_mean_usd": result.get("cost_mean", 0),
                "cost_p95_usd": result.get("cost_p95", 0),
                "delay_mean_days": result.get("delay_mean", 0),
                "esg_score_mean": result.get("esg_score_mean", 0),
                "best_config": result.get("best_config", {}),
            }
        )

    # Ask LLM for recommendations
    recommendations: list[dict] = []
    try:
        llm = _get_llm()
        prompt = (
            f"Manufacturer: {profile.get('name', 'Unknown')} "
            f"({profile.get('industry', 'manufacturing')})\n"
            f"Supplier countries: {profile.get('supplier_countries', [])}\n"
            f"Min ESG requirement: {profile.get('min_esg_score', 50)}\n\n"
            f"Simulation results:\n{json.dumps(results_summary, indent=2)}"
        )
        response = await llm.ainvoke(
            [
                SystemMessage(content=_RECOMMENDER_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
        data = json.loads(response.content)
        raw_recs = data.get("recommendations", [])
    except Exception:
        logger.exception("LLM recommendation generation failed — using heuristic fallback")
        raw_recs = _heuristic_recommendations(results_summary)

    # Enrich each recommendation with numeric scores and ESG delta
    for i, rec in enumerate(raw_recs[:5]):
        best_result = min(
            simulation_results.values(),
            key=lambda r: r.get("cost_mean", float("inf")),
        )
        rec["id"] = f"rec_{i}"
        rec["scenario_id"] = list(simulation_results.keys())[0] if simulation_results else None
        rec["cost_delta_usd"] = rec.pop("estimated_savings_usd", 0)
        rec["risk_delta"] = _risk_label_to_delta(rec.pop("risk_reduction", "medium"))
        rec["esg_delta"] = _esg_label_to_delta(rec.pop("esg_impact", "neutral"))
        rec["confidence_pct"] = max(50.0, min(99.0, 85.0 - i * 10))
        rec["proposed_config"] = best_result.get("best_config", {})
        recommendations.append(rec)

    # Compute ESG projections for the top recommendation
    esg_baseline = state.get("esg_baseline", {})
    esg_projected = {}
    if recommendations:
        top_rec = recommendations[0]
        esg_projected = await score_portfolio_from_config(
            top_rec.get("proposed_config", {}), delta=top_rec.get("esg_delta", 0)
        )

    selected = recommendations[0] if recommendations else None
    logger.info("Recommender: generated %d recommendations", len(recommendations))

    return {
        "recommendations": recommendations,
        "selected_recommendation": selected,
        "esg_baseline": esg_baseline,
        "esg_projected": esg_projected,
        "messages": [HumanMessage(content=f"Generated {len(recommendations)} recommendations.")],
    }


def _risk_label_to_delta(label: str) -> float:
    return {"high": -0.35, "medium": -0.15, "low": -0.05}.get(label.lower(), -0.15)


def _esg_label_to_delta(label: str) -> float:
    return {"improve": 5.0, "neutral": 0.0, "degrade": -5.0}.get(label.lower(), 0.0)


def _heuristic_recommendations(results_summary: list[dict]) -> list[dict]:
    """Fallback when LLM is unavailable: simple rule-based recommendations."""
    if not results_summary:
        return []
    worst = max(results_summary, key=lambda r: r.get("cost_p95_usd", 0))
    return [
        {
            "rec_type": "reroute",
            "description": (
                f"Reroute shipments to avoid disruption scenario '{worst['scenario']}'. "
                f"Expected to reduce P95 cost from ${worst['cost_p95_usd']:,.0f}."
            ),
            "rationale": f"Highest tail-risk scenario: {worst['scenario']}",
            "estimated_savings_usd": worst["cost_p95_usd"] * -0.2,
            "risk_reduction": "medium",
            "esg_impact": "neutral",
        },
        {
            "rec_type": "inventory_adj",
            "description": "Increase safety stock by 2 weeks to buffer against average delays.",
            "rationale": f"Mean delay across scenarios: {worst['delay_mean_days']:.1f} days",
            "estimated_savings_usd": -5000,
            "risk_reduction": "low",
            "esg_impact": "neutral",
        },
    ]
