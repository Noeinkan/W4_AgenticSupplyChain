"""
Shared state schema for the LangGraph supply-chain agent pipeline.

The Annotated[list, operator.add] pattern is LangGraph's reducer convention:
nodes return partial dicts and LangGraph *appends* list fields automatically.
Scalar fields are simply overwritten by the latest node that sets them.
"""

import operator
from typing import Annotated, Literal, TypedDict


class SupplyChainState(TypedDict):
    # ---- Input ----------------------------------------------------------------
    manufacturer_profile: dict
    """Industry, HS codes, supplier countries, annual volume, min ESG floor."""

    trigger_event_id: str | None
    """Optional: a specific event that triggered this pipeline run."""

    # ---- Monitor node output --------------------------------------------------
    active_events: Annotated[list[dict], operator.add]
    """Disruption events relevant to this manufacturer (appended each cycle)."""

    risk_scores: dict[str, float]
    """Country-level risk scores {ISO2: 0.0–1.0} from the monitor agent."""

    # ---- Analyzer node output -------------------------------------------------
    affected_suppliers: list[dict]
    """Suppliers directly impacted by active events (with impact_score field)."""

    affected_routes: list[dict]
    """Routes impacted, with adjusted cost/delay estimates."""

    # ---- Simulator node output ------------------------------------------------
    scenarios: Annotated[list[dict], operator.add]
    """Scenario parameter dicts passed to the Monte Carlo engine."""

    simulation_results: dict[str, dict]
    """Keyed by scenario ID; values are SimulationResult dicts."""

    # ---- Recommender node output ----------------------------------------------
    recommendations: Annotated[list[dict], operator.add]
    """Ranked list of recommended actions (reroute, supplier_switch, inventory_adj)."""

    selected_recommendation: dict | None
    """The top recommendation chosen by the recommender agent."""

    # ---- HITL gate ------------------------------------------------------------
    hitl_required: bool
    """True when a human approval is needed before execution."""

    hitl_decision: Literal["approve", "reject", "modify"] | None
    """Set by the governance API after human review."""

    hitl_notes: str | None
    """Optional notes from the approver."""

    approval_timeout_seconds: int
    """How long to wait for human approval before timing out (default: 86400 = 24h)."""

    # ---- Executor node output -------------------------------------------------
    execution_status: Literal["pending", "executing", "done", "failed"] | None
    execution_log: Annotated[list[str], operator.add]

    # ---- ESG ------------------------------------------------------------------
    esg_baseline: dict
    """ESG score breakdown for current supplier portfolio."""

    esg_projected: dict
    """Projected ESG score if the selected recommendation is executed."""

    # ---- Control flow ---------------------------------------------------------
    thread_id: str | None
    """LangGraph checkpoint thread ID — passed through for API continuations."""

    iteration_count: int
    """Number of recommend→HITL→reanalyze cycles completed."""

    max_iterations: int
    """Circuit-breaker: stop looping after this many rejections (default: 3)."""

    messages: Annotated[list, operator.add]
    """LangChain message history (for LLM context)."""

    error: str | None
    """Set if any node encounters an unrecoverable error."""
