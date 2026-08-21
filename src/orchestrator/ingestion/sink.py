"""
Where ingested events land.

Before this module the ingestion jobs wrote only to Postgres, so with the default
``DATA_BACKEND=memory`` a live feed had nowhere to go and the monitor agent never
saw it. Everything now flows through :func:`publish`, which normalises raw source
dicts into the catalog's event shape and pushes them into the same
``catalog.events`` list the monitor node reads. Persisting to Postgres is an
extra, not the path.

Event IDs are the same deterministic UUIDv5 the rest of the catalog uses, derived
from the title, so re-polling a feed that still carries yesterday's storm updates
the feed rather than duplicating it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from orchestrator.config import settings
from orchestrator.data.catalog import get_catalog, stable_id

logger = logging.getLogger(__name__)

_VALID_EVENT_TYPES = {"tariff", "weather", "strike", "geopolitical", "supply", "news"}


def normalise(raw: dict) -> dict | None:
    """
    Turn a source dict into a catalog event, or ``None`` if it carries no title.

    Sources emit ``title``/``content``/``url``; the catalog stores
    ``title``/``description``/``source_url`` alongside validity timestamps.
    """
    title = (raw.get("title") or "").strip()
    if not title:
        return None

    now = datetime.now(UTC).isoformat()
    event_type = raw.get("event_type") or "news"
    if event_type not in _VALID_EVENT_TYPES:
        event_type = "news"

    try:
        severity = max(1, min(5, int(raw.get("severity") or 1)))
    except (TypeError, ValueError):
        severity = 1

    countries = [
        str(c).upper()[:2]
        for c in (raw.get("affected_countries") or [])
        if c and str(c).strip()
    ]

    return {
        "id": stable_id("event", title),
        "event_type": event_type,
        "severity": severity,
        "affected_countries": countries,
        "affected_hs_codes": list(raw.get("affected_hs_codes") or []),
        "title": title[:500],
        "description": (raw.get("content") or raw.get("description") or "")[:2000],
        "source_url": raw.get("url") or None,
        "source": raw.get("source") or None,
        "valid_from": raw.get("published_at") or now,
        "valid_to": None,
        "created_at": now,
    }


async def publish(raw_events: list[dict]) -> dict:
    """
    Normalise, deduplicate and store a batch of source events.

    Returns ``{"received", "published", "duplicates", "total"}``. Newest events go
    to the front, and the list is capped at ``INGESTION_MAX_EVENTS`` so a feed
    that misbehaves cannot grow the catalog without bound.
    """
    catalog = await get_catalog()

    normalised: list[dict] = []
    seen_in_batch: set[str] = set()
    for raw in raw_events:
        event = normalise(raw)
        if event and event["id"] not in seen_in_batch:
            seen_in_batch.add(event["id"])
            normalised.append(event)

    known = {e["id"] for e in catalog.events}
    fresh = [e for e in normalised if e["id"] not in known]

    if fresh:
        catalog.events = (fresh + catalog.events)[: settings.ingestion_max_events]
        await _persist(fresh)

    result = {
        "received": len(raw_events),
        "published": len(fresh),
        "duplicates": len(normalised) - len(fresh),
        "total": len(catalog.events),
    }
    logger.info(
        "Ingestion sink: %d received, %d new, %d already known (catalog holds %d)",
        result["received"], result["published"], result["duplicates"], result["total"],
    )
    return result


async def _persist(events: list[dict]) -> None:
    """
    Mirror new events into Postgres when the DB backend is active.

    Optional by design: a failure here is logged and dropped, because the catalog
    already holds the events and the pipeline reads from the catalog.
    """
    if settings.data_backend != "db":
        return

    try:
        from orchestrator.db.engine import AsyncSessionLocal
        from orchestrator.ingestion import embedder

        async with AsyncSessionLocal() as db:
            await embedder.ingest_batch(
                db,
                [
                    {
                        "title": e["title"],
                        "content": e["description"],
                        "url": e["source_url"] or "",
                        "event_type": e["event_type"],
                        "severity": e["severity"],
                        "affected_countries": e["affected_countries"],
                        "affected_hs_codes": e["affected_hs_codes"],
                    }
                    for e in events
                ],
            )
    except Exception as exc:
        logger.warning("Event persistence skipped (%s)", exc)
