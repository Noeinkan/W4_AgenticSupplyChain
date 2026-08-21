"""
ESG reporting routes.

POST /api/v1/esg/report        GRI / SASB report for a supplier portfolio
GET  /api/v1/esg/score/{id}    ESG breakdown for one supplier
GET  /api/v1/esg/compare       baseline vs. a proposed allocation
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orchestrator.api.schemas import ESGReportRequest, SupplierESGResponse
from orchestrator.data import get_catalog
from orchestrator.esg.calculator import (
    generate_gri_report,
    generate_sasb_report,
    score_portfolio,
    score_supplier,
)

router = APIRouter(tags=["esg"])


@router.post("/report")
async def generate_esg_report(request: ESGReportRequest):
    """Portfolio ESG report against the requested disclosure standard."""
    catalog = await get_catalog()
    suppliers = (
        [s for s in catalog.suppliers if s["id"] in set(request.supplier_ids)]
        if request.supplier_ids
        else catalog.suppliers
    )
    if not suppliers:
        raise HTTPException(status_code=404, detail="No matching suppliers")

    # Capacity-weighted, so the report reflects the real sourcing footprint
    # rather than treating a 60k-unit supplier the same as a 600k-unit one.
    allocation = {s["id"]: float(s.get("capacity_units") or 1) for s in suppliers}
    portfolio = score_portfolio(allocation, suppliers, catalog.routes)

    audited = sum(1 for s in suppliers if (s.get("certifications") or {}).get("SA8000"))
    pct_audited = 100.0 * audited / len(suppliers)

    if request.standard == "GRI":
        return generate_gri_report(portfolio, pct_suppliers_audited=pct_audited)
    if request.standard == "SASB":
        return generate_sasb_report(portfolio, pct_audited=pct_audited)
    return portfolio


@router.get("/score/{supplier_id}", response_model=SupplierESGResponse)
async def get_supplier_esg(supplier_id: str):
    catalog = await get_catalog()
    supplier = catalog.supplier(supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    return SupplierESGResponse(**score_supplier(supplier, catalog.routes_for(supplier_id)))


@router.get("/compare")
async def compare_allocations(run_id: str):
    """Baseline vs. projected ESG for a completed pipeline run."""
    from orchestrator.pipeline import get_store

    run = get_store().get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    baseline = run.state.get("esg_baseline") or {}
    projected = run.state.get("esg_projected") or {}
    dimensions = ["environmental", "social", "governance", "composite"]
    return {
        "run_id": run_id,
        "baseline": baseline,
        "projected": projected,
        "delta": {
            d: round(float(projected.get(d, 0) or 0) - float(baseline.get(d, 0) or 0), 2)
            for d in dimensions
        },
    }
