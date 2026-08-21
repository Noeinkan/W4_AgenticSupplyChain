# Agentic Supply-Chain Resilience Orchestrator

Autonomous agents that watch global supply-chain disruptions, simulate them across
thousands of Monte Carlo iterations, and recommend reroutes under human-in-the-loop
governance — with a browser dashboard on top.

```bash
npm install       # first run only
npm start         # → dashboard at http://localhost:5173, API at :8000
```

That's the whole setup. **No database, no docker, no API keys.** The catalog runs
in memory and the reasoning layer falls back to deterministic logic, so a clean
clone boots straight into a working dashboard.

If Python dependencies are missing, `npm start` tells you exactly what to run:

```bash
pip install -r requirements.txt
```

---

## What the dashboard shows

| View | What's in it |
|---|---|
| **Network** | Capacity concentration by country, live disruption feed, supplier master |
| **Simulate** | Run the pipeline live; scenario comparison, cost distribution, the cost-of-ESG curve, country risk, optimal supplier mix, ranked recommendations |
| **Governance** | Approval queue, full audit trail, escalation policy |
| **ESG** | Environmental/social/governance composition, GRI & SASB reports, leaderboard |

Light and dark themes, a colourblind-validated palette, and every chart has a
tooltip. Charts are hand-built SVG — no charting library, no CDN.

## How it works

```
Ingestion (optional)          Agent pipeline (per trigger)
  NewsAPI / RSS      ──┐        monitor → analyzer → simulator → recommender
  OpenWeatherMap     ──┼──→                                          │
  UN Comtrade        ──┘                                    ┌────────┴────────┐
                                                        auto-approve      [HITL gate]
                                                            │                 │
                                                            └────→ executor ←──┘
```

The pipeline streams over server-sent events, so the browser renders each node as
it happens. At the HITL gate the run **suspends** — it stays parked in the store
until a decision arrives, then resumes: approve goes to the executor, reject loops
back to the analyzer up to `max_iterations` times.

### Governance tiers

| Cost impact | Tier | Window | Behaviour |
|---|---|---|---|
| < $10k | auto | — | Executes without pausing |
| $10k–$100k | manager | 24 h | Pipeline suspends at the gate |
| ≥ $100k, or any supplier switch | c-suite | 48 h | Pipeline suspends at the gate |

## The simulation

Each scenario samples tariff shocks, port closures, weather delays, demand swings
and capacity cuts, then solves a supplier-allocation LP per iteration:

```
minimise   Σ xᵢ·cᵢ                    landed cost
subject to Σ xᵢ  = D                  demand
           0 ≤ xᵢ ≤ capᵢ              capacity
           Σ xᵢ·eᵢ ≥ E·D              ESG floor (optional)
```

Rather than calling a solver per iteration, the whole batch is solved at once.
Without the ESG row it's a continuous knapsack — fill cheapest first. With it,
the row is relaxed into a Lagrangian, bisected to the critical multiplier, and the
two bracketing solutions interpolated. Both are optimal for L(λ\*), so the
combination meeting the row with equality is the **exact** LP optimum, not an
approximation — verified against PuLP/CBC in the test suite.

The practical effect, measured on this machine:

| 1,000 iterations | Time |
|---|---|
| PuLP + CBC subprocess (the previous approach) | **161 s** |
| Vectorised, ESG floor active | **48 ms** |
| Vectorised, no floor | **0.4 ms** |

A full pipeline run — 3 scenarios × 2,000 iterations, plus the ESG frontier
sweep — completes in around **500 ms**.

### The cost-of-ESG curve

Once an ESG floor binds, every iteration lands on the constraint, so a
per-iteration Pareto front collapses to a single point. The frontier is therefore
computed by *re-solving at a series of floor levels*, which answers the question
actually worth asking: what does tightening the ESG requirement cost? The curve is
typically near-linear, then goes vertical once the optimiser is forced onto
whichever supplier has the highest score at any price.

## Choosing an LLM

One env var. No per-vendor SDK — every provider is reached over plain HTTP, so
swapping never means installing a package.

```bash
LLM_PROVIDER=none       # default: deterministic, free, no network
LLM_PROVIDER=ollama     # local models, nothing leaves the machine
LLM_PROVIDER=gemini     # GEMINI_API_KEY
LLM_PROVIDER=openai     # any OpenAI-compatible endpoint (Groq, Together, vLLM…)
LLM_PROVIDER=anthropic  # ANTHROPIC_API_KEY
```

**The numbers never come from the model.** Costs, risks and ESG deltas are always
computed from the simulation; a configured LLM only rewrites the prose of a
recommendation. If the provider is unset, unreachable, or returns unparseable
output, the pipeline carries on with rule-based text. Each recommendation is
labelled `LLM-authored` or `rule-based` in the UI.

`SOVEREIGN_MODE=true` forces Ollama for air-gapped deployment.

## Commands

```bash
npm start           # API + dashboard together
npm run api         # backend only, with --reload
npm run web         # dashboard only
npm run build       # production bundle → web/dist
npm test            # pytest (no DB, no keys, no network)
```

Or directly, if you prefer Python:

```bash
PYTHONPATH=src uvicorn orchestrator.main:app --reload
PYTHONPATH=src pytest tests/ -v
```

## Optional: Postgres

Only needed if you want persistence. Everything works without it.

```bash
docker compose up db -d
pip install "sqlalchemy[asyncio]" asyncpg pgvector alembic
PYTHONPATH=src alembic upgrade head
PYTHONPATH=src python scripts/seed_data.py
DATA_BACKEND=db npm start
```

Supplier IDs are deterministic UUIDv5 values, so they match between the in-memory
catalog and the seeded database. If the database is unreachable the app logs a
warning and falls back to memory rather than failing to boot.

## Optional: LangGraph

`USE_LANGGRAPH=true` (plus `pip install langgraph`) swaps the built-in pipeline
for a LangGraph one. It buys durable Postgres checkpointing — a 48-hour approval
window survives a restart. Both engines call the same node functions in
`orchestrator/pipeline/nodes.py`, so they cannot drift.

## Layout

```
src/orchestrator/
  simulation/allocator.py   vectorised LP solver (the hot path)
  simulation/engine.py      Monte Carlo engine
  simulation/optimizer.py   PuLP reference implementation / test oracle
  pipeline/nodes.py         the six agent nodes, shared by both engines
  pipeline/runner.py        native streaming pipeline with HITL suspend/resume
  pipeline/store.py         run registry + SSE fan-out with replay
  data/catalog.py           supplier/route/event catalog (memory or Postgres)
  llm/provider.py           swappable LLM backend
  esg/                      GRI / SASB scoring
  api/routes/               FastAPI endpoints
  agents/graph.py           optional LangGraph binding
web/src/
  components/charts.jsx     hand-built SVG charts
  views.jsx                 the four dashboard views
tests/                      49 tests, no external dependencies
```

## API

Interactive docs at <http://localhost:8000/docs>.

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/pipeline/runs` | Start a run |
| `GET /api/v1/pipeline/runs/{id}/stream` | SSE progress (replays history on connect) |
| `POST /api/v1/pipeline/runs/{id}/decision` | Approve / reject a suspended run |
| `GET /api/v1/pipeline/pending` | Runs awaiting approval |
| `GET /api/v1/pipeline/audit` | Governance audit trail |
| `GET /api/v1/catalog/overview` | Everything the landing view needs |
| `GET /api/v1/catalog/esg` | Supplier ESG leaderboard |
| `POST /api/v1/esg/report` | GRI / SASB portfolio report |
| `GET /health/` | Status, data backend, LLM provider |
