"""
LangGraph supply-chain agent graph definition.

Topology:
  START → monitor → analyzer → simulator → recommender → hitl_gate → executor → END
                                                               ↑ reject (max 3x)
                                                           ←───┘ reanalyze loop

Key design decisions:
- interrupt_before=["hitl_gate"]: graph pauses before hitl_gate fires so the
  governance API can inject a human decision via graph.aupdate_state() then resume.
- AsyncPostgresSaver checkpointer: state survives restarts; 24h approval windows work.
- Conditional edge after hitl_gate: approve→executor, reject→analyzer (loop), timeout→END.
"""

import logging
from typing import Literal

from langgraph.graph import END, StateGraph

from orchestrator.agents import nodes
from orchestrator.agents.nodes import (
    analyzer,
    executor,
    hitl_gate,
    monitor,
    recommender,
    simulator,
)
from orchestrator.agents.state import SupplyChainState

logger = logging.getLogger(__name__)


def _route_after_hitl(
    state: SupplyChainState,
) -> Literal["executor", "analyzer", "__end__"]:
    """Conditional edge: decide where to go after the HITL gate."""
    if state.get("error"):
        return END

    decision = state.get("hitl_decision")
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    if decision == "approve":
        return "executor"

    if decision == "reject":
        if iteration >= max_iter:
            logger.warning("Max iterations (%d) reached — ending pipeline", max_iter)
            return END
        return "analyzer"

    # None = still waiting for human / timeout
    logger.info("HITL: no decision yet or timeout — ending pipeline")
    return END


def _increment_iteration(state: SupplyChainState) -> dict:
    """Small pass-through node that bumps the loop counter."""
    return {"iteration_count": state.get("iteration_count", 0) + 1}


def build_graph(checkpointer=None):
    """
    Build and compile the LangGraph.

    Args:
        checkpointer: An AsyncPostgresSaver instance (from langgraph-checkpoint-postgres).
                      Pass None for testing without persistence.

    Returns:
        Compiled LangGraph ready for .astream() or .ainvoke().
    """
    graph = StateGraph(SupplyChainState)

    # Register nodes
    graph.add_node("monitor", monitor.run)
    graph.add_node("analyzer", analyzer.run)
    graph.add_node("simulator", simulator.run)
    graph.add_node("recommender", recommender.run)
    graph.add_node("hitl_gate", hitl_gate.run)
    graph.add_node("executor", executor.run)
    graph.add_node("increment_iter", _increment_iteration)

    # Linear execution path
    graph.set_entry_point("monitor")
    graph.add_edge("monitor", "analyzer")
    graph.add_edge("analyzer", "simulator")
    graph.add_edge("simulator", "recommender")
    graph.add_edge("recommender", "hitl_gate")

    # After HITL: branch on human decision
    graph.add_conditional_edges(
        "hitl_gate",
        _route_after_hitl,
        {
            "executor": "executor",
            "analyzer": "increment_iter",  # rejection loops back via counter
            END: END,
        },
    )

    # Rejection loop: counter → back to analyzer for fresh recommendations
    graph.add_edge("increment_iter", "analyzer")
    graph.add_edge("executor", END)

    compile_kwargs: dict = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
        # Pause BEFORE hitl_gate so state is saved and API can inject decision
        compile_kwargs["interrupt_before"] = ["hitl_gate"]

    return graph.compile(**compile_kwargs)


async def get_checkpointer():
    """
    Create an AsyncPostgresSaver for LangGraph state persistence.
    Falls back to MemorySaver when DB isn't configured (dev/test).
    """
    from orchestrator.config import settings

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Convert asyncpg URL to plain postgres URL for psycopg
        pg_url = settings.database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        checkpointer = AsyncPostgresSaver.from_conn_string(pg_url)
        await checkpointer.setup()
        logger.info("Using AsyncPostgresSaver for LangGraph checkpointing")
        return checkpointer
    except Exception:
        logger.warning(
            "AsyncPostgresSaver unavailable — falling back to MemorySaver (no persistence)"
        )
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
