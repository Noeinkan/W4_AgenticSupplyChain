from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Event


async def get_recent(
    db: AsyncSession, hours: int = 24, severity_min: int = 1
) -> list[Event]:
    """Fetch events from the last N hours above a minimum severity."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    result = await db.execute(
        select(Event)
        .where(Event.created_at >= cutoff, Event.severity >= severity_min)
        .order_by(Event.severity.desc(), Event.created_at.desc())
        .limit(100)
    )
    return list(result.scalars().all())


async def semantic_search(
    db: AsyncSession, embedding: list[float], top_k: int = 5
) -> list[dict]:
    """
    Raw SQL pgvector cosine similarity search.
    Returns dicts (not ORM objects) for speed — avoids lazy-load issues.
    """
    sql = text("""
        SELECT id, event_type, severity, title, description,
               affected_countries, source_url,
               1 - (embedding <=> CAST(:emb AS vector)) AS similarity
        FROM events
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:emb AS vector)
        LIMIT :top_k
    """)
    result = await db.execute(
        sql,
        {"emb": str(embedding), "top_k": top_k},
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def save(db: AsyncSession, event: Event) -> Event:
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event
