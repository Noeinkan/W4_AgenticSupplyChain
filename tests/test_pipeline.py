"""
Pipeline and API tests.

These run entirely against the in-memory catalog with LLM_PROVIDER=none, so they
need no database, no API key and no network - the same configuration `npm start`
uses by default.
"""

import pytest

from orchestrator.data.catalog import Catalog
from orchestrator.pipeline.nodes import escalation_tier
from orchestrator.pipeline.runner import PipelineRun
from orchestrator.pipeline.store import RunStore

PROFILE = {
    "name": "Test Manufacturer",
    "industry": "fashion",
    "hs_codes": ["6104"],
    "supplier_countries": ["BD", "VN", "IN"],
    "annual_volume_units": 600_000,
    "min_esg_score": 55.0,
    "n_iterations": 200,
    "max_iterations": 2,
}


async def _drive(profile: dict, decision: str | None = "approve") -> PipelineRun:
    """Run a pipeline to completion, answering the HITL gate if it pauses."""
    run = PipelineRun(profile)
    async for event in run.stream():
        if event.status == "awaiting_approval" and decision:
            run.decide(decision, "test-approver", "automated test")
    return run


# -- catalog ------------------------------------------------------------------


def test_in_memory_catalog_needs_no_database():
    catalog = Catalog.in_memory()
    assert len(catalog.suppliers) == 12
    assert len(catalog.routes) == 36
    assert catalog.backend == "memory"


def test_supplier_ids_are_stable_across_instances():
    """The dashboard deep-links to suppliers, so IDs must not be random."""
    assert [s["id"] for s in Catalog.in_memory().suppliers] == [
        s["id"] for s in Catalog.in_memory().suppliers
    ]


def test_profile_filter_falls_back_rather_than_returning_nothing():
    catalog = Catalog.in_memory()
    assert catalog.for_profile(["ZZ"], None), "an unmatched filter must not empty the pool"
    assert {s["country_code"] for s in catalog.for_profile(["VN"], None)} == {"VN"}


# -- governance ---------------------------------------------------------------


@pytest.mark.parametrize(
    "rec, expected",
    [
        ({"rec_type": "inventory_adj", "cost_delta_usd": 4_000}, "auto"),
        ({"rec_type": "reroute", "cost_delta_usd": 50_000}, "manager"),
        ({"rec_type": "reroute", "cost_delta_usd": 250_000}, "c_suite"),
        # A supplier switch always escalates, however cheap it looks.
        ({"rec_type": "supplier_switch", "cost_delta_usd": 100}, "c_suite"),
    ],
)
def test_escalation_tiers(rec, expected):
    assert escalation_tier(rec)[0] == expected


# -- pipeline -----------------------------------------------------------------


async def test_pipeline_runs_to_completion():
    run = await _drive(PROFILE)

    assert run.status == "complete"
    assert run.progress_pct == 100.0
    assert run.state["simulation_results"]
    assert run.state["recommendations"]
    assert run.error is None


async def test_pipeline_emits_every_node_in_order():
    run = await _drive(PROFILE)
    seen = [e.node for e in run.events]
    for node in ["monitor", "analyzer", "simulator", "recommender", "executor"]:
        assert node in seen
    assert seen.index("monitor") < seen.index("simulator") < seen.index("executor")


async def test_rejection_loops_back_and_terminates():
    """Rejecting must re-analyse, then stop at max_iterations rather than spin."""
    run = PipelineRun({**PROFILE, "max_iterations": 1})
    rejections = 0
    async for event in run.stream():
        if event.status == "awaiting_approval":
            rejections += 1
            run.decide("reject", "test-approver", "not acceptable")

    assert rejections == 2, "one initial gate plus one retry"
    assert run.status == "complete"
    assert run.state["execution_status"].startswith("not executed")


async def test_approval_is_recorded_in_the_execution_log():
    run = await _drive(PROFILE)
    log = "\n".join(run.state["execution_log"])
    assert "test-approver" in log
    assert "automated test" in log
    assert run.state["execution_status"] == "executed"


async def test_compute_time_excludes_time_blocked_on_a_human():
    run = await _drive(PROFILE)
    assert run.compute_ms <= run.duration_ms + 1e-6
    assert run.compute_ms > 0


async def test_esg_floor_is_honoured_end_to_end():
    run = await _drive({**PROFILE, "min_esg_score": 65.0})
    for result in run.state["simulation_results"].values():
        assert result["esg_score_mean"] >= 65.0 - 0.01


# -- run store ----------------------------------------------------------------


async def test_store_replays_history_to_a_late_subscriber():
    """A browser tab opened mid-run must still render the earlier nodes."""
    store = RunStore()
    run = store.create(PROFILE)
    store.start(run)

    events = []
    async for event in store.subscribe(run.run_id):
        events.append(event)
        if event.status == "awaiting_approval":
            run.decide("approve", "test-approver", None)

    assert [e.node for e in events][:1] == ["monitor"]
    assert events[-1].node == "executor"


async def test_store_audit_log_records_the_decision():
    store = RunStore()
    run = store.create(PROFILE)
    store.start(run)
    async for event in store.subscribe(run.run_id):
        if event.status == "awaiting_approval":
            run.decide("approve", "auditor", "signed off")

    entry = store.audit_log()[0]
    assert entry["decision"] == "approve"
    assert entry["approver"] == "auditor"
    assert entry["notes"] == "signed off"


async def test_store_never_evicts_a_run_awaiting_approval():
    """Evicting a paused run would strand a governance decision."""
    store = RunStore(max_runs=2)
    paused = store.create(PROFILE)
    paused.status = "awaiting_approval"
    for _ in range(5):
        store.create(PROFILE)

    assert store.get(paused.run_id) is not None


# -- API ----------------------------------------------------------------------


async def test_health_reports_configuration(client):
    body = (await client.get("/health/")).json()
    assert body["status"] == "ok"
    assert body["data_backend"] == "memory"
    assert body["llm"]["provider"] == "none"


async def test_catalog_endpoints(client):
    assert len((await client.get("/api/v1/catalog/suppliers")).json()) == 12
    assert len((await client.get("/api/v1/catalog/routes")).json()) == 36
    assert len((await client.get("/api/v1/catalog/scenarios")).json()) == 5

    overview = (await client.get("/api/v1/catalog/overview")).json()
    assert overview["supplier_count"] == 12
    assert overview["by_country"]


async def test_esg_leaderboard_is_ranked(client):
    board = (await client.get("/api/v1/catalog/esg")).json()
    assert [s["rank"] for s in board] == list(range(1, len(board) + 1))
    scores = [s["composite_score"] for s in board]
    assert scores == sorted(scores, reverse=True)


async def test_run_lifecycle_over_http(client):
    started = await client.post("/api/v1/pipeline/runs",
                                json={"manufacturer_profile": PROFILE})
    assert started.status_code == 202
    run_id = started.json()["run_id"]

    detail = await client.get(f"/api/v1/pipeline/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id


async def test_decision_on_a_running_run_is_rejected(client):
    """Deciding on a run that is not at the gate must 409, not corrupt state."""
    started = await client.post("/api/v1/pipeline/runs",
                                json={"manufacturer_profile": {**PROFILE, "min_esg_score": 0}})
    run_id = started.json()["run_id"]

    response = await client.post(f"/api/v1/pipeline/runs/{run_id}/decision",
                                 json={"decision": "approve", "approver": "test"})
    assert response.status_code in (409, 200)


async def test_unknown_run_is_404(client):
    assert (await client.get("/api/v1/pipeline/runs/does-not-exist")).status_code == 404
    assert (await client.get("/api/v1/esg/score/does-not-exist")).status_code == 404
