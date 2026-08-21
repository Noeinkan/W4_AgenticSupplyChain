"""Liveness and configuration reporting."""

from datetime import UTC, datetime

from fastapi import APIRouter

from orchestrator.api.schemas import HealthResponse
from orchestrator.config import settings
from orchestrator.data import get_catalog
from orchestrator.llm import provider

router = APIRouter(tags=["health"])

VERSION = "0.2.0"


@router.get("/", response_model=HealthResponse)
async def health_check():
    catalog = await get_catalog()
    return HealthResponse(
        status="ok",
        version=VERSION,
        data_backend=catalog.backend,
        supplier_count=len(catalog.suppliers),
        llm=provider.describe().to_dict(),
        db_connected=catalog.backend == "db",
        ingestion_enabled=settings.enable_ingestion,
        engine="langgraph" if settings.use_langgraph else "native",
        server_time=datetime.now(UTC),
    )


@router.get("/llm")
async def llm_health():
    """Probe the configured LLM provider with a one-token prompt."""
    return (await provider.health()).to_dict()
