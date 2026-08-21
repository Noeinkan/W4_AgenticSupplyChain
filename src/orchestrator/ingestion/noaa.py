"""
NOAA ingestion: National Weather Service alerts and National Hurricane Center storms.

Both feeds are free, keyless and unauthenticated. NWS asks only for a descriptive
``User-Agent`` (``NOAA_USER_AGENT``); requests without one are throttled.

Coverage is honest about its limits. NWS covers US territory, which is what the
destination ports on the West and Gulf coasts need, and NHC covers the Atlantic
and eastern/central Pacific basins. Neither sees a Western Pacific typhoon - the
GDACS-backed PortWatch disruptions feed in :mod:`orchestrator.ingestion.portwatch`
is what covers Asian supplier hubs, and the two are meant to run together.
"""

from __future__ import annotations

import logging
import re

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
NHC_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

# States hosting the container ports that terminate the modelled lanes, plus the
# Gulf and East Coast alternates a reroute would use.
PORT_STATES = ["CA", "OR", "WA", "TX", "LA", "NY", "NJ", "GA", "SC", "FL", "VA", "MD"]

# Alerts scoring below this are routine weather, not a cargo event.
MIN_ALERT_SEVERITY = 3

# NWS event names that actually stop cargo moving, in descending severity.
_ALERT_SEVERITY: dict[int, list[str]] = {
    5: ["hurricane warning", "tsunami warning", "extreme wind warning", "storm surge warning"],
    4: [
        "hurricane watch", "tropical storm warning", "blizzard warning",
        "storm surge watch", "ice storm warning", "flash flood emergency",
    ],
    3: [
        "tropical storm watch", "high wind warning", "winter storm warning",
        "flood warning", "gale warning", "storm warning", "dense fog advisory",
    ],
}

_NHC_CLASSIFICATION: dict[str, str] = {
    "HU": "Hurricane", "MH": "Major Hurricane", "TS": "Tropical Storm",
    "TD": "Tropical Depression", "STS": "Severe Tropical Storm",
    "STD": "Subtropical Depression", "SS": "Subtropical Storm", "PTC": "Potential Tropical Cyclone",
}

# NHC storm ids are prefixed by basin: al = Atlantic, ep/cp = eastern/central Pacific.
_BASIN_COUNTRIES: dict[str, list[str]] = {
    "al": ["US", "MX"],
    "ep": ["US", "MX"],
    "cp": ["US"],
}


def _user_agent() -> str:
    return settings.noaa_user_agent


def score_alert_severity(event: str, nws_severity: str = "") -> int:
    """
    Map an NWS alert onto the 1-5 supply-chain severity scale.

    The name of the alert carries more signal than the CAP severity field: a
    "Severe Thunderstorm Warning" is routine for a port, a "Hurricane Warning" is
    not, and both are filed as CAP ``Severe``.

    Keywords match on word boundaries, so the marine "Storm Warning" product does
    not also swallow every "Thunderstorm Warning".
    """
    text = event.lower()
    for severity in sorted(_ALERT_SEVERITY, reverse=True):
        if any(re.search(rf"\b{re.escape(k)}\b", text) for k in _ALERT_SEVERITY[severity]):
            return severity
    return 3 if nws_severity.lower() == "extreme" else 2


def build_alert_events(features: list[dict], min_severity: int = MIN_ALERT_SEVERITY) -> list[dict]:
    """
    Convert NWS GeoJSON alert features into event dicts.

    Alerts below ``min_severity`` are dropped rather than stored. NWS runs tens of
    routine convective warnings at any moment - a thunderstorm over Baton Rouge is
    not a supply-chain event, and letting them through buries the signal that is.
    """
    events: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}
        event_name = props.get("event") or ""
        if not event_name:
            continue

        severity = score_alert_severity(event_name, props.get("severity") or "")
        if severity < min_severity:
            continue

        areas = props.get("areaDesc") or "United States"
        events.append(
            {
                "title": f"NWS {event_name}: {areas[:120]}",
                "content": (
                    (props.get("headline") or props.get("description") or event_name)
                    + f" Effective {props.get('effective') or 'now'} until "
                    + f"{props.get('expires') or 'further notice'}. "
                    + "Source: NOAA National Weather Service."
                ),
                "url": props.get("@id") or NWS_ALERTS_URL,
                "event_type": "weather",
                "severity": severity,
                "affected_countries": ["US"],
                "raw_data": {
                    "event": event_name,
                    "nws_severity": props.get("severity"),
                    "urgency": props.get("urgency"),
                    "area": areas[:500],
                    "expires": props.get("expires"),
                },
            }
        )
    return events


def build_storm_events(storms: list[dict]) -> list[dict]:
    """Convert NHC active-storm records into event dicts."""
    events: list[dict] = []
    for storm in storms:
        name = storm.get("name") or "Unnamed system"
        classification = _NHC_CLASSIFICATION.get(
            (storm.get("classification") or "").upper(), "Tropical cyclone"
        )
        basin = (storm.get("id") or "")[:2].lower()

        try:
            intensity_kt = int(storm.get("intensity") or 0)
        except (TypeError, ValueError):
            intensity_kt = 0

        events.append(
            {
                "title": f"{classification} {name} active in the {_basin_name(basin)}",
                "content": (
                    f"{classification} {name} at {storm.get('latitude') or '?'} "
                    f"{storm.get('longitude') or '?'}, maximum sustained winds "
                    f"{intensity_kt} kt, minimum pressure {storm.get('pressure') or '?'} mb, "
                    f"moving {storm.get('movementDir') or '?'} degrees at "
                    f"{storm.get('movementSpeed') or '?'} kt. Port closures and vessel "
                    f"diversions are likely along the forecast track. "
                    f"Source: NOAA National Hurricane Center, advisory issued "
                    f"{storm.get('lastUpdate') or 'recently'}."
                ),
                "url": ((storm.get("publicAdvisory") or {}).get("url")) or "https://www.nhc.noaa.gov/",
                "event_type": "weather",
                "severity": _storm_severity(intensity_kt),
                "affected_countries": _BASIN_COUNTRIES.get(basin, ["US"]),
                "raw_data": {
                    "id": storm.get("id"),
                    "classification": storm.get("classification"),
                    "intensity_kt": intensity_kt,
                    "latitude": storm.get("latitudeNumeric"),
                    "longitude": storm.get("longitudeNumeric"),
                },
            }
        )
    return events


def _basin_name(basin: str) -> str:
    return {
        "al": "Atlantic",
        "ep": "eastern Pacific",
        "cp": "central Pacific",
    }.get(basin, "NHC area of responsibility")


def _storm_severity(intensity_kt: int) -> int:
    """Saffir-Simpson in knots, compressed onto the 1-5 supply-chain scale."""
    if intensity_kt >= 96:  # category 3+
        return 5
    if intensity_kt >= 64:  # hurricane
        return 4
    if intensity_kt >= 34:  # tropical storm
        return 3
    return 2


async def fetch_nws_alerts(states: list[str] | None = None) -> list[dict]:
    """Active severe/extreme NWS alerts for the port states."""
    area = ",".join(states or PORT_STATES)
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(
                NWS_ALERTS_URL,
                params={"status": "actual", "severity": "Severe,Extreme", "area": area},
                headers={"User-Agent": _user_agent(), "Accept": "application/geo+json"},
            )
            resp.raise_for_status()
            features = resp.json().get("features", [])
    except Exception:
        logger.exception("NWS alert fetch failed")
        return []

    events = build_alert_events(features)
    logger.info("NOAA NWS: %d active alerts -> %d events", len(features), len(events))
    return events


async def fetch_nhc_storms() -> list[dict]:
    """Active tropical cyclones tracked by the National Hurricane Center."""
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.get(NHC_STORMS_URL, headers={"User-Agent": _user_agent()})
            resp.raise_for_status()
            storms = resp.json().get("activeStorms") or []
    except Exception:
        logger.exception("NHC storm fetch failed")
        return []

    events = build_storm_events(storms)
    logger.info("NOAA NHC: %d active storms -> %d events", len(storms), len(events))
    return events


async def fetch_all_noaa_events() -> list[dict]:
    """
    Both NOAA feeds. Called by the APScheduler job and by
    ``POST /api/v1/ingestion/run``. Needs no API key.
    """
    import asyncio

    results = await asyncio.gather(
        fetch_nws_alerts(), fetch_nhc_storms(), return_exceptions=True
    )

    events: list[dict] = []
    for result in results:
        if isinstance(result, list):
            events.extend(result)
        else:
            logger.warning("NOAA feed failed: %s", result)

    logger.info("NOAA: %d events across 2 feeds", len(events))
    return events
