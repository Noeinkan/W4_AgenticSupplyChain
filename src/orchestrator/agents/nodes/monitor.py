"""
MonitorAgent node: scans for supply-chain disruptions relevant to the manufacturer profile.

Actions:
1. Pull recent events from DB (last 24h, severity ≥ 2)
2. Semantic search for events matching the manufacturer's supplier countries + HS codes
3. Ask the LLM to score country-level risk (0.0–1.0) given discovered events
4. Return enriched active_events list + risk_scores dict
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from orchestrator.agents.state import SupplyChainState
from orchestrator.agents.tools.search_tool import (
    get_active_events,
    semantic_search_events,
)

logger = logging.getLogger(__name__)

_MONITOR_SYSTEM_PROMPT = """You are a supply chain risk analyst for a global manufacturer.
Given a list of recent disruption events, score each country in the manufacturer's supplier
network on a risk scale of 0.0 (safe) to 1.0 (critical disruption).

Consider: event severity, affected countries, event type weight
(tariff > geopolitical > weather > strike > news), and recency.

Respond ONLY with valid JSON in this exact format:
{"country_risks": {"CN": 0.8, "VN": 0.3, ...}, "summary": "one sentence summary"}
"""


def _get_llm():
    """Lazy import to avoid import errors when API key not set."""
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
        max_tokens=512,
    )


async def run(state: SupplyChainState) -> dict:
    """MonitorAgent node — returns partial state update."""
    profile = state.get("manufacturer_profile", {})
    supplier_countries = profile.get("supplier_countries", [])
    hs_codes = profile.get("hs_codes", [])

    # 1. Recent events from DB
    recent_events_raw = await get_active_events.ainvoke({"hours": 48, "severity_min": 2})

    # 2. Semantic search for profile-specific disruptions
    search_results: list[dict] = []
    queries = (
        [f"supply chain disruption {c}" for c in supplier_countries[:4]]
        + [f"trade disruption HS {code}" for code in hs_codes[:2]]
    )
    for q in queries:
        hits = await semantic_search_events.ainvoke({"query": q, "top_k": 3})
        search_results.extend(hits)

    # Deduplicate by id
    seen: set[str] = set()
    unique_events: list[dict] = []
    for e in recent_events_raw + search_results:
        eid = e.get("id", "")
        if eid and eid not in seen:
            seen.add(eid)
            unique_events.append(e)

    # 3. LLM risk scoring
    risk_scores: dict[str, float] = {c: 0.0 for c in supplier_countries}
    summary = "No significant disruptions detected."

    if unique_events:
        events_text = "\n".join(
            f"- [{e['event_type'].upper()} sev={e['severity']}] {e.get('title', e.get('description', ''))[:200]}"
            f" | countries: {e.get('affected_countries', [])}"
            for e in unique_events[:20]
        )
        prompt = (
            f"Manufacturer supplier countries: {supplier_countries}\n"
            f"HS codes: {hs_codes}\n\n"
            f"Recent events:\n{events_text}"
        )

        try:
            llm = _get_llm()
            response = await llm.ainvoke(
                [
                    SystemMessage(content=_MONITOR_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            data = json.loads(response.content)
            risk_scores.update(data.get("country_risks", {}))
            summary = data.get("summary", summary)
            logger.info("Monitor: risk scores = %s", risk_scores)
        except Exception:
            logger.exception("LLM risk scoring failed — using zero scores")

    return {
        "active_events": unique_events,
        "risk_scores": risk_scores,
        "messages": [HumanMessage(content=f"Monitor summary: {summary}")],
    }
