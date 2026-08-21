"""
The ingestion source registry.

One place that knows which live feeds exist, which of them need a key, and what
happened the last time each ran. Both entry points go through here: the
APScheduler jobs in :mod:`orchestrator.ingestion.scheduler` and the
``/api/v1/ingestion`` routes.

Fetchers are imported inside :func:`collect`, never at module scope, so this
module stays importable when ``feedparser`` or ``apscheduler`` are absent - which
is the default, since neither is in ``requirements.txt``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from orchestrator.config import settings
from orchestrator.ingestion import sink

logger = logging.getLogger(__name__)


class Source:
    """One live feed: how to call it, what it needs, and how often it should run."""

    def __init__(self, name: str, description: str, interval: str, key_setting: str = ""):
        self.name = name
        self.description = description
        self.interval = interval
        self.key_setting = key_setting

    @property
    def key_present(self) -> bool:
        return bool(getattr(settings, self.key_setting, "")) if self.key_setting else True

    @property
    def available(self) -> bool:
        """Keyless sources are always available; keyed ones need their key set."""
        return self.key_present

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "interval": self.interval,
            "requires_key": bool(self.key_setting),
            "key_setting": self.key_setting.upper() or None,
            "available": self.available,
            "last_run": _LAST_RUN.get(self.name),
        }


SOURCES: dict[str, Source] = {
    "portwatch": Source(
        "portwatch",
        "IMF PortWatch chokepoint transits, port throughput and disruption records",
        "daily 03:00 UTC",
    ),
    "noaa": Source(
        "noaa",
        "NOAA National Weather Service alerts and National Hurricane Center storms",
        "every 30 minutes",
    ),
    "comtrade": Source(
        "comtrade",
        "UN Comtrade bilateral trade flows, year-on-year collapse detection",
        "daily 02:00 UTC",
    ),
    "news": Source(
        "news",
        "NewsAPI queries plus free RSS business feeds",
        "every 15 minutes",
        key_setting="newsapi_key",
    ),
    "weather": Source(
        "weather",
        "OpenWeatherMap alerts at the supplier hub coordinates",
        "every 30 minutes",
        key_setting="openweathermap_api_key",
    ),
}

# Keyless sources, which is what makes live ingestion work on a clean clone.
DEFAULT_SOURCES = ["portwatch", "noaa", "comtrade"]

_LAST_RUN: dict[str, dict] = {}


async def _fetch(name: str) -> list[dict]:
    if name == "portwatch":
        from orchestrator.data.catalog import get_catalog
        from orchestrator.ingestion import portwatch

        catalog = await get_catalog()
        return await portwatch.fetch_all_portwatch_events(catalog.countries())

    if name == "noaa":
        from orchestrator.ingestion import noaa

        return await noaa.fetch_all_noaa_events()

    if name == "comtrade":
        from orchestrator.ingestion import comtrade

        return await comtrade.fetch_all_anomalies()

    if name == "news":
        from orchestrator.ingestion import news

        return await news.fetch_all_articles()

    if name == "weather":
        from orchestrator.ingestion import climate

        return await climate.fetch_all_weather_alerts()

    raise KeyError(name)


async def collect(name: str) -> dict:
    """
    Run one source and publish whatever it returns.

    Never raises: a feed that is down, rate-limited or missing an optional
    dependency records the failure and leaves the catalog untouched.
    """
    source = SOURCES.get(name)
    if source is None:
        return {"source": name, "status": "unknown", "error": f"no such source: {name}"}

    if not source.available:
        result = {
            "source": name,
            "status": "skipped",
            "reason": f"{source.key_setting.upper()} not set",
            "published": 0,
            "ran_at": datetime.now(UTC).isoformat(),
        }
        _LAST_RUN[name] = result
        return result

    started = datetime.now(UTC)
    try:
        raw = await _fetch(name)
        published = await sink.publish(raw)
        result = {
            "source": name,
            "status": "ok",
            "ran_at": started.isoformat(),
            "duration_ms": round((datetime.now(UTC) - started).total_seconds() * 1000, 1),
            **published,
        }
    except Exception as exc:
        logger.exception("Ingestion source failed: %s", name)
        result = {
            "source": name,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "published": 0,
            "ran_at": started.isoformat(),
        }

    _LAST_RUN[name] = result
    return result


async def collect_all(names: list[str] | None = None) -> dict:
    """
    Run several sources concurrently and summarise the batch.

    Defaults to the keyless sources, so ``POST /api/v1/ingestion/run`` does
    something useful on a clone with no ``.env`` at all.
    """
    import asyncio

    selected = [n for n in (names or DEFAULT_SOURCES) if n in SOURCES]
    if not selected:
        return {"sources": [], "published": 0, "errors": []}

    results = await asyncio.gather(*[collect(n) for n in selected])
    return {
        "sources": results,
        "published": sum(int(r.get("published") or 0) for r in results),
        "errors": [r["source"] for r in results if r.get("status") == "error"],
    }


def status() -> dict:
    """Configuration and last-run state for every registered source."""
    return {
        "enabled": settings.enable_ingestion,
        "scheduler_running": _scheduler_running(),
        "max_events": settings.ingestion_max_events,
        "default_sources": DEFAULT_SOURCES,
        "sources": [s.to_dict() for s in SOURCES.values()],
    }


def _scheduler_running() -> bool:
    from orchestrator.ingestion import scheduler_state

    return scheduler_state.is_running()


def reset() -> None:
    _LAST_RUN.clear()
