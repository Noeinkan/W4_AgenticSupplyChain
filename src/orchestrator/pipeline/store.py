"""
Run registry with a fan-out event bus.

Replaces the bare module-level ``_runs: dict`` the simulation route used to keep,
which lost every result on reload and could not support more than one viewer.

Each run gets a broadcast hub, so several browser tabs can watch the same
pipeline live, and a tab that connects late still gets the events it missed:
subscribers are replayed the backlog before they start receiving new events.

Runs are held in memory and capped at ``max_runs`` (oldest completed run evicted
first). A paused run awaiting approval is never evicted - losing it would strand
a governance decision.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import OrderedDict
from typing import AsyncIterator

from orchestrator.pipeline.runner import PipelineEvent, PipelineRun

logger = logging.getLogger(__name__)


class _Hub:
    """Broadcasts a run's events to any number of subscribers, with replay."""

    def __init__(self) -> None:
        self.backlog: list[PipelineEvent] = []
        self.finished = False
        self._queues: set[asyncio.Queue] = set()

    def publish(self, event: PipelineEvent) -> None:
        self.backlog.append(event)
        for queue in self._queues:
            queue.put_nowait(event)

    def close(self) -> None:
        self.finished = True
        for queue in self._queues:
            queue.put_nowait(None)

    async def subscribe(self) -> AsyncIterator[PipelineEvent]:
        queue: asyncio.Queue = asyncio.Queue()
        replayed = len(self.backlog)
        for event in self.backlog:
            yield event
        if self.finished:
            return

        self._queues.add(queue)
        try:
            # Anything published between the replay and the subscribe.
            for event in self.backlog[replayed:]:
                yield event
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            self._queues.discard(queue)


class RunStore:
    """All pipeline runs for this process."""

    def __init__(self, max_runs: int = 50):
        self.max_runs = max_runs
        self._runs: OrderedDict[str, PipelineRun] = OrderedDict()
        self._hubs: dict[str, _Hub] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create(self, profile: dict) -> PipelineRun:
        run = PipelineRun(profile)
        self._runs[run.run_id] = run
        self._hubs[run.run_id] = _Hub()
        self._evict()
        return run

    def start(self, run: PipelineRun) -> None:
        """Launch the run in the background; events fan out through its hub."""
        if run.run_id in self._tasks:
            return
        self._tasks[run.run_id] = asyncio.create_task(self._drive(run))

    async def _drive(self, run: PipelineRun) -> None:
        hub = self._hubs[run.run_id]
        try:
            async for event in run.stream():
                hub.publish(event)
        finally:
            hub.close()
            self._tasks.pop(run.run_id, None)

    async def run_to_completion(self, run: PipelineRun) -> PipelineRun:
        """Drive a run synchronously. Returns as soon as it completes or pauses."""
        hub = self._hubs[run.run_id]
        self.start(run)
        while run.status in ("pending", "running"):
            await asyncio.sleep(0.01)
            if run.run_id not in self._tasks and hub.finished:
                break
        return run

    def get(self, run_id: str) -> PipelineRun | None:
        return self._runs.get(run_id)

    def list(self, limit: int = 25) -> list[PipelineRun]:
        return list(reversed(self._runs.values()))[:limit]

    def pending_approvals(self) -> list[PipelineRun]:
        return [r for r in self._runs.values() if r.status == "awaiting_approval"]

    def audit_log(self, limit: int = 100) -> list[dict]:
        """Every governance decision taken, newest first."""
        entries = []
        for run in reversed(self._runs.values()):
            decision = run.state.get("hitl_decision")
            if not decision:
                continue
            rec = run.state.get("selected_recommendation") or {}
            entries.append({
                "run_id": run.run_id,
                "thread_id": run.thread_id,
                "manufacturer": run.profile.get("name"),
                "rec_type": rec.get("rec_type"),
                "description": rec.get("description"),
                "cost_delta_usd": rec.get("cost_delta_usd"),
                "tier": run.state.get("hitl_tier"),
                "decision": decision,
                "approver": run.state.get("hitl_approver"),
                "notes": run.state.get("hitl_notes"),
                "decided_at": run.state.get("hitl_decided_at"),
                "execution_status": run.state.get("execution_status"),
            })
        return entries[:limit]

    async def subscribe(self, run_id: str) -> AsyncIterator[PipelineEvent]:
        hub = self._hubs.get(run_id)
        if hub is None:
            return
        async for event in hub.subscribe():
            yield event

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    def _evict(self) -> None:
        while len(self._runs) > self.max_runs:
            for run_id, run in self._runs.items():
                if run.status != "awaiting_approval":
                    self._runs.pop(run_id)
                    self._hubs.pop(run_id, None)
                    break
            else:
                return  # every run is paused; keep them all


_store: RunStore | None = None


def get_store() -> RunStore:
    global _store
    if _store is None:
        _store = RunStore()
    return _store
