"""
Optional LangGraph binding.

    START -> monitor -> analyzer -> simulator -> recommender -> hitl_gate -> executor -> END
                                        ^                           |
                                        +------- reject loop -------+

This is a *binding*, not a second implementation: every node delegates to the
same functions in :mod:`orchestrator.pipeline.nodes` that the native runner
uses. Previously the two diverged, and this side had grown a hard
``langchain_core`` import that broke on a clean install.

The native runner in :mod:`orchestrator.pipeline.runner` is the default and
needs no extra packages. Set ``USE_LANGGRAPH=true`` to use this instead, which
buys durable Postgres checkpointing - graph state survives a restart, so a 48h
c-suite approval window outlives a deploy. It requires ``langgraph`` and, for
persistence, ``langgraph-checkpoint-postgres``.
"""

from __future__ import annotations

import logging
from typing import Literal

from orchestrator.pipeline import nodes

logger = logging.getLogger(__name__)


async def _monitor(state: dict) -> dict:
    from orchestrator.data.catalog import get_catalog

    working = dict(state)
    await nodes.monitor(working, await get_catalog())
    return {"active_events": working["active_events"], "risk_scores": working["risk_scores"],
            "narrative": working.get("narrative", "")}


async def _analyzer(state: dict) -> dict:
    from orchestrator.data.catalog import get_catalog

    working = dict(state)
    await nodes.analyzer(working, await get_catalog())
    return {"affected_suppliers": working["affected_suppliers"],
            "affected_routes": working["affected_routes"],
            "esg_baseline": working["esg_baseline"]}


async def _simulator(state: dict) -> dict:
    from orchestrator.data.catalog import get_catalog

    working = dict(state)
    await nodes.simulator(working, await get_catalog())
    return {"scenarios": working["scenarios"], "simulation_results": working["simulation_results"]}


async def _recommender(state: dict) -> dict:
    from orchestrator.data.catalog import get_catalog

    working = dict(state)
    await nodes.recommender(working, await get_catalog())
    return {"recommendations": working["recommendations"],
            "selected_recommendation": working["selected_recommendation"],
            "esg_projected": working.get("esg_projected", {})}


async def _hitl_gate(state: dict) -> dict:
    working = dict(state)
    nodes.hitl_gate(working)
    return {"hitl_required": working["hitl_required"], "hitl_decision": working["hitl_decision"],
            "hitl_tier": working["hitl_tier"],
            "approval_timeout_seconds": working["approval_timeout_seconds"],
            "selected_recommendation": working.get("selected_recommendation")}


async def _executor(state: dict) -> dict:
    working = dict(state)
    await nodes.executor(working)
    return {"execution_status": working["execution_status"],
            "execution_log": working["execution_log"]}


def _route_after_hitl(state: dict) -> Literal["executor", "increment_iter", "__end__"]:
    """approve -> execute, reject -> re-analyse (bounded), anything else -> stop."""
    from langgraph.graph import END

    if state.get("error"):
        return END
    decision = state.get("hitl_decision")
    if decision == "approve":
        return "executor"
    if decision == "reject":
        if state.get("iteration_count", 0) >= state.get("max_iterations", 3):
            logger.warning("Max re-analysis iterations reached - ending pipeline")
            return END
        return "increment_iter"
    return END


def _increment_iteration(state: dict) -> dict:
    return {"iteration_count": state.get("iteration_count", 0) + 1, "hitl_decision": None}


def build_graph(checkpointer=None):
    """Compile the graph. ``interrupt_before`` on the gate is what enables HITL."""
    from langgraph.graph import END, StateGraph

    from orchestrator.agents.state import SupplyChainState

    graph = StateGraph(SupplyChainState)
    graph.add_node("monitor", _monitor)
    graph.add_node("analyzer", _analyzer)
    graph.add_node("simulator", _simulator)
    graph.add_node("recommender", _recommender)
    graph.add_node("hitl_gate", _hitl_gate)
    graph.add_node("executor", _executor)
    graph.add_node("increment_iter", _increment_iteration)

    graph.set_entry_point("monitor")
    graph.add_edge("monitor", "analyzer")
    graph.add_edge("analyzer", "simulator")
    graph.add_edge("simulator", "recommender")
    graph.add_edge("recommender", "hitl_gate")
    graph.add_conditional_edges(
        "hitl_gate", _route_after_hitl,
        {"executor": "executor", "increment_iter": "increment_iter", END: END},
    )
    graph.add_edge("increment_iter", "analyzer")
    graph.add_edge("executor", END)

    compile_kwargs: dict = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
        # Pause before the gate so state is durable and the API can inject a decision.
        compile_kwargs["interrupt_before"] = ["hitl_gate"]
    return graph.compile(**compile_kwargs)


async def get_checkpointer():
    """Postgres checkpointer, falling back to in-memory when unavailable."""
    from orchestrator.config import settings

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        pg_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        checkpointer = AsyncPostgresSaver.from_conn_string(pg_url)
        await checkpointer.setup()
        logger.info("LangGraph checkpointing to Postgres")
        return checkpointer
    except Exception as exc:
        logger.warning("Postgres checkpointer unavailable (%s) - using MemorySaver", exc)
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
