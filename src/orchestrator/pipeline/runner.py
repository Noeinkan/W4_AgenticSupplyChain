"""
The agent pipeline.

    monitor -> analyzer -> simulator -> recommender -> [hitl gate] -> executor

Same topology and same HITL semantics as the LangGraph version in
``orchestrator.agents.graph``, but with no framework dependency: a run is an
async generator of typed events, which is exactly what the dashboard's
server-sent-event stream needs, and it runs on a clean install.

HITL pause/resume works by suspending at the gate and returning control to the
caller. The run object stays in the store with ``status="awaiting_approval"``
until :meth:`PipelineRun.decide` supplies a decision, at which point the run
resumes from the gate - approve goes to the executor, reject loops back to the
analyzer up to ``max_iterations`` times.

If ``langgraph`` is installed and ``USE_LANGGRAPH=true``, the original compiled
graph is still available; this module is the default because it works without it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import AsyncIterator, Literal

from orchestrator.data.catalog import get_catalog
from orchestrator.pipeline import nodes
from orchestrator.pipeline.nodes import TIER_AUTO, TIER_CSUITE, TIER_MANAGER, escalation_tier

logger = logging.getLogger(__name__)

Decision = Literal["approve", "reject", "modify"]

NODE_SEQUENCE = ["monitor", "analyzer", "simulator", "recommender", "hitl_gate", "executor"]

@dataclass
class PipelineEvent:
    """One step of progress, streamed to the browser."""

    run_id: str
    node: str
    status: str
    progress_pct: float
    message: str
    payload: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "node": self.node,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "message": self.message,
            "payload": self.payload,
            "ts": self.ts,
        }


class PipelineRun:
    """A single execution of the pipeline, including its paused state."""

    def __init__(self, profile: dict):
        self.run_id = str(uuid.uuid4())
        self.thread_id = str(uuid.uuid4())
        self.profile = profile
        self.status = "pending"
        self.progress_pct = 0.0
        self.created_at = datetime.now(UTC)
        self.completed_at: datetime | None = None
        self.duration_ms: float = 0.0
        self.compute_ms: float = 0.0
        self._waiting_ms: float = 0.0
        self.error: str | None = None

        self.events: list[PipelineEvent] = []
        self.state: dict = {
            "manufacturer_profile": profile,
            "active_events": [],
            "risk_scores": {},
            "affected_suppliers": [],
            "affected_routes": [],
            "scenarios": [],
            "simulation_results": {},
            "recommendations": [],
            "selected_recommendation": None,
            "hitl_required": False,
            "hitl_decision": None,
            "hitl_notes": None,
            "hitl_tier": TIER_AUTO,
            "approval_timeout_seconds": 0,
            "execution_status": "pending",
            "execution_log": [],
            "esg_baseline": {},
            "esg_projected": {},
            "iteration_count": 0,
            "max_iterations": int(profile.get("max_iterations", 3)),
            "narrative": "",
        }
        self._decision = asyncio.Event()

    # -- public API -----------------------------------------------------------

    def decide(self, decision: Decision, approver: str, notes: str | None) -> None:
        """Inject a human decision and release the paused gate."""
        self.state["hitl_decision"] = decision
        self.state["hitl_notes"] = notes
        self.state["hitl_approver"] = approver
        self.state["hitl_decided_at"] = datetime.now(UTC).isoformat()
        self._decision.set()

    def summary(self) -> dict:
        rec = self.state.get("selected_recommendation") or {}
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "manufacturer": self.profile.get("name"),
            "industry": self.profile.get("industry"),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": round(self.duration_ms, 1),
            "compute_ms": round(self.compute_ms, 1),
            "scenario_count": len(self.state.get("simulation_results") or {}),
            "iterations": int(self.profile.get("n_iterations", 1000)),
            "hitl_required": self.state.get("hitl_required", False),
            "hitl_tier": self.state.get("hitl_tier"),
            "hitl_decision": self.state.get("hitl_decision"),
            "top_recommendation": rec.get("description"),
            "cost_delta_usd": rec.get("cost_delta_usd"),
            "error": self.error,
        }

    def detail(self) -> dict:
        return {
            **self.summary(),
            "profile": self.profile,
            "risk_scores": self.state.get("risk_scores", {}),
            "active_events": self.state.get("active_events", []),
            "affected_suppliers": self.state.get("affected_suppliers", []),
            "scenarios": self.state.get("scenarios", []),
            "scenario_results": list((self.state.get("simulation_results") or {}).values()),
            "recommendations": self.state.get("recommendations", []),
            "selected_recommendation": self.state.get("selected_recommendation"),
            "esg_baseline": self.state.get("esg_baseline", {}),
            "esg_projected": self.state.get("esg_projected", {}),
            "execution_status": self.state.get("execution_status"),
            "execution_log": self.state.get("execution_log", []),
            "narrative": self.state.get("narrative", ""),
            "events": [e.to_dict() for e in self.events],
        }

    # -- execution ------------------------------------------------------------

    async def stream(self) -> AsyncIterator[PipelineEvent]:
        """Run the pipeline, yielding an event per node transition."""
        started = time.perf_counter()
        self.status = "running"
        try:
            async for event in self._execute():
                self.events.append(event)
                self.progress_pct = event.progress_pct
                # Kept current on every event, not just at the end, so a run
                # paused at the approval gate still reports the work it has done.
                # compute_ms excludes time blocked on a human, which is the
                # number worth quoting for simulation throughput.
                self.duration_ms = (time.perf_counter() - started) * 1000
                self.compute_ms = self.duration_ms - self._waiting_ms
                yield event
        except Exception as exc:
            logger.exception("Pipeline %s failed", self.run_id)
            self.status = "failed"
            self.error = str(exc)
            self.completed_at = datetime.now(UTC)
            failure = PipelineEvent(self.run_id, "error", "failed", self.progress_pct, str(exc))
            self.events.append(failure)
            yield failure
        finally:
            self.duration_ms = (time.perf_counter() - started) * 1000
            self.compute_ms = self.duration_ms - self._waiting_ms

    async def _execute(self) -> AsyncIterator[PipelineEvent]:
        catalog = await get_catalog()

        yield self._event("monitor", "running", 5, "Scanning disruption feeds")
        await nodes.monitor(self.state, catalog)
        yield self._event(
            "monitor", "done", 18,
            f"{len(self.state['active_events'])} active events, "
            f"{sum(1 for v in self.state['risk_scores'].values() if v >= 0.3)} countries at risk",
            {"risk_scores": self.state["risk_scores"], "events": self.state["active_events"]},
        )

        while True:
            yield self._event("analyzer", "running", 25, "Tracing exposure through the supplier graph")
            await nodes.analyzer(self.state, catalog)
            yield self._event(
                "analyzer", "done", 35,
                f"{len(self.state['affected_suppliers'])} suppliers exposed",
                {"affected_suppliers": self.state["affected_suppliers"]},
            )

            n_iter = int(self.profile.get("n_iterations", 1000))
            yield self._event("simulator", "running", 45, f"Running {n_iter:,} Monte Carlo iterations")
            elapsed = await nodes.simulator(self.state, catalog)
            yield self._event(
                "simulator", "done", 70,
                f"{len(self.state['simulation_results'])} scenarios simulated in {elapsed:.0f} ms",
                {"scenario_results": list(self.state["simulation_results"].values())},
            )

            yield self._event("recommender", "running", 78, "Ranking mitigations")
            await nodes.recommender(self.state, catalog)
            yield self._event(
                "recommender", "done", 88,
                f"{len(self.state['recommendations'])} recommendations generated",
                {"recommendations": self.state["recommendations"]},
            )

            gate = nodes.hitl_gate(self.state)
            if gate == "pause":
                self.status = "awaiting_approval"
                rec = self.state["selected_recommendation"] or {}
                yield self._event(
                    "hitl_gate", "awaiting_approval", 90,
                    f"{self.state['hitl_tier'].replace('_', '-')} approval required "
                    f"for ${abs(float(rec.get('cost_delta_usd') or 0)):,.0f} decision",
                    {"recommendation": rec, "tier": self.state["hitl_tier"]},
                )
                waited = time.perf_counter()
                await self._decision.wait()
                self._waiting_ms += (time.perf_counter() - waited) * 1000
                self._decision.clear()
                self.status = "running"

            decision = self.state.get("hitl_decision")
            yield self._event(
                "hitl_gate", "done", 92, f"Decision: {decision}",
                {"decision": decision, "notes": self.state.get("hitl_notes")},
            )

            if decision == "reject" and self.state["iteration_count"] < self.state["max_iterations"]:
                self.state["iteration_count"] += 1
                self.state["hitl_decision"] = None
                yield self._event(
                    "analyzer", "retry", 30,
                    f"Rejected - re-analysing (attempt {self.state['iteration_count'] + 1}"
                    f"/{self.state['max_iterations'] + 1})",
                )
                continue
            break

        yield self._event("executor", "running", 95, "Applying decision")
        await nodes.executor(self.state)
        self.status = "complete"
        self.completed_at = datetime.now(UTC)
        yield self._event(
            "executor", "done", 100, self.state["execution_status"],
            {"execution_log": self.state["execution_log"]},
        )

    def _event(self, node, status, pct, message, payload=None) -> PipelineEvent:
        return PipelineEvent(self.run_id, node, status, float(pct), message, payload or {})

