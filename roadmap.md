# Agentic Supply-Chain Resilience Orchestrator

Autonomous multi-agent system that monitors global supply-chain disruptions, runs Monte Carlo + LP simulations, and recommends or executes reroutes under human-in-the-loop governance with ESG scoring.

**Problem.** Global supply chains face compounding shocks: geopolitical tensions, shifting tariff regimes, climate-driven disruptions, and labour actions. Existing tools deliver *alerts*. This platform *acts*. McKinsey estimates geo-trade barriers now affect 40%+ of global goods flows; PwC projects a $1.8T shift in sourcing patterns over the next decade; Deloitte identifies autonomous agents as the next frontier of supply-chain management. No existing platform fully integrates agentic execution with climate/geo-risk modelling under human-in-the-loop governance.

**Value proposition.** One platform where autonomous agents continuously monitor, simulate 1,000+ disruption scenarios (tariffs, weather, strikes, geopolitical events), auto-recommend or execute reroutes, supplier switches, and inventory adjustments — with human-in-the-loop governance and built-in ESG/sustainability scoring for regulatory reporting.

**Differentiator.** No existing platform fully integrates all five of: agentic execution (not just alerts); climate + geo-risk in a single simulation model; human-in-the-loop governance with durable state (LangGraph checkpointing); ESG scoring natively tied to routing decisions; sovereign deployment for sensitive industries.

---

### Product surface

**1. Real-time data ingest** — UN Comtrade trade APIs (bilateral flow anomaly detection), news via semantic search (NewsAPI + RSS, embedded into pgvector), satellite/climate feeds (OpenWeatherMap, NOAA) for supplier hub monitoring, and IMF PortWatch port disruption data on daily ingestion.

**2. Multi-agent system** — LangGraph pipeline `Monitor → Analyzer → Simulator → Recommender → HITL Gate → Executor`. MonitorAgent does semantic search + LLM country risk scoring; AnalyzerAgent traces impacted suppliers/routes; SimulatorAgent runs Monte Carlo × LP; RecommenderAgent ranks Pareto-optimal recommendations (cost vs. ESG); the HITL Gate auto-approves low-risk actions and escalates high-impact ones; ExecutorAgent applies the approved recommendation and writes the audit log.

**3. Simulation engine** — 1,000+ stochastic Monte Carlo iterations per scenario (numpy vectorised, ~3s per 1,000), PuLP/CBC LP minimising total landed cost subject to demand + ESG constraints, 5 built-in scenario templates (US-China tariff shock, SE Asia typhoon, Suez Canal blockage, semiconductor shortage, West Coast port strike), and Pareto front cost-vs-ESG analysis.

**4. Human-in-the-loop governance** — full audit trail; LangGraph `interrupt_before` checkpointing lets a decision be made hours later with full state resume.

| Cost delta | Tier | Window |
|---|---|---|
| < $10k | Auto-approve | — |
| < $100k | Manager approval | 24 hours |
| >= $100k or supplier switch | C-suite / Procurement | 48 hours |

**5. ESG scoring** — weighted composite (0-100): Environmental 40% (CO2, certifications), Social 35% (labour standards, SA8000), Governance 25% (World Bank WGI index). GRI and SASB metric mapping for regulatory disclosure.

**6. Sovereign deployment** — optional air-gapped mode using Ollama (llama3:70b) as a drop-in replacement for cloud LLMs. Targets defence, pharma, and critical infrastructure.

---

### Tech stack

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

### Market

**Primary pilot** — mid-size fashion or electronics manufacturers, the industries hit hardest by recent tariff shifts and climate disruptions.

**Monetization** — $50k-$250k/year per enterprise seat, tiered by number of supplier nodes simulated, monthly ingestion volume, and governance tier (auto-approve only vs. full HITL workflow).

---

## Milestone: Foundation + Agent Loop

- [x] Project scaffolding (Docker, Postgres/pgvector, Alembic migrations) <!-- size: M; done: 2026-02-23 -->
- [x] Supplier + route DB schema with ESG fields <!-- size: S; done: 2026-02-23 -->
- [x] News/climate/trade ingestion pipelines (APScheduler) <!-- size: L; done: 2026-02-23 -->
- [x] LangGraph multi-agent pipeline (6 nodes) <!-- size: L; done: 2026-02-23 -->
- [x] Monte Carlo + PuLP simulation engine <!-- size: L; done: 2026-02-23 -->
- [x] HITL governance API (LangGraph interrupt/resume) <!-- size: M; done: 2026-02-23 -->
- [x] ESG scoring engine (GRI/SASB reports) <!-- size: M; done: 2026-02-23 -->
- [x] FastAPI: `/simulation`, `/governance`, `/esg` routes <!-- size: M; done: 2026-02-23 -->
- [x] 18 unit tests (simulation engine + ESG scorer) <!-- size: S; done: 2026-02-24 -->

## Milestone: Simulation Depth + Dashboard

### Streamlit/React digital-twin dashboard

- [ ] Scenario comparison charts (cost distribution, Pareto front) <!-- size: M -->
- [ ] ESG leaderboard and supplier map <!-- size: M -->
- [ ] Pending approvals queue <!-- size: S -->

### Platform

- [ ] Connect live APIs (UN Comtrade, NOAA, IMF PortWatch) <!-- size: L -->
- [ ] Redis/ARQ task queue (replace FastAPI BackgroundTasks) <!-- size: M -->
- [ ] Authentication (JWT via python-jose) <!-- size: M -->
- [ ] AWS deployment: ECS Fargate + RDS + ECR <!-- size: L -->

## Milestone: Enterprise Hardening

- [ ] Pilot with target manufacturer (fashion or electronics) <!-- size: XL -->
- [ ] Multi-tenant architecture (manufacturer isolation) <!-- size: L -->
- [ ] Prometheus metrics + structured logging (structlog) <!-- size: M -->
- [ ] SLA monitoring + alerting (PagerDuty webhook) <!-- size: S -->

## Milestone: Near-Term Extensions (6-12 months)

- [ ] Tier-2 and Tier-3 supplier visibility (n-tier dependency graph, Neo4j) <!-- size: XL -->
  - Map beyond direct suppliers to sub-tier networks using public company filings, news, and graph databases. Identify single points of failure three tiers deep — currently invisible to most manufacturers.
- [ ] ERP integration layer (SAP S/4HANA, Oracle Fusion, Microsoft Dynamics) <!-- size: XL -->
  - On approval, automatically create purchase orders, adjust safety-stock parameters, and trigger logistics bookings — closing the loop from insight to execution.
- [ ] Satellite imagery analysis (Planet Labs / Sentinel-2 capacity signals) <!-- size: L -->
  - Detect factory activity changes (parking lot density, heat signatures, container movement) as leading indicators of capacity disruption, before they surface in news or trade data.
- [ ] Carrier and freight market integration (Freightos, Xeneta rates in the LP) <!-- size: L -->
  - Real-time freight rate APIs and carrier capacity data, so the LP optimizer uses dynamic shipping cost and availability instead of static route costs.

## Milestone: Medium-Term Extensions (12-24 months)

- [ ] Supplier financial health scoring (credit ratings, payment behaviour, filings) <!-- size: L -->
  - A financially stressed supplier is a supply-chain risk before any physical disruption occurs.
- [ ] Demand forecasting integration (POS/order-book signals, Prophet/N-BEATS) <!-- size: XL -->
  - Drive the LP demand parameter dynamically from customer demand signals rather than a static annual volume, combined with external demand shocks (competitor recalls, trend spikes) via time-series ML.
- [ ] Contract and obligation management (LLM contract parsing into the recommender) <!-- size: L -->
  - Parse minimum order quantities, force-majeure clauses, and termination notice periods so suggested supplier switches respect legal obligations.
- [ ] Customs and trade compliance automation (HTS/HS monitoring and classification) <!-- size: XL -->
  - Real-time tariff schedule monitoring, automated Harmonized System classification via LLM, HS-code-level cost impact modelling, and draft import/export documentation attached to the rerouting recommendation.
- [ ] Collaborative supplier portal (self-reported capacity, gamified ESG) <!-- size: XL -->
  - Tier-1 suppliers self-report capacity, certifications, and disruptions. Gamified ESG scoring encourages certification upgrades; verified data replaces scraped estimates.

## Milestone: Long-Term Extensions (24-48 months)

- [ ] Digital twin of the entire supply chain (IoT, in-transit GPS, factory MES sync) <!-- size: XL -->
  - Real-time synchronisation between the simulated network model and physical reality. The simulation is no longer hypothetical — it mirrors the live state of the supply chain.
- [ ] Multi-company consortium mode (anonymised intelligence, differential privacy) <!-- size: XL -->
  - Multiple manufacturers in one industry share anonymised disruption intelligence and pool freight capacity. Differential privacy preserves competitive sensitivity; shared early warning benefits all participants.
- [ ] Autonomous negotiation agents (quote sourcing and term-sheet drafting) <!-- size: XL -->
  - Once a supplier switch is approved, LLM agents engage alternative suppliers via API or email, obtain quotes, and draft term sheets for human sign-off — compressing weeks of procurement into hours.
- [ ] Carbon credit and offset integration (Gold Standard, Verra audit trail) <!-- size: L -->
  - When a reroute reduces scope-3 CO2 by a verifiable amount, generate the audit trail needed to claim and sell carbon credits, turning ESG compliance into a revenue stream.
- [ ] Regulatory change monitoring (Federal Register, EU Official Journal, WTO) <!-- size: L -->
  - Continuously monitor regulatory feeds and model the supply-chain impact of proposed tariff changes or trade agreement amendments *before* they take effect — months of lead time rather than weeks.
- [ ] Predictive disruption scoring (proprietary ML risk models by country/commodity) <!-- size: XL -->
  - Train on historical disruption data, weather patterns, political risk indices, and satellite imagery to produce forward-looking disruption probabilities — moving from reactive monitoring to proactive prevention.
