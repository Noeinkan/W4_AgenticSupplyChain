"""
Pydantic request/response schemas for all FastAPI routes.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Simulation ───────────────────────────────────────────────────────────────


class ManufacturerProfile(BaseModel):
    name: str
    industry: Literal["fashion", "electronics", "automotive", "pharma", "other"] = "fashion"
    hs_codes: list[str] = Field(min_length=1, max_length=20, examples=[["6104", "6201"]])
    supplier_countries: list[str] = Field(examples=[["CN", "VN", "BD"]])
    annual_volume_units: int = Field(gt=0, examples=[500_000])
    min_esg_score: float = Field(default=50.0, ge=0, le=100)
    n_iterations: int = Field(default=1000, ge=100, le=10_000)


class TriggerSimulationRequest(BaseModel):
    manufacturer_profile: ManufacturerProfile
    auto_trigger_on_events: bool = True


class SimulationStartResponse(BaseModel):
    run_id: str
    thread_id: str
    status: str = "started"
    message: str = "Simulation pipeline started in background"


class SimulationStatusResponse(BaseModel):
    run_id: str
    status: Literal["pending", "running", "complete", "failed", "awaiting_approval"]
    progress_pct: float = 0.0
    created_at: datetime | None = None
    completed_at: datetime | None = None
    thread_id: str | None = None


class SimulationResultResponse(BaseModel):
    run_id: str
    thread_id: str
    status: str
    scenario_results: list[dict]
    recommendations: list[dict]
    esg_summary: dict
    hitl_required: bool = False


# ── Governance ───────────────────────────────────────────────────────────────


class GovernanceDecisionRequest(BaseModel):
    thread_id: str
    recommendation_id: str
    decision: Literal["approve", "reject", "modify"]
    approver: str = "api_user"
    notes: str | None = None
    modified_config: dict | None = None


class GovernanceDecisionResponse(BaseModel):
    thread_id: str
    decision: str
    status: str
    message: str


class PendingApproval(BaseModel):
    recommendation_id: str
    thread_id: str | None
    rec_type: str
    description: str | None
    cost_delta_usd: float | None
    risk_delta: float | None
    esg_delta: float | None
    confidence_pct: float | None
    created_at: datetime | None


# ── ESG ──────────────────────────────────────────────────────────────────────


class ESGReportRequest(BaseModel):
    manufacturer_id: str | None = None
    supplier_ids: list[str] | None = None
    scenario_id: str | None = None
    standard: Literal["GRI", "SASB", "CDP", "custom"] = "GRI"


class SupplierESGResponse(BaseModel):
    supplier_id: str
    supplier_name: str | None
    composite_score: float
    environmental: float
    social: float
    governance: float
    breakdown: dict


# ── Health ───────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    db_connected: bool = False
    ingestion_scheduler: bool = False
