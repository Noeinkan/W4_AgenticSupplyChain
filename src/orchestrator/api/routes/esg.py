"""
ESG API routes.

POST /api/v1/esg/report         — generate GRI/SASB ESG report for a portfolio
GET  /api/v1/esg/score/{id}     — ESG score for a single supplier
GET  /api/v1/esg/leaderboard    — ranked supplier ESG leaderboard
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.dependencies import get_db
from orchestrator.api.schemas import ESGReportRequest, SupplierESGResponse
from orchestrator.esg.calculator import (
    generate_gri_report,
    generate_sasb_report,
    score_portfolio,
    score_supplier,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["esg"])


@router.post("/report")
async def generate_esg_report(
    request: ESGReportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an ESG report for a supplier portfolio.
    If supplier_ids provided, score only those suppliers.
    If scenario_id provided, compare baseline vs scenario projected portfolio.
    """
    from orchestrator.db.repositories.route_repo import get_all_active
    from orchestrator.db.repositories.supplier_repo import get_all_active as get_suppliers

    all_suppliers = await get_suppliers(db)
    all_routes = await get_all_active(db)

    if request.supplier_ids:
        suppliers = [s for s in all_suppliers if s.id in request.supplier_ids]
    else:
        suppliers = all_suppliers

    if not suppliers:
        raise HTTPException(status_code=404, detail="No suppliers found")

    # Equal-weight allocation for report (1 unit each)
    allocation = {s.id: 1.0 for s in suppliers}
    supplier_dicts = [
        {
            "id": s.id,
            "name": s.name,
            "country_code": s.country_code,
            "esg_score": float(s.esg_score or 0),
            "certifications": s.certifications or {},
        }
        for s in suppliers
    ]
    route_dicts = [
        {
            "id": r.id,
            "origin_supplier_id": r.origin_supplier_id,
            "co2_kg_per_unit": float(r.co2_kg_per_unit or 1),
        }
        for r in all_routes
    ]

    portfolio = score_portfolio(allocation, supplier_dicts, route_dicts)
    pct_audited = sum(
        1 for s in supplier_dicts if s.get("certifications", {}).get("SA8000")
    ) / max(len(supplier_dicts), 1) * 100

    if request.standard == "GRI":
        return generate_gri_report(portfolio, pct_suppliers_audited=pct_audited)
    elif request.standard == "SASB":
        return generate_sasb_report(portfolio, pct_audited=pct_audited)
    else:
        return portfolio


@router.get("/score/{supplier_id}", response_model=SupplierESGResponse)
async def get_supplier_esg(supplier_id: str, db: AsyncSession = Depends(get_db)):
    """Real-time ESG score for a single supplier."""
    from sqlalchemy import select
    from orchestrator.db.models import Route, Supplier

    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")

    routes_result = await db.execute(
        select(Route).where(Route.origin_supplier_id == supplier_id, Route.active == True)  # noqa: E712
    )
    routes = routes_result.scalars().all()

    supplier_dict = {
        "id": supplier.id,
        "name": supplier.name,
        "country_code": supplier.country_code,
        "certifications": supplier.certifications or {},
    }
    route_dicts = [{"co2_kg_per_unit": float(r.co2_kg_per_unit or 1)} for r in routes]
    score = score_supplier(supplier_dict, route_dicts)

    return SupplierESGResponse(**score)


@router.get("/leaderboard")
async def get_esg_leaderboard(
    industry: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Ranked supplier ESG leaderboard (sorted by composite score desc)."""
    from sqlalchemy import select
    from orchestrator.db.models import Route, Supplier

    query = select(Supplier).where(Supplier.active == True).limit(limit * 2)  # noqa: E712
    result = await db.execute(query)
    suppliers = result.scalars().all()

    all_routes_result = await db.execute(select(Route).where(Route.active == True))  # noqa: E712
    all_routes = all_routes_result.scalars().all()

    scores = []
    for s in suppliers:
        supplier_dict = {
            "id": s.id,
            "name": s.name,
            "country_code": s.country_code,
            "certifications": s.certifications or {},
        }
        routes = [r for r in all_routes if r.origin_supplier_id == s.id]
        route_dicts = [{"co2_kg_per_unit": float(r.co2_kg_per_unit or 1)} for r in routes]
        score = score_supplier(supplier_dict, route_dicts)
        scores.append({
            "rank": 0,
            "supplier_id": s.id,
            "supplier_name": s.name,
            "country_code": s.country_code,
            "composite_score": score["composite_score"],
            "environmental": score["environmental"],
            "social": score["social"],
            "governance": score["governance"],
        })

    scores.sort(key=lambda x: x["composite_score"], reverse=True)
    for i, s in enumerate(scores[:limit], 1):
        s["rank"] = i

    return scores[:limit]
