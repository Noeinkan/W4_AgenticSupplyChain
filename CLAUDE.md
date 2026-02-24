# CLAUDE.md — Agentic Supply-Chain Resilience Orchestrator

## Project overview
Autonomous multi-agent system that monitors global supply-chain disruptions, runs Monte Carlo + LP simulations, and recommends/executes reroutes with HITL governance and ESG scoring.

## Run commands
```bash
docker compose up db -d                         # start Postgres
PYTHONPATH=src alembic upgrade head             # migrate
PYTHONPATH=src python scripts/seed_data.py      # seed
PYTHONPATH=src uvicorn orchestrator.main:app --reload  # API → http://localhost:8000/docs
PYTHONPATH=src pytest tests/ -v                 # tests (no DB/keys needed)
```

## Key files
| Purpose | Path |
|---|---|
| FastAPI entry | `src/orchestrator/main.py` |
| Settings | `src/orchestrator/config.py` |
| LangGraph pipeline | `src/orchestrator/agents/graph.py` |
| Agent state schema | `src/orchestrator/agents/state.py` |
| Monte Carlo engine | `src/orchestrator/simulation/monte_carlo.py` |
| LP optimizer | `src/orchestrator/simulation/optimizer.py` |
| ESG calculator | `src/orchestrator/esg/calculator.py` |
| DB models | `src/orchestrator/db/models.py` |
| Seed data | `scripts/seed_data.py` |
| API routes | `src/orchestrator/api/routes/` |
| Tests | `tests/` |

## Architecture
```
Ingestion (APScheduler)
  NewsAPI/RSS → pgvector embeddings
  OpenWeatherMap → hub alerts
  UN Comtrade → trade-flow anomalies

LangGraph pipeline (per trigger):
  monitor → analyzer → simulator → recommender → [hitl_gate] → executor
  interrupt_before=["hitl_gate"] for HITL pause/resume
  AsyncPostgresSaver (falls back to MemorySaver)

Simulation:
  5 scenario templates × 1,000 Monte Carlo iterations
  PuLP LP: min Σ(x_i × landed_cost_i) s.t. demand + ESG constraints

Storage: Postgres 16 + pgvector (single DB for operational + vector data)
```

## Critical LP constraint rule
When `min_esg_score > 0`, the demand constraint **must be equality** (`== demand_units`), not `>=`.
Using `>=` lets the LP over-allocate a low-ESG supplier beyond demand to satisfy the ESG sum — a silent correctness bug.

## HITL governance tiers
| Cost delta | Tier | Window |
|---|---|---|
| < $10k | Auto-approve | — |
| < $100k | Manager | 24 h |
| ≥ $100k or supplier switch | C-suite | 48 h |

## Tech stack
Python 3.11 · FastAPI · LangGraph 0.2 · langchain-anthropic · pgvector · PuLP/CBC · numpy · APScheduler · Docker Compose

## Sovereign (air-gapped) mode
Set `SOVEREIGN_MODE=true` + `OLLAMA_BASE_URL` + `OLLAMA_MODEL=llama3:70b` in `.env` to bypass cloud LLMs.

## Coding conventions
- `PYTHONPATH=src` required for all commands (no `src` on `sys.path` by default)
- Settings loaded via pydantic-settings from `.env`; see `src/orchestrator/config.py`
- Repositories in `src/orchestrator/db/repositories/` follow async SQLAlchemy pattern
- Do not add docstrings, comments, or type annotations to unchanged code
- Tests must not require a live DB or API keys
