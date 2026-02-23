from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Route


async def get_for_supplier(db: AsyncSession, supplier_id: str) -> list[Route]:
    result = await db.execute(
        select(Route).where(Route.origin_supplier_id == supplier_id, Route.active == True)  # noqa: E712
    )
    return list(result.scalars().all())


async def get_all_active(db: AsyncSession) -> list[Route]:
    result = await db.execute(select(Route).where(Route.active == True))  # noqa: E712
    return list(result.scalars().all())
