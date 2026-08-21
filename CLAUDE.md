# CLAUDE.md — Agentic Supply-Chain Resilience Orchestrator

## Project overview
Multi-agent system that monitors supply-chain disruptions, runs vectorised Monte Carlo
+ LP simulations, and recommends reroutes under HITL governance, with a React dashboard.

## Run commands
```bash
npm start                                    # API :8000 + dashboard :5173
npm test                                     # pytest, no DB/keys/network needed
npm run build                                # production bundle
PYTHONPATH=src uvicorn orchestrator.main:app --reload   # backend only
```
`npm start` needs only `pip install -r requirements.txt`. Postgres, LangGraph,
ingestion and any LLM are all optional and guarded at import time.

## Key files
| Purpose | Path |
|---|---|
| Vectorised LP solver (hot path) | `src/orchestrator/simulation/allocator.py` |
| Monte Carlo engine | `src/orchestrator/simulation/engine.py` |
| PuLP reference / test oracle | `src/orchestrator/simulation/optimizer.py` |
| Agent nodes (shared by both engines) | `src/orchestrator/pipeline/nodes.py` |
| Native streaming pipeline | `src/orchestrator/pipeline/runner.py` |
| Run store + SSE fan-out | `src/orchestrator/pipeline/store.py` |
| Data catalog (memory or Postgres) | `src/orchestrator/data/catalog.py` |
| Swappable LLM backend | `src/orchestrator/llm/provider.py` |
| FastAPI entry | `src/orchestrator/main.py` |
| Settings | `src/orchestrator/config.py` |
| Optional LangGraph binding | `src/orchestrator/agents/graph.py` |
| Charts (hand-built SVG) | `web/src/components/charts.jsx` |
| Dashboard views | `web/src/views.jsx` |
| Tests | `tests/` |

## Architecture
```
monitor → analyzer → simulator → recommender → [hitl gate] → executor
                         ↑                          │
                         └──── reject loop ─────────┘   (bounded by max_iterations)
```
Streams over SSE. At the gate the run suspends in the store until a decision
arrives. Both the native runner and the LangGraph binding call the same functions
in `pipeline/nodes.py` — never fork them.

## Critical invariants

**The allocator must stay exactly optimal.** `solve_batch` replaced a
per-iteration CBC subprocess (161 s → 48 ms per 1,000 iterations). It is not a
heuristic: greedy fill for the box+demand LP, then Lagrangian relaxation on the
ESG row, bisection to λ*, and interpolation between the bracketing solutions.
`tests/test_simulation.py::test_allocator_matches_pulp_optimum` pins this against
PuLP. If you touch `allocator.py`, that test must still pass.

**When `min_esg_score > 0`, the demand constraint is equality (`== demand`), not
`>=`.** With `>=` the LP satisfies the ESG sum by over-allocating a low-ESG
supplier beyond demand — a silent correctness bug. Applies to both
`allocator.solve_batch` and `optimizer.solve_routing_lp`.

**The LLM never produces numbers.** Costs, risk and ESG deltas come from the
simulation. A configured provider only rewrites `description` and `rationale`.
Every path through `llm/provider.py` must degrade to the caller's fallback.

**A run awaiting approval is never evicted from the store** — that would strand a
governance decision.

## HITL governance tiers
| Cost delta | Tier | Window |
|---|---|---|
| < $10k | auto-approve | — |
| < $100k | manager | 24 h |
| ≥ $100k or any supplier switch | c-suite | 48 h |

## Configuration
| Env var | Default | Effect |
|---|---|---|
| `DATA_BACKEND` | `memory` | `db` uses Postgres, falls back to memory if down |
| `LLM_PROVIDER` | `none` | `none` \| `ollama` \| `gemini` \| `openai` \| `anthropic` |
| `LLM_MODEL` | *(blank)* | Provider default when blank |
| `USE_LANGGRAPH` | `false` | `true` needs `pip install langgraph` |
| `ENABLE_INGESTION` | `false` | `true` needs `apscheduler` + API keys |
| `SOVEREIGN_MODE` | `false` | Forces `LLM_PROVIDER=ollama` |

## Tech stack
Python 3.11+ · FastAPI · numpy · PuLP (test oracle only) · React 18 · Vite ·
hand-built SVG charts (no charting library). Optional: SQLAlchemy/asyncpg/pgvector,
LangGraph, APScheduler.

## Coding conventions
- `PYTHONPATH=src` for every Python command (`npm` scripts set it for you)
- Optional dependencies must be imported inside functions and guarded — the app
  has to boot on `requirements.txt` alone
- Charts follow `dataviz`: fixed categorical slot order (never cycled), one-hue
  sequential ramps for magnitude, no dual-axis charts, legend + direct labels for
  any multi-series chart, validated palette in `web/src/theme.css`
- Tests must not require a live DB, API key, or network
- Do not add docstrings, comments, or type annotations to unchanged code
