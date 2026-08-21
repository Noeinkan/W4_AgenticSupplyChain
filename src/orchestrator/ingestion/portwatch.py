"""
IMF PortWatch ingestion.

PortWatch publishes daily AIS-derived port and chokepoint traffic through public
ArcGIS feature services. No API key, no registration, no rate limit worth
worrying about - which is why this is the ingestion source that works on a clean
clone.

Three signals are pulled:

  * **chokepoint transits** - daily vessel counts through Suez, Malacca, Panama,
    the Taiwan Strait and friends. A sustained collapse against the trailing
    baseline is the numeric version of "Red Sea transits down 61% year on year".
  * **port throughput** - daily container port calls for the ports serving the
    catalog's supplier countries, with the same drop detection.
  * **the disruptions database** - GDACS-backed cyclone/flood/earthquake records
    already joined to the ports they affect.

Every number here is measured, never modelled: the module converts the feeds into
event dicts and stops. Estimating impact is the simulator's job.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

ARCGIS_BASE = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"

CHOKEPOINTS_SERVICE = "Daily_Chokepoints_Data"
PORTS_DAILY_SERVICE = "Daily_Ports_Data"
PORTS_MASTER_SERVICE = "PortWatch_ports_database"
DISRUPTIONS_SERVICE = "portwatch_disruptions_database"

# Chokepoints whose transit volume actually moves a lane in this catalog, mapped
# to the supplier countries that route through them.
CHOKEPOINT_EXPOSURE: dict[str, list[str]] = {
    "chokepoint1": ["EG", "IN", "BD", "VN", "TH", "MY", "KH"],  # Suez Canal
    "chokepoint2": ["US"],  # Panama Canal
    "chokepoint3": ["TR"],  # Bosporus Strait
    "chokepoint4": ["EG", "IN", "BD"],  # Bab el-Mandeb Strait
    "chokepoint5": ["MY", "TH", "VN", "KH", "CN", "TW", "KR", "JP", "IN", "BD"],  # Malacca
    "chokepoint7": ["IN", "BD", "VN", "TH", "MY"],  # Cape of Good Hope
    "chokepoint8": ["MA", "TR"],  # Gibraltar Strait
    "chokepoint11": ["TW", "CN", "KR", "JP"],  # Taiwan Strait
    "chokepoint12": ["KR", "JP", "CN"],  # Korea Strait
    "chokepoint14": ["TW", "CN", "VN"],  # Luzon Strait
}

# PortWatch reports ISO3; the catalog keys everything on ISO2.
ISO3_TO_ISO2: dict[str, str] = {
    "BGD": "BD", "CHN": "CN", "DEU": "DE", "EGY": "EG", "ESP": "ES", "ETH": "ET",
    "FRA": "FR", "GBR": "GB", "HKG": "HK", "IDN": "ID", "IND": "IN", "ITA": "IT",
    "JPN": "JP", "KHM": "KH", "KOR": "KR", "LKA": "LK", "MAR": "MA", "MEX": "MX",
    "MYS": "MY", "NLD": "NL", "PAK": "PK", "PHL": "PH", "SGP": "SG", "THA": "TH",
    "TUR": "TR", "TWN": "TW", "USA": "US", "VNM": "VN", "ZAF": "ZA",
}
ISO2_TO_ISO3: dict[str, str] = {v: k for k, v in ISO3_TO_ISO2.items()}

# GDACS hazard codes carried by the disruptions database.
_HAZARD_EVENT_TYPE: dict[str, str] = {
    "TC": "weather", "FL": "weather", "DR": "weather", "WF": "weather",
    "VO": "weather", "EQ": "weather", "TS": "weather",
}
_HAZARD_LABEL: dict[str, str] = {
    "TC": "Tropical cyclone", "FL": "Flood", "DR": "Drought", "WF": "Wildfire",
    "VO": "Volcanic activity", "EQ": "Earthquake", "TS": "Tsunami",
}
_ALERT_SEVERITY: dict[str, int] = {"RED": 5, "ORANGE": 4, "GREEN": 2}

RECENT_WINDOW_DAYS = 7
BASELINE_WINDOW_DAYS = 28
DROP_THRESHOLD = 0.20
MAX_WATCHED_PORTS = 12


async def _query(
    service: str,
    *,
    where: str,
    out_fields: str,
    order_by: str | None = None,
    limit: int | None = None,
    timeout: float = 45.0,
) -> list[dict]:
    """
    Run one ArcGIS feature query and return the plain attribute dicts.

    ArcGIS answers a malformed query with HTTP 200 and an ``error`` body, so the
    status code alone does not separate success from failure.
    """
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    if order_by:
        params["orderByFields"] = order_by
    if limit:
        params["resultRecordCount"] = str(limit)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{ARCGIS_BASE}/{service}/FeatureServer/0/query", params=params
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        logger.exception("PortWatch query failed: %s", service)
        return []

    if isinstance(payload, dict) and payload.get("error"):
        logger.warning("PortWatch rejected query on %s: %s", service, payload["error"])
        return []

    return [f.get("attributes", {}) for f in payload.get("features", [])]


def detect_flow_drop(
    rows: list[dict],
    value_field: str,
    recent_days: int = RECENT_WINDOW_DAYS,
    baseline_days: int = BASELINE_WINDOW_DAYS,
) -> dict | None:
    """
    Compare the most recent days of a daily series against the window before it.

    Returns ``{"change", "recent", "baseline", "recent_days", "baseline_days",
    "latest_date"}`` when both windows carry data and the baseline is large enough
    for a ratio to mean anything, otherwise ``None``. ``change`` is signed: -0.61
    is a 61% fall.
    """
    series = sorted(
        (r for r in rows if r.get("date") and r.get(value_field) is not None),
        key=lambda r: str(r["date"]),
    )
    if len(series) < recent_days + max(7, recent_days):
        return None

    recent = [float(r[value_field]) for r in series[-recent_days:]]
    baseline = [
        float(r[value_field]) for r in series[-(recent_days + baseline_days):-recent_days]
    ]
    if not baseline:
        return None

    recent_mean = sum(recent) / len(recent)
    baseline_mean = sum(baseline) / len(baseline)
    if baseline_mean < 1.0:
        return None

    return {
        "change": (recent_mean - baseline_mean) / baseline_mean,
        "recent": recent_mean,
        "baseline": baseline_mean,
        "recent_days": len(recent),
        "baseline_days": len(baseline),
        "latest_date": str(series[-1]["date"]),
    }


def _drop_severity(change: float) -> int:
    magnitude = abs(change)
    if magnitude >= 0.50:
        return 5
    if magnitude >= 0.35:
        return 4
    return 3


def _iso_date(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _group_by_port(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        portid = row.get("portid")
        if portid:
            grouped.setdefault(portid, []).append(row)
    return grouped


def build_chokepoint_events(rows: list[dict]) -> list[dict]:
    """Group daily chokepoint transits by portid and flag sustained collapses."""
    events: list[dict] = []
    for portid, series in _group_by_port(rows).items():
        drop = detect_flow_drop(series, "n_container")
        if drop is None or drop["change"] > -DROP_THRESHOLD:
            continue

        name = series[-1].get("portname") or portid
        events.append(
            {
                "title": f"Chokepoint transits down {abs(drop['change']):.0%}: {name}",
                "content": (
                    f"Container transits through the {name} averaged "
                    f"{drop['recent']:.1f}/day over the last {drop['recent_days']} days "
                    f"against a {drop['baseline_days']}-day baseline of "
                    f"{drop['baseline']:.1f}/day, a {abs(drop['change']):.0%} fall. "
                    f"Lanes routed through this chokepoint face rerouting delay and a "
                    f"higher bunker cost per TEU. Source: IMF PortWatch daily AIS "
                    f"transits to {drop['latest_date']}."
                ),
                "url": "https://portwatch.imf.org/",
                "event_type": "geopolitical",
                "severity": _drop_severity(drop["change"]),
                "affected_countries": CHOKEPOINT_EXPOSURE.get(portid, []),
                "raw_data": {"portid": portid, "portname": name, **drop},
            }
        )
    return events


def build_port_events(rows: list[dict]) -> list[dict]:
    """Flag ports whose container calls have fallen well below their own baseline."""
    events: list[dict] = []
    for portid, series in _group_by_port(rows).items():
        drop = detect_flow_drop(series, "portcalls_container")
        if drop is None or drop["change"] > -DROP_THRESHOLD:
            continue

        latest = series[-1]
        name = latest.get("portname") or portid
        iso2 = ISO3_TO_ISO2.get(latest.get("ISO3") or "", "")
        events.append(
            {
                "title": f"Port throughput down {abs(drop['change']):.0%}: {name}",
                "content": (
                    f"Container port calls at {name} "
                    f"({latest.get('country') or 'unknown'}) averaged "
                    f"{drop['recent']:.1f}/day over the last {drop['recent_days']} days "
                    f"against a {drop['baseline_days']}-day baseline of "
                    f"{drop['baseline']:.1f}/day. A drop this size usually means berth "
                    f"congestion, closure or a labour action. Source: IMF PortWatch "
                    f"daily AIS port calls to {drop['latest_date']}."
                ),
                "url": "https://portwatch.imf.org/",
                "event_type": "supply",
                "severity": _drop_severity(drop["change"]),
                "affected_countries": [iso2] if iso2 else [],
                "raw_data": {"portid": portid, "portname": name, **drop},
            }
        )
    return events


def build_disruption_events(records: list[dict], port_countries: dict[str, str]) -> list[dict]:
    """
    Convert PortWatch disruption records into event dicts.

    ``port_countries`` maps portid to ISO2 so the affected-port list resolves to
    countries the catalog recognises. A record whose ports all fall outside the
    catalog is dropped rather than filed against no country, because the monitor
    node matches events to suppliers by country.
    """
    events: list[dict] = []
    for record in records:
        hazard = (record.get("eventtype") or "").upper()
        alert = (record.get("alertlevel") or "").upper()
        name = record.get("htmlname") or record.get("eventname") or "PortWatch disruption"

        countries = sorted(
            {
                port_countries[pid]
                for pid in split_ports(record.get("affectedports"))
                if pid in port_countries
            }
        )
        if not countries:
            continue

        port_count = record.get("n_affectedports") or len(countries)
        events.append(
            {
                "title": f"{_HAZARD_LABEL.get(hazard, 'Disruption')}: {name}",
                "content": " ".join(
                    part
                    for part in [
                        record.get("htmldescription") or name,
                        f"Affects {port_count} monitored port(s).",
                        record.get("severitytext") or "",
                        f"Source: IMF PortWatch disruptions database "
                        f"({alert or 'unrated'} alert).",
                    ]
                    if part
                ),
                "url": "https://portwatch.imf.org/pages/port-monitor",
                "event_type": _HAZARD_EVENT_TYPE.get(hazard, "supply"),
                "severity": _ALERT_SEVERITY.get(alert, 3),
                "affected_countries": countries,
                "raw_data": {
                    "eventid": record.get("eventid"),
                    "eventtype": hazard,
                    "alertlevel": alert,
                    "country": record.get("country"),
                },
            }
        )
    return events


def split_ports(value: str | None) -> list[str]:
    """``"port137; port784"`` -> ``["port137", "port784"]``."""
    if not value:
        return []
    return [p.strip() for p in str(value).replace(",", ";").split(";") if p.strip()]


def _sql_in(values: list[str]) -> str:
    return ",".join("'" + v.replace("'", "''") + "'" for v in values)


async def watched_ports(iso2_codes: list[str]) -> list[dict]:
    """
    The busiest container ports serving the given countries, from the PortWatch
    master list. Derived from the catalog rather than hard-coded, so adding a
    supplier country widens the watchlist on its own.
    """
    iso3 = sorted({ISO2_TO_ISO3[c] for c in iso2_codes if c in ISO2_TO_ISO3})
    if not iso3:
        return []

    return await _query(
        PORTS_MASTER_SERVICE,
        where=f"ISO3 IN ({_sql_in(iso3)}) AND vessel_count_container > 300",
        out_fields="portid,portname,country,ISO3,vessel_count_container",
        order_by="vessel_count_container DESC",
        limit=MAX_WATCHED_PORTS,
    )


async def fetch_chokepoint_events(lookback_days: int = 60) -> list[dict]:
    rows = await _query(
        CHOKEPOINTS_SERVICE,
        where=(
            f"portid IN ({_sql_in(list(CHOKEPOINT_EXPOSURE))}) "
            f"AND date >= DATE '{_iso_date(lookback_days)}'"
        ),
        out_fields="date,portid,portname,n_container,n_total",
        order_by="date ASC",
    )
    events = build_chokepoint_events(rows)
    logger.info("PortWatch chokepoints: %d rows -> %d events", len(rows), len(events))
    return events


async def fetch_port_events(iso2_codes: list[str], lookback_days: int = 60) -> list[dict]:
    ports = await watched_ports(iso2_codes)
    portids = [p["portid"] for p in ports if p.get("portid")]
    if not portids:
        return []

    rows = await _query(
        PORTS_DAILY_SERVICE,
        where=(
            f"portid IN ({_sql_in(portids)}) AND date >= DATE '{_iso_date(lookback_days)}'"
        ),
        out_fields="date,portid,portname,country,ISO3,portcalls_container,portcalls",
        order_by="date ASC",
    )
    events = build_port_events(rows)
    logger.info(
        "PortWatch ports: %d ports, %d rows -> %d events", len(portids), len(rows), len(events)
    )
    return events


async def _port_countries(portids: list[str]) -> dict[str, str]:
    """Resolve portid -> ISO2 in bulk, so disruption records land on real countries."""
    mapping: dict[str, str] = {}
    for start in range(0, len(portids), 200):
        rows = await _query(
            PORTS_MASTER_SERVICE,
            where=f"portid IN ({_sql_in(portids[start:start + 200])})",
            out_fields="portid,ISO3",
        )
        for row in rows:
            iso2 = ISO3_TO_ISO2.get(row.get("ISO3") or "")
            if iso2 and row.get("portid"):
                mapping[row["portid"]] = iso2
    return mapping


async def fetch_disruption_events(lookback_days: int = 45) -> list[dict]:
    # ``todate`` is a date field: it compares against a DATE literal, not the
    # epoch milliseconds the layer returns in its own responses.
    records = await _query(
        DISRUPTIONS_SERVICE,
        where=(
            f"todate >= DATE '{_iso_date(lookback_days)}' "
            f"AND alertlevel IN ('RED','ORANGE')"
        ),
        out_fields=(
            "eventid,eventtype,eventname,htmlname,htmldescription,alertlevel,"
            "country,fromdate,todate,severitytext,affectedports,n_affectedports"
        ),
        order_by="todate DESC",
        limit=50,
    )
    if not records:
        return []

    portids = sorted({pid for r in records for pid in split_ports(r.get("affectedports"))})
    events = build_disruption_events(records, await _port_countries(portids))
    logger.info("PortWatch disruptions: %d records -> %d events", len(records), len(events))
    return events


async def fetch_all_portwatch_events(iso2_codes: list[str] | None = None) -> list[dict]:
    """
    All three PortWatch signals for the given supplier countries.

    Called by the daily APScheduler job and by ``POST /api/v1/ingestion/run``.
    Needs no API key.
    """
    import asyncio

    countries = iso2_codes or sorted(ISO2_TO_ISO3)
    results = await asyncio.gather(
        fetch_chokepoint_events(),
        fetch_port_events(countries),
        fetch_disruption_events(),
        return_exceptions=True,
    )

    events: list[dict] = []
    for result in results:
        if isinstance(result, list):
            events.extend(result)
        else:
            logger.warning("PortWatch feed failed: %s", result)

    logger.info("PortWatch: %d events across 3 feeds", len(events))
    return events
