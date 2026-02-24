# Codebase Index — W4_AgenticSupplyChain

## Entry points
- [src/orchestrator/main.py](src/orchestrator/main.py) — FastAPI app, lifespan, router mounts, scheduler start
- [src/orchestrator/config.py](src/orchestrator/config.py) — pydantic-settings `Settings` (env vars)

## Agent pipeline
- [src/orchestrator/agents/graph.py](src/orchestrator/agents/graph.py) — LangGraph `StateGraph` definition, interrupt, checkpointer
- [src/orchestrator/agents/state.py](src/orchestrator/agents/state.py) — `AgentState` TypedDict
- [src/orchestrator/agents/nodes/monitor.py](src/orchestrator/agents/nodes/monitor.py) — fetches recent disruption events
- [src/orchestrator/agents/nodes/analyzer.py](src/orchestrator/agents/nodes/analyzer.py) — LLM risk analysis
- [src/orchestrator/agents/nodes/simulator.py](src/orchestrator/agents/nodes/simulator.py) — calls Monte Carlo engine
- [src/orchestrator/agents/nodes/recommender.py](src/orchestrator/agents/nodes/recommender.py) — LP optimizer → ranked recommendations
- [src/orchestrator/agents/nodes/hitl_gate.py](src/orchestrator/agents/nodes/hitl_gate.py) — pause/resume, governance tier routing
- [src/orchestrator/agents/nodes/executor.py](src/orchestrator/agents/nodes/executor.py) — applies approved reroute
- [src/orchestrator/agents/tools/search_tool.py](src/orchestrator/agents/tools/search_tool.py) — pgvector semantic search tool

## Simulation
- [src/orchestrator/simulation/monte_carlo.py](src/orchestrator/simulation/monte_carlo.py) — 1,000-iteration MC engine
- [src/orchestrator/simulation/optimizer.py](src/orchestrator/simulation/optimizer.py) — PuLP LP (min cost, ESG + demand constraints)
- [src/orchestrator/simulation/scenarios.py](src/orchestrator/simulation/scenarios.py) — 5 scenario templates
- [src/orchestrator/simulation/scoring.py](src/orchestrator/simulation/scoring.py) — scenario risk scoring

## ESG
- [src/orchestrator/esg/calculator.py](src/orchestrator/esg/calculator.py) — weighted ESG score per supplier/route
- [src/orchestrator/esg/standards.py](src/orchestrator/esg/standards.py) — GRI / SASB report builders

## Database
- [src/orchestrator/db/models.py](src/orchestrator/db/models.py) — SQLAlchemy ORM models (Supplier, DisruptionEvent, SimulationRun, Route, …)
- [src/orchestrator/db/engine.py](src/orchestrator/db/engine.py) — async engine + session factory
- [src/orchestrator/db/repositories/supplier_repo.py](src/orchestrator/db/repositories/supplier_repo.py)
- [src/orchestrator/db/repositories/event_repo.py](src/orchestrator/db/repositories/event_repo.py)
- [src/orchestrator/db/repositories/scenario_repo.py](src/orchestrator/db/repositories/scenario_repo.py)
- [src/orchestrator/db/repositories/route_repo.py](src/orchestrator/db/repositories/route_repo.py)

## Ingestion
- [src/orchestrator/ingestion/scheduler.py](src/orchestrator/ingestion/scheduler.py) — APScheduler jobs (15 min / 30 min / daily)
- [src/orchestrator/ingestion/news.py](src/orchestrator/ingestion/news.py) — NewsAPI + RSS feed parser
- [src/orchestrator/ingestion/climate.py](src/orchestrator/ingestion/climate.py) — OpenWeatherMap hub alerts
- [src/orchestrator/ingestion/comtrade.py](src/orchestrator/ingestion/comtrade.py) — UN Comtrade trade-flow anomaly detection
- [src/orchestrator/ingestion/embedder.py](src/orchestrator/ingestion/embedder.py) — OpenAI ada-002 → pgvector upsert

## API
- [src/orchestrator/api/routes/simulation.py](src/orchestrator/api/routes/simulation.py) — `POST /trigger`, `GET /{id}/status`, `GET /{id}/results`
- [src/orchestrator/api/routes/governance.py](src/orchestrator/api/routes/governance.py) — `POST /decision`, `GET /pending`
- [src/orchestrator/api/routes/esg.py](src/orchestrator/api/routes/esg.py) — `POST /report`, `GET /leaderboard`
- [src/orchestrator/api/routes/health.py](src/orchestrator/api/routes/health.py) — `GET /health`
- [src/orchestrator/api/schemas.py](src/orchestrator/api/schemas.py) — Pydantic request/response models
- [src/orchestrator/api/dependencies.py](src/orchestrator/api/dependencies.py) — FastAPI dependency injectors

## Sovereign mode
- [src/orchestrator/sovereign/local_llm.py](src/orchestrator/sovereign/local_llm.py) — Ollama client swap-in

## Tests
- [tests/test_simulation.py](tests/test_simulation.py) — Monte Carlo + LP optimizer unit tests
- [tests/test_esg.py](tests/test_esg.py) — ESG calculator unit tests
- [tests/conftest.py](tests/conftest.py) — shared fixtures

## Config / infra
- [docker-compose.yml](docker-compose.yml) — Postgres 16 + pgvector service
- [pyproject.toml](pyproject.toml) — Poetry deps, pytest config
- [alembic.ini](alembic.ini) — migration config (`PYTHONPATH=src alembic upgrade head`)
- [.env.example](.env.example) — required env vars template
- [scripts/seed_data.py](scripts/seed_data.py) — seed suppliers, scenarios, sample events
