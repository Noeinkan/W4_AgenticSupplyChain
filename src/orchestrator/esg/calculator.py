"""
ESG scoring engine.

Composite score (0–100):
  Environmental  40%  — CO₂/unit, ISO14001, RE100, SBTi
  Social         35%  — SA8000, WRAP, ILO country labour score
  Governance     25%  — World Bank WGI corruption percentile, ISO37001

score_portfolio_from_config() is called by the recommender node to project
ESG impact of a proposed supplier allocation change.
"""

import logging

from orchestrator.esg.standards import (
    CERTIFICATION_BONUSES,
    COUNTRY_GOVERNANCE_SCORES,
    COUNTRY_LABOUR_SCORES,
    GRI_METRICS,
    SASB_METRICS,
)

logger = logging.getLogger(__name__)

WEIGHTS = {"environmental": 0.40, "social": 0.35, "governance": 0.25}


def score_supplier(supplier: dict, routes: list[dict]) -> dict:
    """
    Compute ESG score breakdown for a single supplier.

    Returns dict with: composite_score, environmental, social, governance, breakdown
    """
    certs = supplier.get("certifications") or {}
    country = supplier.get("country_code", "US")
    avg_co2 = _avg_co2(routes)

    env = _score_environmental(certs, avg_co2)
    soc = _score_social(certs, country)
    gov = _score_governance(certs, country)
    composite = env * WEIGHTS["environmental"] + soc * WEIGHTS["social"] + gov * WEIGHTS["governance"]

    return {
        "supplier_id": supplier.get("id"),
        "supplier_name": supplier.get("name"),
        "composite_score": round(composite, 2),
        "environmental": round(env, 2),
        "social": round(soc, 2),
        "governance": round(gov, 2),
        "breakdown": {
            "avg_co2_kg_per_unit": round(avg_co2, 4),
            "certifications": certs,
            "country_wgi_score": COUNTRY_GOVERNANCE_SCORES.get(country, 50),
            "country_ilo_score": COUNTRY_LABOUR_SCORES.get(country, 50),
        },
    }


def score_portfolio(
    supplier_allocations: dict[str, float],
    all_suppliers: list[dict],
    all_routes: list[dict],
) -> dict:
    """
    Compute weighted-average ESG score for a supplier allocation.

    supplier_allocations: {supplier_id: units_allocated}
    Returns portfolio-level ESG breakdown.
    """
    total_units = sum(supplier_allocations.values()) or 1

    weighted = {"environmental": 0.0, "social": 0.0, "governance": 0.0, "composite": 0.0}
    supplier_scores = []

    for s in all_suppliers:
        weight = supplier_allocations.get(s["id"], 0.0) / total_units
        if weight == 0:
            continue
        routes = [r for r in all_routes if r.get("origin_supplier_id") == s["id"]]
        score = score_supplier(s, routes)
        supplier_scores.append({**score, "weight": weight})
        for key in ("environmental", "social", "governance"):
            weighted[key] += score[key] * weight

    weighted["composite"] = (
        weighted["environmental"] * WEIGHTS["environmental"]
        + weighted["social"] * WEIGHTS["social"]
        + weighted["governance"] * WEIGHTS["governance"]
    )
    weighted["supplier_breakdown"] = supplier_scores
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in weighted.items()}


async def score_portfolio_from_config(
    proposed_config: dict,
    delta: float = 0.0,
) -> dict:
    """
    Async wrapper used by the recommender node.
    Loads suppliers/routes from DB and scores the proposed allocation.
    Falls back to a simple delta if DB is unavailable.
    """
    if not proposed_config:
        return {"composite": 50.0 + delta, "note": "No config provided"}
    try:
        from orchestrator.db.engine import AsyncSessionLocal
        from orchestrator.db.repositories.route_repo import get_all_active
        from orchestrator.db.repositories.supplier_repo import get_all_active as get_suppliers

        async with AsyncSessionLocal() as db:
            all_suppliers = await get_suppliers(db)
            all_routes = await get_all_active(db)

        supplier_dicts = [
            {
                "id": s.id,
                "name": s.name,
                "country_code": s.country_code,
                "esg_score": float(s.esg_score or 0),
                "certifications": s.certifications or {},
            }
            for s in all_suppliers
        ]
        route_dicts = [
            {
                "id": r.id,
                "origin_supplier_id": r.origin_supplier_id,
                "co2_kg_per_unit": float(r.co2_kg_per_unit or 1),
            }
            for r in all_routes
        ]
        return score_portfolio(proposed_config, supplier_dicts, route_dicts)
    except Exception:
        logger.exception("ESG portfolio scoring failed — returning delta estimate")
        return {"composite": 50.0 + delta, "note": "Estimated from delta"}


def generate_gri_report(
    portfolio_score: dict,
    total_co2_tonnes: float = 0.0,
    pct_suppliers_audited: float = 0.0,
) -> dict:
    """Generate a GRI-aligned ESG disclosure report."""
    return {
        "standard": "GRI",
        "composite_esg_score": portfolio_score.get("composite", 0),
        "environmental_score": portfolio_score.get("environmental", 0),
        "social_score": portfolio_score.get("social", 0),
        "governance_score": portfolio_score.get("governance", 0),
        "disclosures": {
            "GRI-305-3": {
                "metric": GRI_METRICS["GRI-305-3"],
                "value": total_co2_tonnes,
                "unit": "tonnes CO2e",
            },
            "GRI-414-1": {
                "metric": GRI_METRICS["GRI-414-1"],
                "value": pct_suppliers_audited,
                "unit": "%",
            },
        },
        "supplier_breakdown": portfolio_score.get("supplier_breakdown", []),
    }


def generate_sasb_report(portfolio_score: dict, pct_audited: float = 0.0) -> dict:
    """Generate a SASB-aligned ESG disclosure report."""
    return {
        "standard": "SASB",
        "composite_esg_score": portfolio_score.get("composite", 0),
        "disclosures": {
            "CG-AA-430a.1": {
                "metric": SASB_METRICS["CG-AA-430a.1"],
                "value": pct_audited,
                "unit": "%",
            },
            "TC-HW-430a.1": {
                "metric": SASB_METRICS["TC-HW-430a.1"],
                "value": pct_audited,
                "unit": "%",
            },
        },
    }


# ── Private helpers ──────────────────────────────────────────────────────────


def _score_environmental(certs: dict, avg_co2: float) -> float:
    score = 50.0
    # CO2 scoring: <0.5 kg/unit = excellent, >5 = poor
    if avg_co2 < 0.5:
        score += 35.0
    elif avg_co2 < 1.5:
        score += 20.0
    elif avg_co2 < 5.0:
        score += 8.0
    else:
        score -= 10.0
    for cert, bonus in CERTIFICATION_BONUSES["environmental"].items():
        if certs.get(cert):
            score += bonus
    return min(max(score, 0.0), 100.0)


def _score_social(certs: dict, country: str) -> float:
    score = 50.0
    country_ilo = COUNTRY_LABOUR_SCORES.get(country, 50.0)
    score = (score + country_ilo) / 2.0
    for cert, bonus in CERTIFICATION_BONUSES["social"].items():
        if certs.get(cert):
            score += bonus
    return min(max(score, 0.0), 100.0)


def _score_governance(certs: dict, country: str) -> float:
    score = COUNTRY_GOVERNANCE_SCORES.get(country, 50.0)
    for cert, bonus in CERTIFICATION_BONUSES["governance"].items():
        if certs.get(cert):
            score += bonus
    return min(max(score, 0.0), 100.0)


def _avg_co2(routes: list[dict]) -> float:
    if not routes:
        return 1.0
    values = [float(r.get("co2_kg_per_unit") or 1.0) for r in routes]
    return sum(values) / len(values)
