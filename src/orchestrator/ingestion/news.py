"""
News ingestion from NewsAPI.org (free tier: 100 req/day) and free RSS feeds.
Articles are classified, severity-scored, and passed to the embedder.
"""

import logging
from datetime import UTC, datetime

import httpx

from orchestrator.config import settings
from orchestrator.data.commodities import tag_text

logger = logging.getLogger(__name__)

SUPPLY_CHAIN_QUERIES = [
    "supply chain disruption",
    "port strike logistics",
    "semiconductor shortage",
    "tariff trade war",
    "shipping delay freight",
    "factory closure manufacturing",
    "geopolitical trade embargo",
    "climate flood factory",
    "diesel shortage refinery",
    "rare earth export controls",
    "fertilizer urea potash supply",
    "oil tanker Hormuz",
]

# Free RSS feeds — no API key required
RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
]

_EVENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "tariff": ["tariff", "trade war", "sanction", "embargo", "customs duty", "export ban",
               "export control", "export licen"],
    "weather": ["flood", "typhoon", "hurricane", "cyclone", "drought", "wildfire", "earthquake"],
    "strike": ["strike", "labor action", "walkout", "port workers", "union"],
    "geopolitical": ["war", "conflict", "invasion", "blockade", "geopoliti"],
    "supply": ["shortage", "chip shortage", "semiconductor", "raw material", "capacity"],
}

_SEVERITY_KEYWORDS: dict[int, list[str]] = {
    5: ["shutdown", "blockade", "catastrophic", "major port closed", "invasion"],
    4: ["significant", "major strike", "hurricane", "typhoon", "large-scale"],
    3: ["disruption", "delay", "shortage", "escalation"],
    2: ["concern", "risk", "potential", "warning", "alert"],
}


def classify_event_type(text: str) -> str:
    lower = text.lower()
    for event_type, keywords in _EVENT_TYPE_KEYWORDS.items():
        if any(k in lower for k in keywords):
            return event_type
    return "news"


def estimate_severity(text: str) -> int:
    lower = text.lower()
    for severity in sorted(_SEVERITY_KEYWORDS.keys(), reverse=True):
        if any(k in lower for k in _SEVERITY_KEYWORDS[severity]):
            return severity
    return 1


QUERIES_PER_POLL = 4


def queries_for_window(now: datetime | None = None) -> list[str]:
    """Four queries per poll, rotating every 15 minutes so every query gets its turn."""
    now = now or datetime.now(UTC)
    window = now.hour * 4 + now.minute // 15
    start = (window * QUERIES_PER_POLL) % len(SUPPLY_CHAIN_QUERIES)
    rotated = SUPPLY_CHAIN_QUERIES[start:] + SUPPLY_CHAIN_QUERIES[:start]
    return rotated[:QUERIES_PER_POLL]


async def fetch_newsapi_articles(query: str) -> list[dict]:
    """
    NewsAPI.org everything endpoint.
    Free tier: 100 requests/day, no commercial use.
    """
    if not settings.newsapi_key:
        logger.warning("NEWSAPI_KEY not set — skipping NewsAPI fetch")
        return []

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                    "apiKey": settings.newsapi_key,
                },
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "content": (a.get("description") or "") + " " + (a.get("content") or ""),
                    "url": a.get("url", ""),
                    "published_at": a.get("publishedAt", ""),
                    "source": a.get("source", {}).get("name", "NewsAPI"),
                }
                for a in articles
                if a.get("title")
            ]
    except Exception:
        logger.exception("NewsAPI fetch failed for query: %s", query)
        return []


def fetch_rss_feeds() -> list[dict]:
    """Parse free RSS feeds synchronously (feedparser handles HTTP)."""
    import feedparser

    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                articles.append(
                    {
                        "title": entry.get("title", ""),
                        "content": entry.get("summary", ""),
                        "url": entry.get("link", ""),
                        "published_at": entry.get("published", str(datetime.now(UTC))),
                        "source": feed.feed.get("title", url),
                    }
                )
        except Exception:
            logger.exception("RSS feed parse failed: %s", url)
    return articles


async def fetch_all_articles() -> list[dict]:
    """
    Pull from all news sources and enrich with event_type + severity.
    Called by the APScheduler job every 15 minutes.
    """
    articles: list[dict] = []

    # Parallel NewsAPI queries
    import asyncio
    results = await asyncio.gather(
        *[fetch_newsapi_articles(q) for q in queries_for_window()],  # stay within rate limit
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, list):
            articles.extend(r)

    # RSS feeds (sync, fast)
    articles.extend(fetch_rss_feeds())

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            text = a["title"] + " " + a.get("content", "")
            a["event_type"] = classify_event_type(text)
            a["severity"] = estimate_severity(text)
            a["affected_hs_codes"] = tag_text(text)
            unique.append(a)

    logger.info("Fetched %d unique articles from all news sources", len(unique))
    return unique
