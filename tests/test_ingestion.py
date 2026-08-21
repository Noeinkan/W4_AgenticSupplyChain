"""
Ingestion tests.

Every live feed is exercised through its pure transform - the function that turns
a decoded API payload into event dicts - with fixtures captured from the real
responses. Nothing here opens a socket, reads a key or touches a database.
"""

from datetime import date, timedelta

import pytest

from orchestrator.data.catalog import Catalog
from orchestrator.ingestion import collector, comtrade, noaa, portwatch, sink


_SERIES_START = date(2026, 6, 1)


def _daily_series(portid, value_field, values):
    """One row per day, in the ``YYYY-MM-DD`` string form the ArcGIS feeds return."""
    return [
        {
            "date": (_SERIES_START + timedelta(days=i)).isoformat(),
            "portid": portid,
            "portname": "Suez Canal",
            "country": "Egypt",
            "ISO3": "EGY",
            value_field: v,
        }
        for i, v in enumerate(values)
    ]


# -- PortWatch: drop detection -------------------------------------------------

def test_flow_drop_detects_sustained_collapse():
    rows = _daily_series("chokepoint1", "n_container", [20] * 28 + [8] * 7)
    drop = portwatch.detect_flow_drop(rows, "n_container")

    assert drop is not None
    assert drop["change"] == pytest.approx(-0.60)
    assert drop["recent"] == pytest.approx(8.0)
    assert drop["baseline"] == pytest.approx(20.0)
    assert drop["recent_days"] == 7
    assert drop["latest_date"] == (_SERIES_START + timedelta(days=34)).isoformat()


def test_flow_drop_ignores_steady_traffic():
    rows = _daily_series("chokepoint1", "n_container", [20, 21, 19, 20] * 9)
    drop = portwatch.detect_flow_drop(rows, "n_container")

    assert drop is not None
    assert abs(drop["change"]) < portwatch.DROP_THRESHOLD


def test_flow_drop_needs_enough_history():
    rows = _daily_series("chokepoint1", "n_container", [20] * 5)
    assert portwatch.detect_flow_drop(rows, "n_container") is None


def test_flow_drop_ignores_negligible_baseline():
    """Hormuz carries almost no container traffic; a 1 -> 0 swing is not a signal."""
    rows = _daily_series("chokepoint6", "n_container", [0] * 28 + [0] * 7)
    assert portwatch.detect_flow_drop(rows, "n_container") is None


def test_chokepoint_event_carries_exposed_countries():
    rows = _daily_series("chokepoint1", "n_container", [20] * 28 + [6] * 7)
    events = portwatch.build_chokepoint_events(rows)

    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "geopolitical"
    assert event["severity"] == 5  # 70% fall
    assert "IN" in event["affected_countries"]
    assert "70%" in event["title"]


def test_chokepoint_events_skip_healthy_lanes():
    rows = _daily_series("chokepoint5", "n_container", [50] * 35)
    assert portwatch.build_chokepoint_events(rows) == []


def test_port_event_maps_iso3_to_catalog_country():
    rows = [
        {**r, "portname": "Shanghai", "country": "China", "ISO3": "CHN"}
        for r in _daily_series("port1188", "portcalls_container", [30] * 28 + [15] * 7)
    ]
    events = portwatch.build_port_events(rows)

    assert len(events) == 1
    assert events[0]["affected_countries"] == ["CN"]
    assert events[0]["event_type"] == "supply"
    assert events[0]["severity"] == 5


# -- PortWatch: disruptions database ------------------------------------------

def test_disruption_record_resolves_countries_through_ports():
    records = [
        {
            "eventid": 1000552,
            "eventtype": "TC",
            "htmlname": "Tropical Cyclone IDAI-19",
            "htmldescription": "Red Tropical Cyclone IDAI-19.",
            "alertlevel": "RED",
            "country": "Mozambique",
            "severitytext": "Hurricane > 74 mph",
            "affectedports": "port137; port784",
            "n_affectedports": 2,
        }
    ]
    events = portwatch.build_disruption_events(records, {"port137": "VN", "port784": "TH"})

    assert len(events) == 1
    assert events[0]["affected_countries"] == ["TH", "VN"]
    assert events[0]["event_type"] == "weather"
    assert events[0]["severity"] == 5


def test_disruption_record_dropped_when_no_port_is_in_the_catalog():
    records = [{"eventtype": "FL", "alertlevel": "ORANGE", "affectedports": "port999"}]
    assert portwatch.build_disruption_events(records, {"port137": "VN"}) == []


def test_split_ports_handles_both_separators():
    assert portwatch.split_ports("port1; port2, port3") == ["port1", "port2", "port3"]
    assert portwatch.split_ports(None) == []


# -- NOAA ----------------------------------------------------------------------

def test_nws_alert_severity_ranks_by_event_name_not_cap_field():
    """A severe thunderstorm and a hurricane are both CAP 'Severe'; ports care about one."""
    assert noaa.score_alert_severity("Hurricane Warning", "Severe") == 5
    assert noaa.score_alert_severity("Tropical Storm Warning", "Severe") == 4
    assert noaa.score_alert_severity("Severe Thunderstorm Warning", "Severe") == 2


def test_nws_features_become_us_weather_events():
    features = [
        {
            "properties": {
                "@id": "https://api.weather.gov/alerts/urn:oid:1",
                "event": "Hurricane Warning",
                "severity": "Extreme",
                "urgency": "Immediate",
                "areaDesc": "Los Angeles County, CA",
                "headline": "Hurricane Warning issued for the LA basin",
                "effective": "2026-08-21T17:15:00-05:00",
                "expires": "2026-08-22T17:45:00-05:00",
            }
        },
        {"properties": {"event": ""}},
    ]
    events = noaa.build_alert_events(features)

    assert len(events) == 1
    assert events[0]["affected_countries"] == ["US"]
    assert events[0]["event_type"] == "weather"
    assert events[0]["severity"] == 5


def test_routine_convective_warnings_are_dropped():
    """NWS runs dozens of these at once; unfiltered they bury every real signal."""
    features = [
        {"properties": {"event": "Severe Thunderstorm Warning", "severity": "Severe",
                        "areaDesc": f"County {i}, LA"}}
        for i in range(20)
    ] + [{"properties": {"event": "Storm Surge Warning", "severity": "Severe",
                         "areaDesc": "Harris, TX"}}]

    events = noaa.build_alert_events(features)

    assert len(events) == 1
    assert events[0]["severity"] == 5
    assert "Storm Surge" in events[0]["title"]


def test_nhc_storm_severity_follows_wind_speed():
    storms = [
        {"id": "cp012026", "name": "Lala", "classification": "HU", "intensity": "80",
         "pressure": "974", "latitude": "28.6N", "longitude": "170.4W"},
        {"id": "al032026", "name": "Kai", "classification": "TD", "intensity": "25",
         "pressure": "1006", "latitude": "15.0N", "longitude": "40.0W"},
    ]
    events = noaa.build_storm_events(storms)

    assert [e["severity"] for e in events] == [4, 2]
    assert events[0]["affected_countries"] == ["US"]
    assert events[1]["affected_countries"] == ["US", "MX"]
    assert "Hurricane Lala" in events[0]["title"]


# -- Comtrade ------------------------------------------------------------------

def test_reference_periods_are_the_two_last_complete_years():
    from datetime import UTC, datetime

    assert comtrade.reference_periods(datetime(2026, 8, 21, tzinfo=UTC)) == ["2024", "2025"]


def test_yoy_drop_needs_two_distinct_periods():
    """The single-period query this replaced could never produce an anomaly."""
    one_year = [
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "6104",
         "period": "2025", "primaryValue": 4_000_000},
    ]
    assert comtrade.detect_trade_anomalies(one_year) == []


def test_yoy_drop_flags_collapsed_lane():
    flows = [
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "6104",
         "period": "2024", "primaryValue": 10_000_000},
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "6104",
         "period": "2025", "primaryValue": 4_000_000},
    ]
    anomalies = comtrade.detect_trade_anomalies(flows)

    assert len(anomalies) == 1
    assert anomalies[0]["event_type"] == "tariff"  # 60% fall
    assert anomalies[0]["affected_countries"] == ["US", "CN"]
    assert anomalies[0]["affected_hs_codes"] == ["6104"]


def test_yoy_drop_ignores_small_lanes_and_mild_moves():
    flows = [
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "6104",
         "period": "2024", "primaryValue": 500_000},
        {"reporterCode": 842, "partnerCode": 156, "cmdCode": "6104",
         "period": "2025", "primaryValue": 100_000},
        {"reporterCode": 842, "partnerCode": 704, "cmdCode": "8471",
         "period": "2024", "primaryValue": 10_000_000},
        {"reporterCode": 842, "partnerCode": 704, "cmdCode": "8471",
         "period": "2025", "primaryValue": 9_500_000},
    ]
    assert comtrade.detect_trade_anomalies(flows) == []


# -- Sink ----------------------------------------------------------------------

def test_normalise_maps_source_shape_onto_catalog_shape():
    event = sink.normalise(
        {
            "title": "Chokepoint transits down 61%: Suez Canal",
            "content": "Container transits collapsed.",
            "url": "https://portwatch.imf.org/",
            "event_type": "geopolitical",
            "severity": 5,
            "affected_countries": ["eg", "in"],
        }
    )

    assert event["title"].startswith("Chokepoint transits")
    assert event["description"] == "Container transits collapsed."
    assert event["source_url"] == "https://portwatch.imf.org/"
    assert event["affected_countries"] == ["EG", "IN"]
    assert event["valid_from"] and event["created_at"]


def test_normalise_rejects_untitled_and_clamps_out_of_range_fields():
    assert sink.normalise({"content": "no title"}) is None

    event = sink.normalise({"title": "x", "severity": 99, "event_type": "nonsense"})
    assert event["severity"] == 5
    assert event["event_type"] == "news"


def test_normalise_id_is_stable_for_the_same_title():
    a = sink.normalise({"title": "Typhoon near Haiphong"})
    b = sink.normalise({"title": "Typhoon near Haiphong"})
    assert a["id"] == b["id"]


@pytest.fixture
def memory_catalog(monkeypatch):
    catalog = Catalog.in_memory()

    async def _get_catalog(refresh=False):
        return catalog

    monkeypatch.setattr("orchestrator.ingestion.sink.get_catalog", _get_catalog)
    return catalog


async def test_publish_lands_events_in_the_in_memory_catalog(memory_catalog):
    before = len(memory_catalog.events)
    result = await sink.publish(
        [
            {"title": "Port throughput down 40%: Cat Lai", "content": "x",
             "event_type": "supply", "severity": 4, "affected_countries": ["VN"]},
            {"title": "Hurricane Warning: Los Angeles", "content": "y",
             "event_type": "weather", "severity": 5, "affected_countries": ["US"]},
        ]
    )

    assert result["published"] == 2
    assert len(memory_catalog.events) == before + 2
    assert memory_catalog.events[0]["title"] == "Port throughput down 40%: Cat Lai"


async def test_publish_is_idempotent_across_polls(memory_catalog):
    batch = [{"title": "Typhoon near Haiphong", "content": "x", "affected_countries": ["VN"]}]

    first = await sink.publish(batch)
    second = await sink.publish(batch)

    assert first["published"] == 1
    assert second["published"] == 0
    assert second["duplicates"] == 1


async def test_publish_deduplicates_within_one_batch(memory_catalog):
    result = await sink.publish(
        [{"title": "Same story"}, {"title": "Same story"}, {"title": "Other story"}]
    )
    assert result["published"] == 2


async def test_publish_caps_the_catalog(memory_catalog, monkeypatch):
    monkeypatch.setattr(
        "orchestrator.ingestion.sink.settings.ingestion_max_events", 20, raising=False
    )
    await sink.publish([{"title": f"Event {i}"} for i in range(50)])

    assert len(memory_catalog.events) == 20


async def test_published_events_reach_the_monitor_node(memory_catalog):
    """The point of the sink: a live event must be visible to the agent pipeline."""
    from orchestrator.pipeline.nodes import monitor

    await sink.publish(
        [
            {"title": "Chokepoint transits down 61%: Suez Canal", "content": "x",
             "event_type": "geopolitical", "severity": 5, "affected_countries": ["BD"]}
        ]
    )

    state = {"manufacturer_profile": {"supplier_countries": ["BD"], "hs_codes": []}}
    await monitor(state, memory_catalog)

    titles = [e["title"] for e in state["active_events"]]
    assert "Chokepoint transits down 61%: Suez Canal" in titles


# -- Collector -----------------------------------------------------------------

def test_keyless_sources_are_available_without_any_env():
    for name in collector.DEFAULT_SOURCES:
        assert collector.SOURCES[name].available
        assert not collector.SOURCES[name].key_setting


def test_keyed_sources_report_their_missing_key():
    weather = collector.SOURCES["weather"]
    assert weather.key_setting == "openweathermap_api_key"
    assert weather.to_dict()["key_setting"] == "OPENWEATHERMAP_API_KEY"


async def test_collect_skips_a_source_whose_key_is_absent():
    collector.reset()
    result = await collector.collect("news")

    assert result["status"] == "skipped"
    assert "NEWSAPI_KEY" in result["reason"]
    assert result["published"] == 0


async def test_collect_reports_a_failing_feed_without_raising(monkeypatch):
    async def _boom(name):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(collector, "_fetch", _boom)
    collector.reset()

    batch = await collector.collect_all(["portwatch", "noaa"])

    assert batch["errors"] == ["portwatch", "noaa"]
    assert batch["published"] == 0
    assert all(r["status"] == "error" for r in batch["sources"])


async def test_collect_all_publishes_what_a_source_returns(memory_catalog, monkeypatch):
    async def _fake(name):
        return [{"title": f"{name} event", "affected_countries": ["VN"], "severity": 3}]

    monkeypatch.setattr(collector, "_fetch", _fake)
    collector.reset()

    batch = await collector.collect_all(["portwatch"])

    assert batch["published"] == 1
    assert batch["errors"] == []
    assert collector.SOURCES["portwatch"].to_dict()["last_run"]["status"] == "ok"


# -- API surface ---------------------------------------------------------------

async def test_status_endpoint_lists_every_source(client):
    resp = await client.get("/api/v1/ingestion/status")
    assert resp.status_code == 200

    body = resp.json()
    assert body["enabled"] is False
    assert body["scheduler_running"] is False
    assert {s["name"] for s in body["sources"]} == set(collector.SOURCES)

    keyless = [s for s in body["sources"] if not s["requires_key"]]
    assert {s["name"] for s in keyless} == set(collector.DEFAULT_SOURCES)


async def test_run_endpoint_rejects_an_unknown_source(client):
    resp = await client.post("/api/v1/ingestion/run", json={"sources": ["bloomberg"]})
    assert resp.status_code == 400
    assert "bloomberg" in resp.json()["detail"]


async def test_run_endpoint_returns_per_source_outcomes(client, monkeypatch):
    async def _fake(name):
        return [{"title": f"{name} headline", "affected_countries": ["CN"]}]

    monkeypatch.setattr(collector, "_fetch", _fake)
    collector.reset()

    resp = await client.post("/api/v1/ingestion/run", json={"sources": ["noaa"]})
    assert resp.status_code == 200

    body = resp.json()
    assert body["published"] == 1
    assert body["sources"][0]["source"] == "noaa"
    assert body["sources"][0]["status"] == "ok"
