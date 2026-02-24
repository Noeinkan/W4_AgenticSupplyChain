# Agentic Supply-Chain Resilience Orchestrator

Autonomous agents that continuously monitor global supply-chain disruptions (tariffs, weather, strikes, geopolitical shocks), simulate 1,000+ scenarios via Monte Carlo + LP optimization, and recommend or execute reroutes — with human-in-the-loop governance and built-in ESG/sustainability scoring.

**Target market:** Fashion + electronics manufacturers ($50k–$250k/year per enterprise seat)

---

## Architecture

```
Ingestion (15min/30min/daily)
  NewsAPI + RSS → pgvector semantic search
  OpenWeatherMap → supplier hub alerts
  UN Comtrade → trade-flow anomaly detection

LangGraph Pipeline (per trigger)
  monitor → analyzer → simulator → recommender → [HITL gate] → executor

Simulation Engine
  5 scenario templates × 1,000 Monte Carlo iterations
  PuLP LP optimizer: min Σ(x_i × landed_cost_i) s.t. demand + ESG constraints

FastAPI
  POST /api/v1/simulation/trigger   → async pipeline start
  GET  /api/v1/simulation/{id}/results
  POST /api/v1/governance/decision  → HITL approve/reject/modify
  GET  /api/v1/governance/pending
  POST /api/v1/esg/report           → GRI/SASB report
  GET  /api/v1/esg/leaderboard
```

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web API | FastAPI + uvicorn |
| Agents | LangGraph + LangChain Anthropic |
| Embeddings | OpenAI text-embedding-ada-002 + pgvector |
| Simulation | numpy (Monte Carlo) + PuLP/CBC (LP) |
| Database | Postgres 16 + pgvector extension |
| Ingestion | APScheduler + httpx + feedparser |
| Sovereign mode | Ollama (llama3:70b) — air-gapped deployment |
| Infra | Docker Compose (dev) / ECS Fargate + RDS (prod) |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Python 3.11+
- Poetry (`pip install poetry`)

### 1. Clone and configure
```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY (required) and optionally OPENAI_API_KEY, NEWSAPI_KEY
```

### 2. Start Postgres
```bash
docker compose up db -d
```

### 3. Install dependencies
```bash
poetry install
```

### 4. Run migrations + seed data
```bash
PYTHONPATH=src alembic upgrade head
PYTHONPATH=src python scripts/seed_data.py
```

### 5. Start the API
```bash
PYTHONPATH=src uvicorn orchestrator.main:app --reload
```

Open **http://localhost:8000/docs** for the interactive API docs.

---

## Usage

### Trigger a simulation

```bash
curl -X POST http://localhost:8000/api/v1/simulation/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "manufacturer_profile": {
      "name": "AcmeFashion",
      "industry": "fashion",
      "hs_codes": ["6104", "6201"],
      "supplier_countries": ["CN", "VN", "BD"],
      "annual_volume_units": 500000
    }
  }'
# Returns: {"run_id": "...", "thread_id": "..."}
```

### Poll status
```bash
curl http://localhost:8000/api/v1/simulation/{run_id}/status
```

### Approve a HITL recommendation
```bash
curl -X POST http://localhost:8000/api/v1/governance/decision \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "...",
    "recommendation_id": "...",
    "decision": "approve",
    "approver": "jane.doe@company.com",
    "notes": "Approved — Q4 risk exposure justifies cost increase"
  }'
```

### Get ESG report (GRI standard)
```bash
curl -X POST http://localhost:8000/api/v1/esg/report \
  -H "Content-Type: application/json" \
  -d '{"standard": "GRI"}'
```

---

## Scenario Templates

| ID | Name | Type |
|---|---|---|
| `china_tariff_25pct` | US-China 25% Tariff Shock | tariff |
| `sea_typhoon_season` | SE Asia Typhoon Season | weather |
| `suez_canal_blockage` | Suez Canal Closure | geopolitical |
| `semiconductor_shortage` | Global Semiconductor Shortage | supply |
| `west_coast_port_strike` | West Coast Port Strike | strike |

---

## HITL Governance Tiers

| Cost Delta | Tier | Approval Window |
|---|---|---|
| < $10k | Auto-approve | — |
| < $100k | Manager | 24 hours |
| ≥ $100k or supplier switch | C-suite / Procurement | 48 hours |

---

## Sovereign (Air-Gapped) Mode

For sensitive industries (defence, pharma) that can't use cloud LLMs:

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3:70b

# Set in .env
SOVEREIGN_MODE=true
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3:70b
```

---

## Running Tests

```bash
PYTHONPATH=src pytest tests/ -v
```

Tests cover: LP optimizer, Monte Carlo engine, ESG scoring — no DB or API keys needed.

---

## Project Structure

```
src/orchestrator/
├── main.py              # FastAPI app
├── config.py            # Settings (pydantic-settings)
├── db/                  # SQLAlchemy models + repositories
├── ingestion/           # News, weather, trade data ingest
├── agents/              # LangGraph nodes + tools
│   └── nodes/           # monitor → analyzer → simulator → recommender → hitl → executor
├── simulation/          # Monte Carlo + PuLP LP optimizer
├── esg/                 # ESG scoring + GRI/SASB report generation
├── api/                 # FastAPI routes + schemas
└── sovereign/           # Ollama air-gapped LLM module
```
