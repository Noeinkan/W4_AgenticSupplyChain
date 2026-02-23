"""
Climate and weather disruption ingestion.
Uses OpenWeatherMap One Call API 3.0 (free tier: 1,000 calls/day).
Major supplier hub coordinates are polled every 30 minutes.
"""

import logging

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)

# Major manufacturing hub coordinates to monitor
SUPPLIER_HUB_COORDS = [
    {"name": "Dhaka, Bangladesh", "lat": 23.81, "lon": 90.41, "country": "BD"},
    {"name": "Ho Chi Minh City, Vietnam", "lat": 10.82, "lon": 106.63, "country": "VN"},
    {"name": "Shanghai, China", "lat": 31.23, "lon": 121.47, "country": "CN"},
    {"name": "Shenzhen, China", "lat": 22.54, "lon": 114.06, "country": "CN"},
    {"name": "Taipei, Taiwan", "lat": 25.04, "lon": 121.56, "country": "TW"},
    {"name": "Seoul, South Korea", "lat": 37.57, "lon": 126.98, "country": "KR"},
    {"name": "Istanbul, Turkey", "lat": 41.01, "lon": 28.95, "country": "TR"},
    {"name": "Mumbai, India", "lat": 19.08, "lon": 72.88, "country": "IN"},
    {"name": "Kuala Lumpur, Malaysia", "lat": 3.14, "lon": 101.69, "country": "MY"},
    {"name": "Bangkok, Thailand", "lat": 13.76, "lon": 100.50, "country": "TH"},
]


async def fetch_weather_alerts(lat: float, lon: float) -> list[dict]:
    """
    OpenWeatherMap One Call API 3.0.
    Returns list of active weather alerts with supply-chain severity score.
    """
    if not settings.openweathermap_api_key:
        logger.warning("OPENWEATHERMAP_API_KEY not set — skipping weather fetch")
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.openweathermap.org/data/3.0/onecall",
                params={
                    "lat": lat,
                    "lon": lon,
                    "exclude": "minutely,hourly,daily",
                    "appid": settings.openweathermap_api_key,
                    "units": "metric",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            alerts = data.get("alerts", [])
            return [
                {
                    "event": alert.get("event", "Weather Alert"),
                    "description": alert.get("description", "")[:500],
                    "severity": _score_weather_severity(alert),
                    "start": alert.get("start"),
                    "end": alert.get("end"),
                    "lat": lat,
                    "lon": lon,
                }
                for alert in alerts
            ]
    except Exception:
        logger.exception("Weather fetch failed for coords (%s, %s)", lat, lon)
        return []


def _score_weather_severity(alert: dict) -> int:
    """Map weather alert to 1–5 severity scale for supply chain impact."""
    text = (alert.get("event", "") + " " + alert.get("description", "")).lower()
    if any(k in text for k in ["hurricane", "typhoon", "cyclone", "major flood", "catastrophic"]):
        return 5
    if any(k in text for k in ["tropical storm", "blizzard", "severe flood", "wildfire"]):
        return 4
    if any(k in text for k in ["storm", "tornado", "freeze", "heat wave", "drought"]):
        return 3
    if any(k in text for k in ["rain", "wind", "fog", "ice"]):
        return 2
    return 1


async def fetch_all_weather_alerts() -> list[dict]:
    """
    Poll all supplier hub locations and collect active weather alerts.
    Returns enriched alert dicts ready for the embedder.
    """
    import asyncio

    hub_alerts = await asyncio.gather(
        *[fetch_weather_alerts(h["lat"], h["lon"]) for h in SUPPLIER_HUB_COORDS],
        return_exceptions=True,
    )

    enriched: list[dict] = []
    for hub, alerts in zip(SUPPLIER_HUB_COORDS, hub_alerts):
        if isinstance(alerts, Exception):
            continue
        for alert in alerts:
            enriched.append(
                {
                    "title": f"Weather Alert: {alert['event']} near {hub['name']}",
                    "content": alert["description"],
                    "url": "",
                    "event_type": "weather",
                    "severity": alert["severity"],
                    "affected_countries": [hub["country"]],
                    "raw_data": alert,
                }
            )

    logger.info("Fetched %d weather alerts across %d hubs", len(enriched), len(SUPPLIER_HUB_COORDS))
    return enriched
