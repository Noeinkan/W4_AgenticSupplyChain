"""
Seed Postgres from the canonical catalog.

Only needed for DATA_BACKEND=db. The dashboard runs from the same data in memory
without this step, which is why `npm start` needs no database.

The supplier and route definitions live in orchestrator.data.catalog, so the
seeded database and the in-memory catalog cannot drift apart, and IDs match
between the two backends.

Run:
    PYTHONPATH=src python scripts/seed_data.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrator.data.catalog import Catalog  # noqa: E402


async def seed() -> None:
    from sqlalchemy import func, select

    from orchestrator.db.engine import AsyncSessionLocal, Base, engine
    from orchestrator.db.models import Route, Supplier

    catalog = Catalog.in_memory()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(func.count()).select_from(Supplier))
        if existing.scalar():
            print("Database already seeded - skipping.")
            return

        for supplier in catalog.suppliers:
            db.add(Supplier(**supplier))
            print(f"  supplier: {supplier['name']} ({supplier['country_code']})")

        for route in catalog.routes:
            db.add(Route(**route))

        await db.commit()

    print(f"\nSeeded {len(catalog.suppliers)} suppliers and {len(catalog.routes)} routes.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except ImportError as exc:
        print(f"Database dependencies missing: {exc}")
        print("Install them with:  pip install 'sqlalchemy[asyncio]' asyncpg pgvector alembic")
        sys.exit(1)
