"""
APScheduler jobs for automated data ingestion.
Attached to the FastAPI lifespan so jobs start/stop with the app.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from orchestrator.db.engine import AsyncSessionLocal

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """
    Configure and return the APScheduler instance (not started yet).
    Call scheduler.start() inside the FastAPI lifespan.

    Job schedule:
      - News + RSS:    every 15 minutes
      - Weather:       every 30 minutes
      - Comtrade:      daily at 02:00 UTC
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        _job_ingest_news,
        trigger=IntervalTrigger(minutes=15),
        id="news_ingestion",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        _job_ingest_weather,
        trigger=IntervalTrigger(minutes=30),
        id="weather_ingestion",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.add_job(
        _job_ingest_comtrade,
        trigger=CronTrigger(hour=2, minute=0),
        id="comtrade_ingestion",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    return scheduler


async def _job_ingest_news() -> None:
    from orchestrator.ingestion import embedder, news

    logger.info("Starting news ingestion job")
    async with AsyncSessionLocal() as db:
        articles = await news.fetch_all_articles()
        await embedder.ingest_batch(db, articles)
    logger.info("News ingestion job complete")


async def _job_ingest_weather() -> None:
    from orchestrator.ingestion import climate, embedder

    logger.info("Starting weather ingestion job")
    async with AsyncSessionLocal() as db:
        alerts = await climate.fetch_all_weather_alerts()
        await embedder.ingest_batch(db, alerts)
    logger.info("Weather ingestion job complete: %d alerts", len(alerts))


async def _job_ingest_comtrade() -> None:
    from orchestrator.ingestion import comtrade, embedder

    logger.info("Starting Comtrade ingestion job")
    async with AsyncSessionLocal() as db:
        anomalies = await comtrade.fetch_all_anomalies()
        await embedder.ingest_batch(db, anomalies)
    logger.info("Comtrade ingestion job complete: %d anomalies", len(anomalies))
