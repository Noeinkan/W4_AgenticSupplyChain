"""
The six agent nodes, as free functions over a plain state dict.

Both execution engines share these: :class:`orchestrator.pipeline.runner.PipelineRun`
drives them directly, and ``orchestrator.agents.graph`` binds the same functions
into a LangGraph when ``USE_LANGGRAPH=true``. Keeping one implementation is the
point - the previous split let the two drift, and the LangGraph copy had grown a
hard dependency on ``langchain_core`` that broke on a clean install.

Each function mutates ``state`` in place and returns either nothing or a small
piece of telemetry. ``state`` uses the same keys as the LangGraph
``SupplyChainState`` TypedDict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime

from orchestrator.data.catalog import get_catalog
from orchestrator.esg.calculator import score_portfolio
from orchestrator.llm import provider
from orchestrator.simulation.engine import run_scenario_async
from orchestrator.simulation.scenarios import SCENARIO_TEMPLATES, select_relevant_scenarios

logger = logging.getLogger(__name__)

TIER_AUTO = "auto"
TIER_MANAGER = "manager"
TIER_CSUITE = "c_suite"


def escalation_tier(rec: dict) -> tuple[str, int]:
    """(tier, approval window in seconds) for a recommendation."""
    cost = abs(float(rec.get("cost_delta_usd") or 0))
    if rec.get("rec_type") == "supplier_switch":
        return TIER_CSUITE, 48 * 3600
    if cost < 10_000:
        return TIER_AUTO, 0
    if cost < 100_000:
        return TIER_MANAGER, 24 * 3600
    return TIER_CSUITE, 48 * 3600


async def monitor(state: dict, catalog) -> None:
    """Collect relevant events and score country risk."""
    countries = [c.upper() for c in state["manufacturer_profile"].get("supplier_countries", [])] or catalog.countries()
    hs_codes = state["manufacturer_profile"].get("hs_codes", [])

    relevant = [
        e for e in catalog.events
        if not countries or set(e.get("affected_countries", [])) & set(countries)
    ] or catalog.events

    baseline = _heuristic_risk(relevant, countries)
    result = await provider.complete_json(
        _MONITOR_SYSTEM,
        _monitor_prompt(countries, hs_codes, relevant),
        fallback={"country_risks": baseline, "summary": _risk_summary(baseline, relevant)},
        max_tokens=512,
    )

    risks = {c: 0.0 for c in countries}
    risks.update(baseline)
    for country, score in (result.get("country_risks") or {}).items():
        try:
            risks[country.upper()] = max(0.0, min(1.0, float(score)))
        except (TypeError, ValueError):
            continue

    state["active_events"] = relevant
    state["risk_scores"] = risks
    state["narrative"] = result.get("summary") or _risk_summary(risks, relevant)

async def analyzer(state: dict, catalog) -> None:
    """Map country risk onto concrete suppliers and lanes."""
    risks = state["risk_scores"]
    pool = catalog.for_profile(
        state["manufacturer_profile"].get("supplier_countries"), state["manufacturer_profile"].get("hs_codes")
    )

    affected = [
        {**s, "impact_score": risks.get(s["country_code"], 0.0)}
        for s in pool
        if risks.get(s["country_code"], 0.0) >= 0.30
    ]
    affected.sort(key=lambda s: s["impact_score"], reverse=True)

    exposed_ids = {s["id"] for s in affected}
    state["affected_suppliers"] = affected
    state["affected_routes"] = [
        r for r in catalog.routes
        if r.get("origin_supplier_id") in exposed_ids or r.get("through_affected_country")
    ]

    allocation = {s["id"]: float(s.get("capacity_units") or 0) for s in pool}
    state["esg_baseline"] = score_portfolio(allocation, pool, catalog.routes)

async def simulator(state: dict, catalog) -> float:
    """Run every relevant scenario. Returns wall-clock milliseconds."""
    from orchestrator.config import settings

    scenarios = select_relevant_scenarios(
        state["risk_scores"], state["active_events"]
    ) or list(SCENARIO_TEMPLATES.values())[:3]

    suppliers = catalog.for_profile(
        state["manufacturer_profile"].get("supplier_countries"), state["manufacturer_profile"].get("hs_codes")
    )
    # Alternative sources outside the profile are what make a reroute possible.
    pool_ids = {s["id"] for s in suppliers}
    suppliers = suppliers + [s for s in catalog.suppliers if s["id"] not in pool_ids]

    demand = max(1, int(state["manufacturer_profile"].get("annual_volume_units", 120_000)) // 12)
    n_iter = min(int(state["manufacturer_profile"].get("n_iterations", 1000)), settings.max_mc_iterations)
    floor = float(state["manufacturer_profile"].get("min_esg_score", 0.0))

    started = time.perf_counter()
    results = await asyncio.gather(
        *(
            run_scenario_async(
                scenario=s, suppliers=suppliers, routes=catalog.routes,
                demand_units=demand, n_iterations=n_iter,
                min_esg_score=floor, seed=abs(hash(s["id"])) % (2**32),
            )
            for s in scenarios
        ),
        return_exceptions=True,
    )
    elapsed = (time.perf_counter() - started) * 1000

    simulation_results, ran = {}, []
    for scenario, result in zip(scenarios, results):
        if isinstance(result, Exception):
            logger.warning("Scenario %s failed: %s", scenario["id"], result)
            continue
        simulation_results[scenario["id"]] = result.to_dict()
        ran.append(scenario)

    state["scenarios"] = ran
    state["simulation_results"] = simulation_results
    return elapsed

async def recommender(state: dict, catalog) -> None:
    """Turn simulation output into ranked, costed actions."""
    results = state["simulation_results"]
    if not results:
        state["recommendations"] = []
        state["selected_recommendation"] = None
        return

    recs = _heuristic_recommendations(results, state["affected_suppliers"], catalog)

    enriched = await provider.complete_json(
        _RECOMMENDER_SYSTEM,
        _recommender_prompt(state["manufacturer_profile"], results, recs),
        fallback={"recommendations": []},
        max_tokens=1500,
    )
    for i, llm_rec in enumerate((enriched.get("recommendations") or [])[: len(recs)]):
        if isinstance(llm_rec, dict) and llm_rec.get("description"):
            recs[i]["description"] = str(llm_rec["description"])
            recs[i]["rationale"] = str(llm_rec.get("rationale") or recs[i]["rationale"])
            recs[i]["authored_by"] = "llm"

    state["recommendations"] = recs
    selected = recs[0] if recs else None
    state["selected_recommendation"] = selected

    if selected and selected.get("proposed_config"):
        state["esg_projected"] = score_portfolio(
            selected["proposed_config"], catalog.suppliers, catalog.routes
        )

def hitl_gate(state: dict) -> str:
    """'pause' when a human must decide, otherwise auto-approve."""
    selected = state.get("selected_recommendation")
    if not selected:
        state["hitl_required"] = False
        state["hitl_decision"] = "reject"
        state["hitl_tier"] = TIER_AUTO
        return "continue"

    tier, window = escalation_tier(selected)
    state["hitl_tier"] = tier
    state["approval_timeout_seconds"] = window

    if state.get("hitl_decision"):
        state["hitl_required"] = False
        return "continue"

    if tier == TIER_AUTO:
        state["hitl_required"] = False
        state["hitl_decision"] = "approve"
        state["hitl_approver"] = "auto-approve policy"
        return "continue"

    state["hitl_required"] = True
    return "pause"

async def executor(state: dict) -> None:
    """Record the outcome. Real ERP writes are out of scope; the log is the artefact."""
    decision = state.get("hitl_decision")
    selected = state.get("selected_recommendation") or {}
    ts = datetime.now(UTC).isoformat()
    approver = state.get("hitl_approver", "unknown")

    if decision != "approve":
        state["execution_status"] = f"not executed ({decision or 'no decision'})"
        state["execution_log"] = [f"[{ts}] Halted: decision={decision}, approver={approver}"]
        state["hitl_required"] = False
        return

    log = [
        f"[{ts}] Approved by {approver} ({state['hitl_tier']} tier)",
        f"[{ts}] Action: {selected.get('rec_type')} - {selected.get('description')}",
    ]
    allocation = selected.get("proposed_config") or {}
    catalog = await get_catalog()
    for sid, units in sorted(allocation.items(), key=lambda kv: -kv[1])[:8]:
        supplier = catalog.supplier(sid)
        name = supplier["name"] if supplier else sid[:8]
        log.append(f"[{ts}]   allocate {units:,.0f} units -> {name}")
    if state.get("hitl_notes"):
        log.append(f"[{ts}] Approver notes: {state['hitl_notes']}")
    log.append(f"[{ts}] Execution complete - {len(allocation)} supplier allocations written")

    state["execution_status"] = "executed"
    state["execution_log"] = log
    state["hitl_required"] = False



# -- recommendation heuristics -------------------------------------------------


def _heuristic_recommendations(results: dict, affected: list[dict], catalog) -> list[dict]:
    """Deterministic recommendations derived straight from the simulation output.

    These are the numbers of record. When an LLM is configured it rewrites the
    prose, but never the figures - so the dashboard shows the same costs whether
    or not a provider is available.
    """
    ranked = sorted(results.values(), key=lambda r: r.get("risk_score", 0), reverse=True)
    worst = ranked[0]
    cheapest = min(results.values(), key=lambda r: r.get("cost_mean", float("inf")))

    baseline = worst.get("baseline_cost_mean") or worst.get("cost_mean", 0)
    exposure = worst.get("cost_p95", 0) - baseline
    mix = {m["supplier_id"]: m for m in cheapest.get("supplier_mix", [])}
    exposed_ids = {s["id"] for s in affected}
    switch_in = [m for sid, m in mix.items() if sid not in exposed_ids][:3]

    recs: list[dict] = []

    recs.append({
        "id": "rec_reroute",
        "rec_type": "reroute",
        "scenario_id": worst["scenario_id"],
        "description": (
            f"Shift volume onto the lanes the optimiser selects under "
            f"'{worst['scenario_name']}', capping tail exposure at "
            f"${worst.get('cost_p95', 0):,.0f}."
        ),
        "rationale": (
            f"Highest-risk scenario (risk {worst.get('risk_score', 0):.2f}, "
            f"{worst.get('infeasible_pct', 0):.1f}% of iterations cannot serve demand). "
            f"P95 sits ${exposure:,.0f} above the undisrupted baseline."
        ),
        "cost_delta_usd": round(cheapest.get("cost_mean", 0) - baseline, 2),
        "risk_delta": -round(worst.get("risk_score", 0) * 0.45, 4),
        "esg_delta": round(cheapest.get("esg_score_mean", 0) - worst.get("esg_score_mean", 0), 2),
        "confidence_pct": round(max(55.0, 95.0 - worst.get("infeasible_pct", 0)), 1),
        "proposed_config": cheapest.get("best_config", {}),
        "authored_by": "heuristic",
    })

    if switch_in:
        names = ", ".join(m["name"] for m in switch_in)
        share = sum(m["share_pct"] for m in switch_in)
        recs.append({
            "id": "rec_switch",
            "rec_type": "supplier_switch",
            "scenario_id": worst["scenario_id"],
            "description": (
                f"Qualify {names} as alternate sources and move {share:.0f}% of volume "
                f"out of the exposed countries."
            ),
            "rationale": (
                f"The optimiser routes {share:.0f}% of units through these suppliers across "
                f"feasible iterations; none sit in a country flagged above the 0.30 risk floor."
            ),
            "cost_delta_usd": round(exposure * -0.30, 2),
            "risk_delta": -0.35,
            "esg_delta": round(
                sum(m["esg_score"] for m in switch_in) / len(switch_in)
                - worst.get("esg_score_mean", 0), 2,
            ),
            "confidence_pct": 72.0,
            "proposed_config": cheapest.get("best_config", {}),
            "authored_by": "heuristic",
        })

    buffer_days = max(7, round(worst.get("delay_p95", 0) - worst.get("delay_mean", 0)))
    recs.append({
        "id": "rec_inventory",
        "rec_type": "inventory_adj",
        "scenario_id": worst["scenario_id"],
        "description": f"Hold {buffer_days} additional days of safety stock on exposed SKUs.",
        "rationale": (
            f"P95 transit is {worst.get('delay_p95', 0):.0f} days against a mean of "
            f"{worst.get('delay_mean', 0):.0f}; the gap is the buffer needed to hold service level."
        ),
        "cost_delta_usd": round(baseline * 0.012, 2),
        "risk_delta": -0.12,
        "esg_delta": 0.0,
        "confidence_pct": 81.0,
        "proposed_config": {},
        "authored_by": "heuristic",
    })

    recs.sort(key=lambda r: (r["risk_delta"], r["cost_delta_usd"]))
    return recs


def _heuristic_risk(events: list[dict], countries: list[str]) -> dict[str, float]:
    """Country risk from event severity, type weight and recency."""
    weights = {"tariff": 1.0, "geopolitical": 0.95, "supply": 0.85, "weather": 0.8,
               "strike": 0.75, "news": 0.4}
    now = datetime.now(UTC)
    scores: dict[str, float] = {c: 0.0 for c in countries}

    for event in events:
        weight = weights.get(event.get("event_type", "news"), 0.5)
        severity = float(event.get("severity", 1)) / 5.0
        try:
            age_h = (now - datetime.fromisoformat(event["valid_from"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            age_h = 24.0
        recency = max(0.35, 1.0 - age_h / 336.0)
        contribution = weight * severity * recency
        for country in event.get("affected_countries", []):
            scores[country] = min(1.0, scores.get(country, 0.0) + contribution)

    return {k: round(v, 3) for k, v in scores.items()}


def _risk_summary(risks: dict, events: list[dict]) -> str:
    hot = sorted((v, k) for k, v in risks.items() if v >= 0.3)
    if not hot:
        return f"{len(events)} events tracked; no country above the 0.30 risk threshold."
    names = ", ".join(f"{k} {v:.2f}" for v, k in reversed(hot[-4:]))
    return f"{len(events)} events tracked. Elevated risk: {names}."


_MONITOR_SYSTEM = """You are a supply chain risk analyst.
Score each of the manufacturer's supplier countries from 0.0 (normal) to 1.0 (critical).
Weigh event severity, event type (tariff > geopolitical > supply > weather > strike > news),
and recency. Reply with JSON only:
{"country_risks": {"CN": 0.8}, "summary": "one sentence"}"""

_RECOMMENDER_SYSTEM = """You are a supply chain optimisation expert.
You are given simulation-derived recommendations with fixed numeric fields.
Rewrite only 'description' and 'rationale' so an operations director can act on them.
Never change or invent numbers - reuse the ones given. Keep the same order and count.
Reply with JSON only: {"recommendations": [{"description": "...", "rationale": "..."}]}"""


def _monitor_prompt(countries: list[str], hs_codes: list[str], events: list[dict]) -> str:
    lines = "\n".join(
        f"- [{e['event_type']} sev={e['severity']}] {e.get('title', '')} "
        f"| countries: {e.get('affected_countries', [])}"
        for e in events[:20]
    )
    return f"Supplier countries: {countries}\nHS codes: {hs_codes}\n\nEvents:\n{lines}"


def _recommender_prompt(profile: dict, results: dict, recs: list[dict]) -> str:
    import json

    summary = [
        {
            "scenario": r["scenario_name"], "risk_score": r.get("risk_score"),
            "cost_mean": round(r.get("cost_mean", 0)), "cost_p95": round(r.get("cost_p95", 0)),
            "delay_mean_days": round(r.get("delay_mean", 0), 1),
            "esg_score": round(r.get("esg_score_mean", 0), 1),
            "service_level_pct": round(r.get("service_level_pct", 0), 1),
        }
        for r in results.values()
    ]
    drafts = [
        {"rec_type": r["rec_type"], "description": r["description"], "rationale": r["rationale"],
         "cost_delta_usd": r["cost_delta_usd"]}
        for r in recs
    ]
    return (
        f"Manufacturer: {profile.get('name')} ({profile.get('industry')})\n"
        f"Countries: {profile.get('supplier_countries')}\n"
        f"ESG floor: {profile.get('min_esg_score')}\n\n"
        f"Simulation results:\n{json.dumps(summary, indent=2)}\n\n"
        f"Draft recommendations to rewrite:\n{json.dumps(drafts, indent=2)}"
    )
