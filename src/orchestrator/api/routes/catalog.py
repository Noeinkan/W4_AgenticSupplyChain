"""
Reference-data routes backing the dashboard's network, ESG and scenario views.

GET /api/v1/catalog/suppliers    supplier master with ESG breakdown
GET /api/v1/catalog/routes       shipping lanes
GET /api/v1/catalog/events       live disruption feed
GET /api/v1/catalog/scenarios    scenario templates available to simulate
GET /api/v1/catalog/esg          supplier ESG leaderboard
GET /api/v1/catalog/overview     one call for the landing dashboard
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from orchestrator.data import get_catalog
from orchestrator.esg.calculator import score_supplier
from orchestrator.simulation.scenarios import SCENARIO_TEMPLATES

router = APIRouter(tags=["catalog"])


@router.get("/suppliers")
async def list_suppliers():
    catalog = await get_catalog()
    return [
        {**s, "route_count": len(catalog.routes_for(s["id"]))}
        for s in catalog.suppliers
    ]


@router.get("/routes")
async def list_routes():
    catalog = await get_catalog()
    names = {s["id"]: s["name"] for s in catalog.suppliers}
    countries = {s["id"]: s["country_code"] for s in catalog.suppliers}
    return [
        {
            **r,
            "origin_name": names.get(r.get("origin_supplier_id"), "unknown"),
            "origin_country": countries.get(r.get("origin_supplier_id"), "??"),
        }
        for r in catalog.routes
    ]


@router.get("/events")
async def list_events():
    catalog = await get_catalog()
    return sorted(catalog.events, key=lambda e: e.get("severity", 0), reverse=True)


@router.get("/scenarios")
async def list_scenarios():
    """Scenario templates, with the knobs the UI displays."""
    return [
        {
            "id": s["id"],
            "name": s["name"],
            "event_type": s["event_type"],
            "tariff_range": s.get("tariff_shock", {}).get("rate_range", [0, 0]),
            "delay_multiplier_range": s.get("weather_impact", {}).get(
                "delay_multiplier_range", [1, 1]
            ),
            "demand_change_range": s.get("demand_shock", {}).get("change_range", [0, 0]),
            "port_closure_probability": s.get("port_closure_probability", 0),
            "capacity_reduction": s.get("capacity_reduction", {}),
            "extra_transit_days": s.get("extra_transit_days", 0),
        }
        for s in SCENARIO_TEMPLATES.values()
    ]


@router.get("/esg")
async def esg_leaderboard(limit: int = Query(50, ge=1, le=200)):
    """Suppliers ranked by composite ESG score."""
    catalog = await get_catalog()
    scored = [
        {
            **score_supplier(s, catalog.routes_for(s["id"])),
            "country_code": s["country_code"],
            "tier": s.get("tier"),
            "unit_cost_usd": s.get("unit_cost_usd"),
            "capacity_units": s.get("capacity_units"),
        }
        for s in catalog.suppliers
    ]
    scored.sort(key=lambda s: s["composite_score"], reverse=True)
    for rank, entry in enumerate(scored, 1):
        entry["rank"] = rank
    return scored[:limit]


@router.get("/overview")
async def overview():
    """Everything the landing view needs, in one round trip."""
    catalog = await get_catalog()
    suppliers = catalog.suppliers
    capacity = sum(float(s.get("capacity_units") or 0) for s in suppliers)
    esg_values = [float(s.get("esg_score") or 0) for s in suppliers]

    by_country: dict[str, dict] = {}
    for s in suppliers:
        entry = by_country.setdefault(
            s["country_code"], {"country_code": s["country_code"], "suppliers": 0,
                                "capacity_units": 0.0, "esg_sum": 0.0}
        )
        entry["suppliers"] += 1
        entry["capacity_units"] += float(s.get("capacity_units") or 0)
        entry["esg_sum"] += float(s.get("esg_score") or 0)
    for entry in by_country.values():
        entry["esg_score"] = round(entry.pop("esg_sum") / entry["suppliers"], 1)
        entry["capacity_share_pct"] = round(100 * entry["capacity_units"] / (capacity or 1), 1)

    return {
        "backend": catalog.backend,
        "supplier_count": len(suppliers),
        "route_count": len(catalog.routes),
        "country_count": len(by_country),
        "total_capacity_units": capacity,
        "mean_esg_score": round(sum(esg_values) / max(len(esg_values), 1), 1),
        "active_events": len(catalog.events),
        "max_event_severity": max((e.get("severity", 0) for e in catalog.events), default=0),
        "scenario_count": len(SCENARIO_TEMPLATES),
        "by_country": sorted(by_country.values(), key=lambda c: -c["capacity_units"]),
        "events": sorted(catalog.events, key=lambda e: e.get("severity", 0), reverse=True)[:6],
    }
