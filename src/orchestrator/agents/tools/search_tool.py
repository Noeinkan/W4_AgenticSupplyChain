"""
LangChain tools available to agent nodes.
Each @tool function has a typed signature so the LLM knows how to call it.
"""

from langchain_core.tools import tool


@tool
async def semantic_search_events(query: str, top_k: int = 5) -> list[dict]:
    """
    Search supply-chain disruption events by semantic similarity.

    Use this to find relevant events for a topic, country, or commodity.
    Examples:
      - "port disruption Taiwan"
      - "tariff increase electronics China"
      - "factory closure Bangladesh flooding"

    Args:
        query: Natural language description of the disruption to search for.
        top_k: Number of results to return (1–20, default 5).

    Returns:
        List of event dicts: id, event_type, severity (1-5), title, description, similarity.
    """
    # Import here to avoid circular deps at module load time
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.ingestion.embedder import semantic_search

    async with AsyncSessionLocal() as db:
        return await semantic_search(db, query, top_k=min(top_k, 20))


@tool
async def get_supplier_alternatives(
    exclude_country: str,
    hs_code: str = "",
    min_capacity: int = 0,
) -> list[dict]:
    """
    Find alternative suppliers that are NOT in a given high-risk country.

    Use this when a supplier country has high risk scores to find viable alternatives.

    Args:
        exclude_country: ISO 2-letter country code to avoid (e.g. "CN", "BD").
        hs_code: 4-digit HS product code to filter by (optional, e.g. "8542").
        min_capacity: Minimum annual capacity in units (optional).

    Returns:
        List of supplier dicts sorted by ESG score descending.
    """
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.db.repositories.supplier_repo import get_alternatives

    async with AsyncSessionLocal() as db:
        suppliers = await get_alternatives(db, exclude_country, hs_code or None, min_capacity)
        return [
            {
                "id": s.id,
                "name": s.name,
                "country_code": s.country_code,
                "region": s.region,
                "capacity_units": s.capacity_units,
                "unit_cost_usd": float(s.unit_cost_usd or 0),
                "esg_score": float(s.esg_score or 0),
                "lead_time_days": s.lead_time_days,
                "certifications": s.certifications or {},
            }
            for s in suppliers
        ]


@tool
async def get_active_events(hours: int = 24, severity_min: int = 2) -> list[dict]:
    """
    Retrieve the most recent supply-chain disruption events from the database.

    Use this to get a current snapshot of active disruptions.

    Args:
        hours: How far back to look (default 24 hours).
        severity_min: Minimum severity level 1–5 (default 2, filters noise).

    Returns:
        List of event dicts ordered by severity descending.
    """
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.db.repositories.event_repo import get_recent

    async with AsyncSessionLocal() as db:
        events = await get_recent(db, hours=hours, severity_min=severity_min)
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "description": e.description,
                "affected_countries": e.affected_countries or [],
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
