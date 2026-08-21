"""
APScheduler jobs for automated data ingestion.
Attached to the FastAPI lifespan so jobs start/stop with the app.

Every job is a one-line call into :mod:`orchestrator.ingestion.collector`, which
fetches, normalises and publishes into the catalog. Keeping the schedule and the
work apart is what lets ``POST /api/v1/ingestion/run`` trigger exactly the same
path without APScheduler installed.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from orchestrator.ingestion import collector, scheduler_state

logger = logging.getLogger(__name__)

# (source, trigger) pairs. The keyless sources run whether or not a .env exists;
# the keyed ones are scheduled too and skip themselves when the key is absent.
JOB_SCHEDULE = [
    ("noaa", IntervalTrigger(minutes=30)),
    ("news", IntervalTrigger(minutes=15)),
    ("weather", IntervalTrigger(minutes=30)),
    ("comtrade", CronTrigger(hour=2, minute=0)),
    ("portwatch", CronTrigger(hour=3, minute=0)),
]


def create_scheduler() -> AsyncIOScheduler:
    """
    Configure and return the APScheduler instance (not started yet).
    Call scheduler.start() inside the FastAPI lifespan.

    Job schedule:
      - NOAA (NWS + NHC):  every 30 minutes, no key
      - News + RSS:        every 15 minutes, needs NEWSAPI_KEY for the API half
      - Weather (OWM):     every 30 minutes, needs OPENWEATHERMAP_API_KEY
      - Comtrade:          daily at 02:00 UTC, no key (public preview)
      - PortWatch:         daily at 03:00 UTC, no key
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    for source, trigger in JOB_SCHEDULE:
        scheduler.add_job(
            _run_source,
            trigger=trigger,
            id=f"{source}_ingestion",
            args=[source],
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    return scheduler


async def _run_source(source: str) -> None:
    logger.info("Starting %s ingestion job", source)
    result = await collector.collect(source)
    logger.info(
        "%s ingestion job %s: %d new events",
        source, result.get("status"), int(result.get("published") or 0),
    )


def start(scheduler: AsyncIOScheduler) -> list[str]:
    """Start the scheduler and record it as running for the status endpoint."""
    scheduler.start()
    job_ids = [j.id for j in scheduler.get_jobs()]
    scheduler_state.mark_started(job_ids)
    return job_ids


def shutdown(scheduler: AsyncIOScheduler) -> None:
    scheduler.shutdown(wait=False)
    scheduler_state.mark_stopped()
