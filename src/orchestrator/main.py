"""
FastAPI application entry point.

Lifespan:
  - Starts APScheduler ingestion jobs (news/weather/trade)
  - Initialises LangGraph with Postgres checkpointer (or MemorySaver fallback)
  - Disposes DB engine and scheduler on shutdown
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.agents.graph import build_graph, get_checkpointer
from orchestrator.api.routes import esg, governance, health, simulation
from orchestrator.config import settings
from orchestrator.db.engine import engine
from orchestrator.ingestion.scheduler import create_scheduler

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Supply Chain Orchestrator", version="0.1.0", debug=settings.debug)

    # 1. LangGraph checkpointer + compiled graph
    checkpointer = await get_checkpointer()
    graph = build_graph(checkpointer)
    app.state.graph = graph
    app.state.checkpointer = checkpointer
    logger.info("LangGraph compiled and ready")

    # 2. Ingestion scheduler
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Ingestion scheduler started",
        jobs=[j.id for j in scheduler.get_jobs()],
    )

    yield  # ── app is running ─────────────────────────────────────────────────

    # Shutdown
    scheduler.shutdown(wait=False)
    await engine.dispose()
    logger.info("Shutdown complete")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Agentic Supply-Chain Resilience Orchestrator",
    description=(
        "Autonomous agents that monitor, simulate 1,000+ disruption scenarios, "
        "and recommend or execute supply-chain reroutes — with human-in-the-loop governance."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/health")
app.include_router(simulation.router, prefix="/api/v1/simulation")
app.include_router(governance.router, prefix="/api/v1/governance")
app.include_router(esg.router, prefix="/api/v1/esg")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "Supply Chain Resilience Orchestrator",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
