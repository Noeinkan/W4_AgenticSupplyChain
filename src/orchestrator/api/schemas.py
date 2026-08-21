"""
Pydantic request/response schemas for all FastAPI routes.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Industry = Literal["fashion", "electronics", "automotive", "pharma", "other"]


# -- Pipeline ------------------------------------------------------------------


class ManufacturerProfile(BaseModel):
    name: str = Field(examples=["Northwind Apparel"])
    industry: Industry = "fashion"
    hs_codes: list[str] = Field(default_factory=lambda: ["6104"], max_length=20)
    supplier_countries: list[str] = Field(default_factory=list, examples=[["VN", "BD", "IN"]])
    annual_volume_units: int = Field(default=1_200_000, gt=0)
    min_esg_score: float = Field(default=0.0, ge=0, le=100)
    n_iterations: int = Field(default=1000, ge=100, le=50_000)
    max_iterations: int = Field(default=3, ge=0, le=10)


class TriggerRunRequest(BaseModel):
    manufacturer_profile: ManufacturerProfile


class RunStartResponse(BaseModel):
    run_id: str
    thread_id: str
    status: str = "started"


class RunSummary(BaseModel):
    run_id: str
    thread_id: str
    status: str
    progress_pct: float
    manufacturer: str | None = None
    industry: str | None = None
    created_at: str
    completed_at: str | None = None
    duration_ms: float = 0.0
    compute_ms: float = 0.0
    scenario_count: int = 0
    iterations: int = 0
    hitl_required: bool = False
    hitl_tier: str | None = None
    hitl_decision: str | None = None
    top_recommendation: str | None = None
    cost_delta_usd: float | None = None
    error: str | None = None


class RunDetail(RunSummary):
    profile: dict = Field(default_factory=dict)
    risk_scores: dict = Field(default_factory=dict)
    active_events: list[dict] = Field(default_factory=list)
    affected_suppliers: list[dict] = Field(default_factory=list)
    scenarios: list[dict] = Field(default_factory=list)
    scenario_results: list[dict] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)
    selected_recommendation: dict | None = None
    esg_baseline: dict = Field(default_factory=dict)
    esg_projected: dict = Field(default_factory=dict)
    execution_status: str | None = None
    execution_log: list[str] = Field(default_factory=list)
    narrative: str = ""
    events: list[dict] = Field(default_factory=list)


# -- Governance ----------------------------------------------------------------


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "modify"]
    approver: str = "dashboard_user"
    notes: str | None = None


class DecisionResponse(BaseModel):
    run_id: str
    thread_id: str
    decision: str
    status: str
    message: str


# -- ESG -----------------------------------------------------------------------


class ESGReportRequest(BaseModel):
    supplier_ids: list[str] | None = None
    standard: Literal["GRI", "SASB", "raw"] = "GRI"


class SupplierESGResponse(BaseModel):
    supplier_id: str
    supplier_name: str | None
    composite_score: float
    environmental: float
    social: float
    governance: float
    breakdown: dict


# -- Health --------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    data_backend: str
    supplier_count: int = 0
    llm: dict = Field(default_factory=dict)
    db_connected: bool = False
    ingestion_enabled: bool = False
    engine: str = "native"
    server_time: datetime | None = None
