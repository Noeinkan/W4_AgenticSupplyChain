"""
FastAPI application entry point.

Boots with nothing but FastAPI, numpy and pydantic installed: the data catalog
defaults to in-memory, the agent pipeline is framework-free, and the LLM layer
falls back to deterministic reasoning. Postgres, APScheduler ingestion and
LangGraph are all opt-in via settings, and a failure to load any of them
degrades the feature rather than the process.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.api.routes import catalog, esg, health, pipeline
from orchestrator.config import settings
from orchestrator.data import get_catalog
from orchestrator.llm import provider
from orchestrator.pipeline import get_store

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    data = await get_catalog()
    llm = provider.describe()
    logger.info(
        "Orchestrator ready - catalog=%s (%d suppliers, %d routes)  llm=%s/%s  engine=%s",
        data.backend, len(data.suppliers), len(data.routes),
        llm.provider, llm.model, "langgraph" if settings.use_langgraph else "native",
    )

    scheduler = None
    if settings.enable_ingestion:
        try:
            from orchestrator.ingestion.scheduler import create_scheduler

            scheduler = create_scheduler()
            scheduler.start()
            logger.info("Ingestion scheduler started: %s", [j.id for j in scheduler.get_jobs()])
        except Exception as exc:
            logger.warning("Ingestion disabled (%s)", exc)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
    await get_store().shutdown()
    if data.backend == "db":
        from orchestrator.db.engine import engine

        await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Agentic Supply-Chain Resilience Orchestrator",
    description=(
        "Agents monitor global disruptions, simulate them across thousands of Monte Carlo "
        "iterations, and recommend reroutes under human-in-the-loop governance."
    ),
    version=health.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health")
app.include_router(catalog.router, prefix="/api/v1/catalog")
app.include_router(pipeline.router, prefix="/api/v1/pipeline")
app.include_router(esg.router, prefix="/api/v1/esg")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Supply Chain Resilience Orchestrator",
        "version": health.VERSION,
        "dashboard": "http://localhost:5173",
        "docs": "/docs",
        "health": "/health",
    }
