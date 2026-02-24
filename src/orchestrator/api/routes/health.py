from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.dependencies import get_db
from orchestrator.api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/", response_model=HealthResponse)
async def health_check(request: Request, db: AsyncSession = Depends(get_db)):
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    scheduler = getattr(request.app.state, "scheduler", None)

    return HealthResponse(
        status="ok",
        version="0.1.0",
        db_connected=db_ok,
        ingestion_scheduler=bool(scheduler and scheduler.running),
    )
