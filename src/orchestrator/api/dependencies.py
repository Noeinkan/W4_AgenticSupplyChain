"""FastAPI dependency injectors."""

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.engine import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def get_graph(request: Request):
    """Inject the compiled LangGraph from app state."""
    return request.app.state.graph


def get_scheduler(request: Request):
    """Inject the APScheduler instance from app state."""
    return request.app.state.scheduler
