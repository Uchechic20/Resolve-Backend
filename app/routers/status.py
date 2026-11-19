from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timezone
from pydantic import BaseModel
from app.core.database import get_db
from app.models.user import User
from app.models.service_status import ServiceOutage
from app.dependencies import require_role

router = APIRouter(prefix="/status", tags=["Service Status"])


class OutageCreate(BaseModel):
    service_name: str
    description: str
    status: str = "investigating"


@router.get("/active")
async def get_active_outages(db: AsyncSession = Depends(get_db)):
    """Public endpoint: Check if any services are currently down."""
    stmt = select(ServiceOutage).where(ServiceOutage.status != "resolved").order_by(desc(ServiceOutage.started_at))
    outages = (await db.execute(stmt)).scalars().all()
    return outages


@router.post("/outages")
async def create_outage(
        outage: OutageCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role("admin"))
):
    """Admin endpoint: Report a new outage."""
    new_outage = ServiceOutage(**outage.model_dump())
    db.add(new_outage)
    await db.commit()
    return new_outage


@router.patch("/outages/{outage_id}/resolve")
async def resolve_outage(
        outage_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role("admin"))
):
    """Admin endpoint: Mark outage as resolved."""
    outage = await db.get(ServiceOutage, outage_id)
    if not outage:
        raise HTTPException(404, "Outage not found")

    outage.status = "resolved"
    outage.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"message": "Outage resolved"}