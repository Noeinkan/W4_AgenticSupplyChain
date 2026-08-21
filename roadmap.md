# Agentic Supply-Chain Resilience Orchestrator

Autonomous multi-agent system that monitors global supply-chain disruptions, runs Monte Carlo + LP simulations, and recommends or executes reroutes under human-in-the-loop governance with ESG scoring.

**Problem.** Global supply chains face compounding shocks: geopolitical tensions, shifting tariff regimes, climate-driven disruptions, and labour actions. Existing tools deliver *alerts*. This platform *acts*. McKinsey estimates geo-trade barriers now affect 40%+ of global goods flows; PwC projects a $1.8T shift in sourcing patterns over the next decade; Deloitte identifies autonomous agents as the next frontier of supply-chain management. The incumbents that *do* act on disruptions keep the decision layer closed: you get a recommendation, not an optimum you can check.

**Value proposition.** One platform where autonomous agents continuously monitor, simulate 1,000+ disruption scenarios (tariffs, weather, strikes, geopolitical events), auto-recommend or execute reroutes, supplier switches, and inventory adjustments — with human-in-the-loop governance and built-in ESG/sustainability scoring for regulatory reporting.

**Differentiator.** Two of the five original claims no longer hold as differentiators, and saying so sharpens the rest. Disruption *sensing* is a solved commercial market (Resilinc EventWatchAI, Everstream, Interos), and the *agentic loop* is now shipping from the planning vendors — Kinaxis Maestro Agents with HITL guardrails, o9's sense-model-decide-execute-learn, SAP Joule. What none of them expose is the decision layer itself. The defensible edge is therefore narrower and harder to copy:

1. **A verifiable optimum.** The supplier-allocation LP is solved exactly — greedy fill, Lagrangian relaxation of the ESG row, bisection to the critical multiplier — and pinned against a PuLP/CBC oracle in CI. 1,000 iterations in 48 ms rather than 161 s. Commercial control towers keep this layer opaque; open-source projects loop a solver per scenario.
2. **ESG as a binding constraint, not a reported score.** Re-solving across floor levels prices the tightening — the cost-of-ESG curve answers what the requirement actually costs.
3. **The LLM never produces a number,** enforced architecturally and labelled per recommendation in the UI (`LLM-authored` vs `rule-based`).
4. **Sovereign deployment** for defence, pharma and critical infrastructure.
5. **A clean clone boots with no database, no keys and no Docker** — the whole platform runs on `requirements.txt` alone, and now pulls *live* disruption data on the same terms: PortWatch, NOAA and Comtrade are all keyless.

---

### Product surface

**1. Real-time data ingest** — five live sources, three of which need no API key, so a clean clone pulls real disruption data rather than a demo fixture. IMF PortWatch supplies daily AIS chokepoint transits, container port calls and the GDACS-backed disruptions database; NOAA supplies NWS alerts for the US port states and NHC active tropical cyclones; UN Comtrade supplies year-on-year bilateral flow collapses through its public preview endpoint. NewsAPI + RSS and OpenWeatherMap add coverage when their keys are set. Events are severity-scored, deduplicated by title, and published into the same catalog the monitor agent reads, on the in-memory backend as readily as on Postgres. `POST /api/v1/ingestion/run` fetches on demand; `ENABLE_INGESTION=true` runs the same collectors on an APScheduler loop.

**2. Multi-agent system** — pipeline `Monitor → Analyzer → Simulator → Recommender → HITL Gate → Executor`, streamed to the browser over server-sent events so each node renders as it happens. The native runner (`pipeline/runner.py`) is the default and needs no extra dependency; `USE_LANGGRAPH=true` swaps in a LangGraph binding for durable Postgres checkpointing. Both engines call the same node functions in `pipeline/nodes.py`, so they cannot drift. MonitorAgent does semantic search + LLM country risk scoring; AnalyzerAgent traces impacted suppliers/routes; SimulatorAgent runs Monte Carlo × LP; RecommenderAgent ranks Pareto-optimal recommendations (cost vs. ESG); the HITL Gate auto-approves low-risk actions and escalates high-impact ones; ExecutorAgent applies the approved recommendation and writes the audit log.

**3. Simulation engine** — 2,000 stochastic Monte Carlo iterations per scenario, numpy-vectorised, sampling tariff shocks, port closures, weather delays, demand swings and capacity cuts. The allocation LP (minimise landed cost, subject to demand equality, per-supplier capacity, and an optional ESG floor) is solved for the **whole batch at once** instead of once per iteration. PuLP/CBC survives only as the test oracle.

| 1,000 iterations | Time |
|---|---|
| PuLP + CBC subprocess (the original approach) | 161 s |
| Vectorised, ESG floor active | 48 ms |
| Vectorised, no floor | 0.4 ms |

A full run — 3 scenarios × 2,000 iterations plus the frontier sweep — completes in ~500 ms. Five built-in scenario templates (US-China tariff shock, SE Asia typhoon, Suez Canal blockage, semiconductor shortage, West Coast port strike). Once the ESG floor binds, every iteration lands on the constraint and a per-iteration Pareto front collapses to a single point, so the frontier is computed instead by re-solving at a series of floor levels: the **cost-of-ESG curve**.

**4. Human-in-the-loop governance** — full audit trail. At the gate the run suspends in the run store and resumes when a decision arrives hours later; a run awaiting approval is never evicted. Reject loops back to the analyzer, bounded by `max_iterations`. With LangGraph enabled, the 48-hour window survives a process restart via Postgres checkpointing.

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
| Language | Python 3.11+ |
| Web API | FastAPI + uvicorn, SSE streaming |
| Agents | Native runner (`pipeline/runner.py`); LangGraph optional for durable checkpointing |
| LLM | Provider-agnostic over plain HTTP — `none` / `ollama` / `gemini` / `openai` / `anthropic`, no per-vendor SDK |
| Simulation | numpy vectorised batch allocator; PuLP/CBC as test oracle only |
| Dashboard | React 18 + Vite, hand-built SVG charts (no charting library, no CDN) |
| Persistence | In-memory catalog by default; SQLAlchemy + asyncpg + pgvector optional |
| Ingestion | httpx against PortWatch / NOAA / Comtrade (keyless); APScheduler + feedparser optional |
| Infrastructure | Nothing required for dev; Docker Compose / AWS ECS Fargate + RDS (prod) |
| Sovereign mode | Ollama (air-gapped) |

---

### Market

**Primary pilot** — mid-size fashion or electronics manufacturers, the industries hit hardest by recent tariff shifts and climate disruptions.

**Monetization** — $50k-$250k/year per enterprise seat, tiered by number of supplier nodes simulated, monthly ingestion volume, and governance tier (auto-approve only vs. full HITL workflow).

---

## Milestone: 1. Foundation + Agent Loop

- [x] 1.1 Project scaffolding (Docker, Postgres/pgvector, Alembic migrations) <!-- size: M; done: 2026-02-23 -->
- [x] 1.2 Supplier + route DB schema with ESG fields <!-- size: S; done: 2026-02-23 -->
- [x] 1.3 News/climate/trade ingestion pipelines (APScheduler) <!-- size: L; done: 2026-02-23 -->
- [x] 1.4 LangGraph multi-agent pipeline (6 nodes) <!-- size: L; done: 2026-02-23 -->
- [x] 1.5 Monte Carlo + PuLP simulation engine <!-- size: L; done: 2026-02-23 -->
- [x] 1.6 HITL governance API (LangGraph interrupt/resume) <!-- size: M; done: 2026-02-23 -->
- [x] 1.7 ESG scoring engine (GRI/SASB reports) <!-- size: M; done: 2026-02-23 -->
- [x] 1.8 FastAPI: `/simulation`, `/governance`, `/esg` routes <!-- size: M; done: 2026-02-23 -->
- [x] 1.9 18 unit tests (simulation engine + ESG scorer) <!-- size: S; done: 2026-02-24 -->

## Milestone: 2. Simulation Depth + Dashboard

### React digital-twin dashboard

- [x] 2.1 Scenario comparison charts (cost distribution, Pareto front) <!-- size: M; done: 2026-08-21 -->
- [x] 2.2 ESG leaderboard and supplier map <!-- size: M; done: 2026-08-21 -->
- [x] 2.3 Pending approvals queue <!-- size: S; done: 2026-08-21 -->

### Engine + platform revamp

- [x] 2.8 Vectorised batch LP allocator (Lagrangian relaxation, bisection to lambda*) <!-- size: L; done: 2026-08-21 -->
  - Replaced the per-iteration CBC subprocess: 161 s to 48 ms per 1,000 iterations. Exact, not heuristic — pinned against PuLP by `test_allocator_matches_pulp_optimum`.
- [x] 2.9 Cost-of-ESG frontier by re-solving across floor levels <!-- size: M; done: 2026-08-21 -->
  - A per-iteration Pareto front collapses to a point once the floor binds, so the frontier sweeps the floor instead and prices the tightening.
- [x] 2.10 Native SSE streaming runner with HITL suspend/resume in the run store <!-- size: L; done: 2026-08-21 -->
- [x] 2.11 Provider-agnostic LLM layer over plain HTTP with rule-based fallback <!-- size: M; done: 2026-08-21 -->
  - One env var, no per-vendor SDK; every path degrades to deterministic text, and each recommendation is labelled `LLM-authored` or `rule-based`.
- [x] 2.12 Zero-dependency boot: in-memory catalog, no DB, keys or Docker <!-- size: M; done: 2026-08-21 -->
- [x] 2.13 Hand-built SVG chart library with light/dark themes and validated palette <!-- size: L; done: 2026-08-21 -->
- [x] 2.14 Test suite to 49 tests (allocator-vs-PuLP oracle, pipeline, ESG) <!-- size: M; done: 2026-08-21 -->

### Platform

- [x] 2.4 Connect live APIs (UN Comtrade, NOAA, IMF PortWatch) <!-- size: L; done: 2026-08-21 -->
  - All three need no API key, so a clean clone pulls real data: PortWatch chokepoint transits, port calls and the GDACS disruptions database; NOAA NWS alerts and NHC storms; Comtrade year-on-year flow collapses via the public preview endpoint.
  - Ingested events land in the catalog the monitor agent reads, so ingestion works on the in-memory backend instead of requiring Postgres. `POST /api/v1/ingestion/run` fetches on demand without APScheduler installed.
- [ ] 2.5 Redis/ARQ task queue (replace FastAPI BackgroundTasks) <!-- size: M -->
- [ ] 2.6 Authentication (JWT via python-jose) <!-- size: M -->
- [ ] 2.7 AWS deployment: ECS Fargate + RDS + ECR <!-- size: L -->

## Milestone: 3. Enterprise Hardening

- [ ] 3.1 Pilot with target manufacturer (fashion or electronics) <!-- size: XL -->
- [ ] 3.2 Multi-tenant architecture (manufacturer isolation) <!-- size: L -->
- [ ] 3.3 Prometheus metrics + structured logging (structlog) <!-- size: M -->
- [ ] 3.4 SLA monitoring + alerting (PagerDuty webhook) <!-- size: S -->

## Milestone: 4. Near-Term Extensions (6-12 months)

- [ ] 4.1 Tier-2 and Tier-3 supplier visibility (n-tier dependency graph, Neo4j) <!-- size: XL -->
  - Map beyond direct suppliers to sub-tier networks using public company filings, news, and graph databases. Identify single points of failure three tiers deep — currently invisible to most manufacturers.
- [ ] 4.2 ERP integration layer (SAP S/4HANA, Oracle Fusion, Microsoft Dynamics) <!-- size: XL -->
  - On approval, automatically create purchase orders, adjust safety-stock parameters, and trigger logistics bookings — closing the loop from insight to execution.
- [ ] 4.3 Satellite imagery analysis (Planet Labs / Sentinel-2 capacity signals) <!-- size: L -->
  - Detect factory activity changes (parking lot density, heat signatures, container movement) as leading indicators of capacity disruption, before they surface in news or trade data.
- [ ] 4.4 Carrier and freight market integration (Freightos, Xeneta rates in the LP) <!-- size: L -->
  - Real-time freight rate APIs and carrier capacity data, so the LP optimizer uses dynamic shipping cost and availability instead of static route costs.

## Milestone: 5. Medium-Term Extensions (12-24 months)

- [ ] 5.1 Supplier financial health scoring (credit ratings, payment behaviour, filings) <!-- size: L -->
  - A financially stressed supplier is a supply-chain risk before any physical disruption occurs.
- [ ] 5.2 Demand forecasting integration (POS/order-book signals, Prophet/N-BEATS) <!-- size: XL -->
  - Drive the LP demand parameter dynamically from customer demand signals rather than a static annual volume, combined with external demand shocks (competitor recalls, trend spikes) via time-series ML.
- [ ] 5.3 Contract and obligation management (LLM contract parsing into the recommender) <!-- size: L -->
  - Parse minimum order quantities, force-majeure clauses, and termination notice periods so suggested supplier switches respect legal obligations.
- [ ] 5.4 Customs and trade compliance automation (HTS/HS monitoring and classification) <!-- size: XL -->
  - Real-time tariff schedule monitoring, automated Harmonized System classification via LLM, HS-code-level cost impact modelling, and draft import/export documentation attached to the rerouting recommendation.
- [ ] 5.5 Collaborative supplier portal (self-reported capacity, gamified ESG) <!-- size: XL -->
  - Tier-1 suppliers self-report capacity, certifications, and disruptions. Gamified ESG scoring encourages certification upgrades; verified data replaces scraped estimates.

## Milestone: 6. Long-Term Extensions (24-48 months)

- [ ] 6.1 Digital twin of the entire supply chain (IoT, in-transit GPS, factory MES sync) <!-- size: XL -->
  - Real-time synchronisation between the simulated network model and physical reality. The simulation is no longer hypothetical — it mirrors the live state of the supply chain.
- [ ] 6.2 Multi-company consortium mode (anonymised intelligence, differential privacy) <!-- size: XL -->
  - Multiple manufacturers in one industry share anonymised disruption intelligence and pool freight capacity. Differential privacy preserves competitive sensitivity; shared early warning benefits all participants.
- [ ] 6.3 Autonomous negotiation agents (quote sourcing and term-sheet drafting) <!-- size: XL -->
  - Once a supplier switch is approved, LLM agents engage alternative suppliers via API or email, obtain quotes, and draft term sheets for human sign-off — compressing weeks of procurement into hours.
- [ ] 6.4 Carbon credit and offset integration (Gold Standard, Verra audit trail) <!-- size: L -->
  - When a reroute reduces scope-3 CO2 by a verifiable amount, generate the audit trail needed to claim and sell carbon credits, turning ESG compliance into a revenue stream.
- [ ] 6.5 Regulatory change monitoring (Federal Register, EU Official Journal, WTO) <!-- size: L -->
  - Continuously monitor regulatory feeds and model the supply-chain impact of proposed tariff changes or trade agreement amendments *before* they take effect — months of lead time rather than weeks.
- [ ] 6.6 Predictive disruption scoring (proprietary ML risk models by country/commodity) <!-- size: XL -->
  - Train on historical disruption data, weather patterns, political risk indices, and satellite imagery to produce forward-looking disruption probabilities — moving from reactive monitoring to proactive prevention.
