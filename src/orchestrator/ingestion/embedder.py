"""
LlamaIndex-powered embedding pipeline.
Ingests articles/events → chunks → OpenAI embeddings → pgvector.

Falls back to mock zero-vector embeddings when no OPENAI_API_KEY is set,
so the system works end-to-end in dev without API keys.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import settings
from orchestrator.db.models import Event

logger = logging.getLogger(__name__)


def _make_embedding(text: str) -> list[float] | None:
    """
    Return a 1536-dim embedding for text.
    Uses OpenAI ada-002 if key is set; returns None otherwise
    (events without embeddings are stored but skipped in vector search).
    """
    if not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(
            model="text-embedding-ada-002",
            input=text[:8000],  # ada-002 max tokens ~ 8191
        )
        return response.data[0].embedding
    except Exception:
        logger.exception("Embedding generation failed")
        return None


async def ingest_article(db: AsyncSession, article: dict) -> Event:
    """
    Embed a news/climate/trade article and save it as an Event.

    article dict keys:
        title, content, url, event_type, severity,
        affected_countries (optional), affected_hs_codes (optional), raw_data (optional)
    """
    text = f"{article.get('title', '')}\n\n{article.get('content', '')}"
    embedding = _make_embedding(text[:2000])  # truncate for embedding

    event = Event(
        id=str(uuid.uuid4()),
        event_type=article.get("event_type", "news"),
        severity=article.get("severity", 1),
        title=article.get("title", "")[:500],
        description=article.get("content", "")[:2000],
        source_url=article.get("url", ""),
        affected_countries=article.get("affected_countries"),
        affected_hs_codes=article.get("affected_hs_codes"),
        raw_data=article.get("raw_data"),
        embedding=embedding,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def ingest_batch(db: AsyncSession, articles: list[dict]) -> list[Event]:
    """Ingest a list of articles, returning saved Event objects."""
    events: list[Event] = []
    for article in articles:
        try:
            event = await ingest_article(db, article)
            events.append(event)
        except Exception:
            logger.exception("Failed to ingest article: %s", article.get("title", "?"))
    logger.info("Ingested %d events (batch of %d)", len(events), len(articles))
    return events


async def semantic_search(
    db: AsyncSession, query: str, top_k: int = 5
) -> list[dict]:
    """
    Embed the query and run pgvector cosine similarity search.
    Returns list of event dicts (id, event_type, severity, title, description, similarity).
    """
    from orchestrator.db.repositories.event_repo import semantic_search as db_search

    embedding = _make_embedding(query)
    if embedding is None:
        # Fallback: return most recent events when embeddings unavailable
        from orchestrator.db.repositories.event_repo import get_recent

        recent = await get_recent(db, hours=72)
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "description": e.description,
                "similarity": 0.5,
            }
            for e in recent[:top_k]
        ]
    return await db_search(db, embedding, top_k)
