# Agentic Supply-Chain Resilience Orchestrator — Product Plan

## Problem Statement

Global supply chains face compounding shocks: geopolitical tensions, shifting tariff regimes, climate-driven disruptions, and labor actions. Existing tools deliver **alerts**. This platform **acts**.

McKinsey estimates geo-trade barriers now affect 40%+ of global goods flows. PwC projects a $1.8T shift in sourcing patterns over the next decade. Deloitte identifies autonomous agents as the next frontier of supply-chain management. No existing platform fully integrates agentic execution with climate/geo-risk modeling under human-in-the-loop governance.

---

## Value Proposition

One platform where autonomous agents continuously monitor, simulate 1,000+ disruption scenarios (tariffs, weather, strikes, geopolitical events), auto-recommend or execute reroutes, supplier switches, and inventory adjustments — with human-in-the-loop governance and built-in ESG/sustainability scoring for regulatory reporting.

---

## Key Features (MVP)

### 1. Real-Time Data Ingest
- Trade APIs (UN Comtrade) — bilateral flow anomaly detection
- News via semantic search (NewsAPI + RSS) — embedded into pgvector
- Satellite / climate feeds (OpenWeatherMap, NOAA) — supplier hub monitoring
- Port disruption data (IMF PortWatch) — daily ingestion

### 2. Multi-Agent System
LangGraph pipeline: **Monitor → Analyzer → Simulator → Recommender → HITL Gate → Executor**
- MonitorAgent: semantic search + LLM country risk scoring
- AnalyzerAgent: traces which suppliers/routes are impacted
- SimulatorAgent: runs Monte Carlo × LP optimization
- RecommenderAgent: ranks Pareto-optimal recs (cost vs. ESG)
- HITL Gate: auto-approves low-risk actions; escalates high-impact decisions
- ExecutorAgent: applies approved recommendation + writes audit log

### 3. Simulation Engine
- **Monte Carlo**: 1,000+ stochastic iterations per scenario (numpy vectorized, ~3s for 1,000 iterations)
- **LP Optimizer**: PuLP/CBC — minimize total landed cost subject to demand + ESG constraints
- **5 built-in scenario templates**: US-China tariff shock, SE Asia typhoon, Suez Canal blockage, semiconductor shortage, West Coast port strike
- **Pareto front analysis**: cost vs. ESG tradeoff visualization

### 4. Human-in-the-Loop Governance
| Cost Delta | Tier | Window |
|---|---|---|
| < $10k | Auto-approve | — |
| < $100k | Manager approval | 24 hours |
| ≥ $100k or supplier switch | C-suite / Procurement | 48 hours |

Full audit trail. LangGraph `interrupt_before` checkpointing allows decisions hours later with full state resume.

### 5. ESG Scoring
Weighted composite (0–100): Environmental 40% (CO₂, certifications), Social 35% (labour standards, SA8000), Governance 25% (World Bank WGI index). GRI and SASB metric mapping for regulatory disclosure.

### 6. Sovereign Deployment
Optional air-gapped mode using Ollama (llama3:70b) — drop-in replacement for cloud LLMs. Targets defence, pharma, and critical infrastructure industries.

---

## Tech Stack (MVP)

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web API | FastAPI + uvicorn |
| Agents | LangGraph 0.2 + LangChain Anthropic (Claude) |
| Vector search | LlamaIndex + pgvector (Postgres 16) |
| Simulation | numpy (MC) + PuLP/CBC (LP optimizer) |
| Ingestion | APScheduler + httpx + feedparser |
| Infrastructure | Docker Compose (dev) / AWS ECS Fargate + RDS (prod) |
| Sovereign mode | Ollama (air-gapped) |

---

## Build Path

### Phase 1 — Week 1–4: Foundation + Agent Loop
- [x] Project scaffolding (Docker, Postgres/pgvector, Alembic migrations)
- [x] Supplier + route DB schema with ESG fields
- [x] News/climate/trade ingestion pipelines (APScheduler)
- [x] LangGraph multi-agent pipeline (6 nodes)
- [x] Monte Carlo + PuLP simulation engine
- [x] HITL governance API (LangGraph interrupt/resume)
- [x] ESG scoring engine (GRI/SASB reports)
- [x] FastAPI: `/simulation`, `/governance`, `/esg` routes
- [x] 18 unit tests (simulation engine + ESG scorer)

### Phase 2 — Week 5–8: Simulation Depth + Dashboard
- [ ] Streamlit/React digital-twin dashboard
  - Scenario comparison charts (cost distribution, Pareto front)
  - ESG leaderboard and supplier map
  - Pending approvals queue
- [ ] Connect live APIs (UN Comtrade, NOAA, IMF PortWatch)
- [ ] Redis/ARQ task queue (replace FastAPI BackgroundTasks)
- [ ] Authentication (JWT via python-jose)
- [ ] AWS deployment: ECS Fargate + RDS + ECR

### Phase 3 — Week 9–12: Enterprise Hardening
- [ ] Pilot with target manufacturer (fashion or electronics)
- [ ] Multi-tenant architecture (manufacturer isolation)
- [ ] Prometheus metrics + structured logging (structlog)
- [ ] SLA monitoring + alerting (PagerDuty webhook)

---

## Target Market

**Primary pilot**: Mid-size fashion or electronics manufacturers — industries hit hardest by recent tariff shifts and climate disruptions.

**Monetization**: $50k–$250k/year per enterprise seat, tiered by:
- Number of supplier nodes simulated
- Monthly ingestion volume
- Governance tier (auto-approve only vs. full HITL workflow)

---

## Differentiator

No existing platform fully integrates:
1. **Agentic execution** (not just alerts — the system acts)
2. **Climate + geo-risk combination** in a single simulation model
3. **Human-in-the-loop governance** with durable state (LangGraph checkpointing)
4. **ESG/sustainability scoring** natively tied to routing decisions
5. **Sovereign deployment** for sensitive industries

---

## Potential Future Developments

### Near-Term (6–12 months)

**Tier-2 and Tier-3 Supplier Visibility**
Map beyond direct suppliers to sub-tier networks. Use public company filings, news, and graph databases (Neo4j) to model n-tier dependency chains. Identify single points of failure three tiers deep — currently invisible to most manufacturers.

**ERP Integration Layer**
Native connectors for SAP S/4HANA, Oracle Fusion, and Microsoft Dynamics. When a recommendation is approved, the system automatically creates purchase orders, adjusts safety-stock parameters, and triggers logistics bookings — closing the loop from insight to execution.

**Satellite Imagery Analysis**
Integrate Planet Labs or Sentinel-2 satellite feeds to detect factory activity changes (parking lot density, heat signatures, shipping container movement) as leading indicators of capacity disruptions before they appear in news or trade data.

**Carrier & Freight Market Integration**
Real-time freight rate APIs (Freightos, Xeneta) and carrier capacity data to include dynamic shipping cost and availability in the LP optimizer — not just static route costs.

---

### Medium-Term (12–24 months)

**Supplier Financial Health Scoring**
Ingest supplier credit ratings, payment behavior, and public financial filings to score financial distress risk. A financially stressed supplier is a supply-chain risk before any physical disruption occurs.

**Demand Forecasting Integration**
Connect to customer demand signals (POS data, order book, distributor sell-through) to drive the LP demand parameter dynamically rather than using a static annual volume. Combine with external demand shocks (competitor recalls, trend spikes) using time-series ML (Prophet, N-BEATS).

**Contract & Obligation Management**
Parse supplier contracts (minimum order quantities, force-majeure clauses, termination notice periods) using LLM document analysis. Surface contractual constraints in the recommendation engine so suggested supplier switches respect legal obligations.

**Customs & Trade Compliance Automation**
Real-time tariff schedule monitoring (HTS/HS code changes), automated Harmonized System classification using LLMs, and HS-code-level cost impact modeling. Generate draft import/export documentation as part of the rerouting recommendation.

**Collaborative Supplier Portal**
A supplier-facing web portal where tier-1 suppliers self-report capacity, certifications, and disruptions. Gamified ESG scoring encourages certification upgrades. Verified data replaces scraped estimates, improving simulation accuracy.

---

### Long-Term (24–48 months)

**Digital Twin of the Entire Supply Chain**
Real-time synchronization between the simulated network model and physical reality via IoT sensors at warehouses, in-transit GPS, and factory MES data. The simulation is no longer hypothetical — it mirrors the live state of the supply chain.

**Multi-Company Consortium Mode**
Multiple manufacturers in the same industry (e.g., competing fashion brands) share anonymized disruption intelligence and pool freight capacity through a consortium platform. Differential privacy preserves competitive sensitivity. Shared early-warning benefits all participants.

**Autonomous Negotiation Agents**
LLM-powered negotiation agents that, once a supplier switch is approved, autonomously engage alternative suppliers via API or email, obtain quotes, and draft term sheets for human sign-off — compressing weeks of procurement activity to hours.

**Carbon Credit & Offset Integration**
Connect ESG routing decisions to verified carbon credit markets (Gold Standard, Verra). When a reroute reduces scope-3 CO₂ by a verifiable amount, automatically generate the audit trail needed to claim and sell carbon credits, turning ESG compliance into a revenue stream.

**Regulatory Change Monitoring**
LLM agents that continuously monitor regulatory feeds (Federal Register, EU Official Journal, WTO notifications) and proactively model the supply-chain impact of proposed tariff changes or trade agreement amendments *before* they take effect — giving manufacturers months of lead time rather than weeks.

**Predictive Disruption Scoring**
Train proprietary ML models on historical disruption data, weather patterns, political risk indices, and satellite imagery to generate forward-looking disruption probability scores by country/commodity — moving from reactive monitoring to proactive risk prevention.
