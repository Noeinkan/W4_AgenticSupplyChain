"""
Pytest configuration and shared fixtures.
"""

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client():
    """HTTP test client for the FastAPI app (requires httpx + fastapi installed)."""
    try:
        from httpx import ASGITransport, AsyncClient
        from orchestrator.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    except ImportError:
        pytest.skip("httpx or fastapi not installed")
