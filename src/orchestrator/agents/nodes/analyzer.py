"""
AnalyzerAgent node: traces which suppliers and routes are impacted by active events.

For each high-risk country (risk_score > 0.3):
- Find suppliers in that country
- Find routes through that country
- Compute an impact_score for each affected entity
- Return affected_suppliers + affected_routes for the simulator
"""

import logging

from orchestrator.agents.state import SupplyChainState

logger = logging.getLogger(__name__)

_RISK_THRESHOLD = 0.30  # minimum country risk score to flag a supplier


async def run(state: SupplyChainState) -> dict:
    """AnalyzerAgent node — returns partial state update."""
    risk_scores = state.get("risk_scores", {})
    profile = state.get("manufacturer_profile", {})

    # Identify high-risk countries
    high_risk_countries = {
        country: score
        for country, score in risk_scores.items()
        if score >= _RISK_THRESHOLD
    }

    if not high_risk_countries:
        logger.info("Analyzer: no high-risk countries detected")
        return {
            "affected_suppliers": [],
            "affected_routes": [],
        }

    logger.info("Analyzer: high-risk countries = %s", high_risk_countries)

    # Load all active suppliers + routes from DB
    from orchestrator.db.engine import AsyncSessionLocal
    from orchestrator.db.repositories.route_repo import get_all_active
    from orchestrator.db.repositories.supplier_repo import get_all_active as get_suppliers

    async with AsyncSessionLocal() as db:
        all_suppliers = await get_suppliers(db)
        all_routes = await get_all_active(db)

    # Build supplier lookup
    supplier_map = {s.id: s for s in all_suppliers}

    # Identify affected suppliers
    affected_suppliers: list[dict] = []
    for supplier in all_suppliers:
        if supplier.country_code in high_risk_countries:
            risk = high_risk_countries[supplier.country_code]
            affected_suppliers.append(
                {
                    "id": supplier.id,
                    "name": supplier.name,
                    "country_code": supplier.country_code,
                    "capacity_units": supplier.capacity_units,
                    "unit_cost_usd": float(supplier.unit_cost_usd or 0),
                    "esg_score": float(supplier.esg_score or 0),
                    "lead_time_days": supplier.lead_time_days,
                    "commodity_codes": supplier.commodity_codes or [],
                    "certifications": supplier.certifications or {},
                    "impact_score": risk,
                }
            )

    # Identify affected routes (routes through high-risk country OR from affected supplier)
    affected_supplier_ids = {s["id"] for s in affected_suppliers}
    affected_routes: list[dict] = []
    for route in all_routes:
        supplier = supplier_map.get(route.origin_supplier_id or "")
        is_from_affected = route.origin_supplier_id in affected_supplier_ids
        is_through_affected = route.through_affected_country

        if is_from_affected or is_through_affected:
            country = supplier.country_code if supplier else "??"
            risk = high_risk_countries.get(country, 0.2)
            affected_routes.append(
                {
                    "id": route.id,
                    "origin_supplier_id": route.origin_supplier_id,
                    "destination_port": route.destination_port,
                    "mode": route.mode,
                    "transit_days": route.transit_days,
                    "cost_per_unit": float(route.cost_per_unit or 0),
                    "co2_kg_per_unit": float(route.co2_kg_per_unit or 0),
                    "reliability_pct": float(route.reliability_pct or 85),
                    "through_affected_country": is_through_affected,
                    "impact_score": risk,
                }
            )

    logger.info(
        "Analyzer: %d affected suppliers, %d affected routes",
        len(affected_suppliers),
        len(affected_routes),
    )

    return {
        "affected_suppliers": affected_suppliers,
        "affected_routes": affected_routes,
    }
