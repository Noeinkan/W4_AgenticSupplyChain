"""
Oil, diesel, fertiliser and rare-earth tracking.

All against the in-memory catalog and captured shapes: no network, no key.
"""

from datetime import UTC, datetime

import pytest

from orchestrator.data import commodities
from orchestrator.data.catalog import Catalog
from orchestrator.ingestion import comtrade, news
from orchestrator.pipeline.nodes import monitor
from orchestrator.pipeline.runner import PipelineRun
from orchestrator.simulation.scenarios import select_relevant_scenarios

FAMILY_PROFILES = {
    "crude_oil": {"hs_codes": ["2709"], "supplier_countries": ["SA", "IQ", "NG"],
                  "annual_volume_units": 6_000_000, "min_esg_score": 50.0},
    "fertiliser": {"hs_codes": ["3102", "3104", "3105"], "supplier_countries": ["QA", "EG", "CA"],
                   "annual_volume_units": 960_000, "min_esg_score": 55.0},
    "rare_earths": {"hs_codes": ["2846", "8505"], "supplier_countries": ["CN"],
                    "annual_volume_units": 9_600_000, "min_esg_score": 50.0},
}


# -- family table ----------------------------------------------------------------

@pytest.mark.parametrize("code, family", [
    ("8505", "rare_earths"),   # longest prefix beats chapter 85
    ("8542", "electronics"),
    ("271019", "diesel"),      # a 6-digit subheading still resolves
    ("2709", "crude_oil"),
    ("3104", "fertiliser"),
    ("6104", "fashion"),
    ("9999", None),
])
def test_family_of_uses_longest_prefix(code, family):
    assert commodities.family_of(code) == family


def test_tag_text_maps_keywords_to_family_codes():
    codes = commodities.tag_text("Urea prices spike as diesel shortage hits farms")
    assert commodities.families_of(codes) == {"fertiliser", "diesel"}
    assert commodities.tag_text("Quarterly earnings beat expectations") == []


# -- catalog -----------------------------------------------------------------------

def test_bulk_commodities_have_no_air_lane_but_magnets_do():
    catalog = Catalog.in_memory()
    for supplier in catalog.suppliers:
        modes = {r["mode"] for r in catalog.routes_for(supplier["id"])}
        if commodities.is_bulk(supplier["commodity_codes"]):
            assert modes == {"sea"}, supplier["name"]
        else:
            assert "air" in modes, supplier["name"]


def test_gulf_loadings_are_exposed_on_every_sea_lane():
    catalog = Catalog.in_memory()
    gulf = [s for s in catalog.suppliers if s["country_code"] in {"SA", "IQ", "AE", "QA"}]
    assert gulf
    for supplier in gulf:
        assert all(r["through_affected_country"] for r in catalog.routes_for(supplier["id"]))


def test_alternatives_stay_inside_the_commodity_family():
    catalog = Catalog.in_memory()
    alternatives = catalog.alternatives(["2710"], exclude=set())
    assert alternatives
    assert all(commodities.families_of(s["commodity_codes"]) == {"diesel"} for s in alternatives)

    assert len(catalog.alternatives(None, exclude=set())) == len(catalog.suppliers)


# -- monitor -------------------------------------------------------------------------

async def test_rare_earth_event_reaches_the_magnet_buyer_not_the_garment_buyer():
    catalog = Catalog.in_memory()
    title = "China widens export licensing to rare-earth oxides and magnets"

    garments = {"manufacturer_profile": {"supplier_countries": ["CN", "VN"], "hs_codes": ["6104"]}}
    await monitor(garments, catalog)
    assert title not in [e["title"] for e in garments["active_events"]]

    # Listed suppliers outside China: the event still matters to this family.
    magnets = {"manufacturer_profile": {"supplier_countries": ["JP"], "hs_codes": ["8505"]}}
    await monitor(magnets, catalog)
    assert title in [e["title"] for e in magnets["active_events"]]


async def test_untagged_events_still_match_by_country():
    catalog = Catalog.in_memory()
    state = {"manufacturer_profile": {"supplier_countries": ["BD"], "hs_codes": ["6104"]}}
    await monitor(state, catalog)
    assert "Dhaka minimum wage review reopens" in [e["title"] for e in state["active_events"]]


# -- scenarios -----------------------------------------------------------------------

def test_hormuz_scenario_follows_gulf_risk_and_tanker_news():
    assert any(s["id"] == "hormuz_disruption" for s in select_relevant_scenarios({"SA": 0.7}, []))
    events = [{"event_type": "geopolitical", "title": "Tanker seized near Hormuz", "description": ""}]
    assert any(s["id"] == "hormuz_disruption" for s in select_relevant_scenarios({}, events))


def test_export_control_scenario_follows_rare_earth_news():
    events = [{"event_type": "tariff", "title": "Rare earth export licences stalled", "description": ""}]
    assert any(s["id"] == "china_export_controls" for s in select_relevant_scenarios({}, events))


# -- end to end ----------------------------------------------------------------------

@pytest.mark.parametrize("family", sorted(FAMILY_PROFILES))
async def test_commodity_run_only_allocates_within_its_family(family):
    profile = {"name": f"Test {family}", "industry": "other", "n_iterations": 200,
               "max_iterations": 1, **FAMILY_PROFILES[family]}
    run = PipelineRun(profile)
    async for event in run.stream():
        if event.status == "awaiting_approval":
            run.decide("approve", "test-approver", "automated test")

    catalog = Catalog.in_memory()
    results = run.state["simulation_results"]
    assert results
    for result in results.values():
        for mix in result["supplier_mix"]:
            supplier = catalog.supplier(mix["supplier_id"])
            assert family in commodities.families_of(supplier["commodity_codes"])


# -- ingestion -----------------------------------------------------------------------

def test_comtrade_batches_cover_every_watch_code_within_the_api_limit():
    batches = comtrade.hs_batches()
    assert all(len(b) <= comtrade.MAX_CODES_PER_CALL for b in batches)
    assert [c for b in batches for c in b] == commodities.watch_codes()
    assert {"2709", "2710", "3102", "2846", "8505"} <= set(commodities.watch_codes())


def test_keyless_comtrade_walks_every_batch_on_consecutive_days():
    batches = comtrade.hs_batches()
    seen = {
        tuple(comtrade.keyless_batch(datetime(2026, 10, day, tzinfo=UTC)))
        for day in range(1, 1 + len(batches))
    }
    assert seen == {tuple(b) for b in batches}


def test_comtrade_anomaly_on_rare_earths_maps_the_partner():
    flows = [
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "2846",
         "period": "2024", "primaryValue": 80_000_000},
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "2846",
         "period": "2025", "primaryValue": 30_000_000},
    ]
    [anomaly] = comtrade.detect_trade_anomalies(flows)
    assert anomaly["affected_countries"] == ["US", "CN"]
    assert commodities.families_of(anomaly["affected_hs_codes"]) == {"rare_earths"}


def test_news_rotation_gives_every_query_a_turn_within_a_day():
    seen = set()
    for hour in range(24):
        for minute in (0, 15, 30, 45):
            seen.update(news.queries_for_window(datetime(2026, 10, 18, hour, minute, tzinfo=UTC)))
    assert seen == set(news.SUPPLY_CHAIN_QUERIES)


def test_export_licensing_news_classifies_as_tariff():
    assert news.classify_event_type("Beijing tightens export licensing for rare earths") == "tariff"
