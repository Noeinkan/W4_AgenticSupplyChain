"""
Shared fixtures.

Every test runs against the in-memory catalog with no LLM provider, so the suite
needs no database, no API key and no network access.
"""

import os

import pytest

os.environ.setdefault("DATA_BACKEND", "memory")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("ENABLE_INGESTION", "false")


@pytest.fixture
async def client():
    """ASGI test client bound directly to the FastAPI app (no live server)."""
    from httpx import ASGITransport, AsyncClient

    from orchestrator.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_run_store():
    """Each test gets a clean run registry, so audit assertions are not order-dependent."""
    import orchestrator.pipeline.store as store_module

    store_module._store = None
    yield
    store_module._store = None
