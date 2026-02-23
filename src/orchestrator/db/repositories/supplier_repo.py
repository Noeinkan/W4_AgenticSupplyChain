from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.models import Supplier


async def get_all_active(db: AsyncSession) -> list[Supplier]:
    result = await db.execute(select(Supplier).where(Supplier.active == True))  # noqa: E712
    return list(result.scalars().all())


async def get_by_country(db: AsyncSession, country_code: str) -> list[Supplier]:
    result = await db.execute(
        select(Supplier).where(Supplier.country_code == country_code, Supplier.active == True)  # noqa: E712
    )
    return list(result.scalars().all())


async def get_alternatives(
    db: AsyncSession,
    exclude_country: str,
    hs_code: str | None = None,
    min_capacity: int = 0,
) -> list[Supplier]:
    """Find alternative suppliers avoiding a specific country."""
    query = select(Supplier).where(
        Supplier.country_code != exclude_country,
        Supplier.active == True,  # noqa: E712
    )
    if min_capacity > 0:
        query = query.where(Supplier.capacity_units >= min_capacity)
    if hs_code:
        query = query.where(Supplier.commodity_codes.any(hs_code))
    query = query.order_by(Supplier.esg_score.desc().nullslast())
    result = await db.execute(query)
    return list(result.scalars().all())


async def upsert(db: AsyncSession, supplier: Supplier) -> Supplier:
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier
