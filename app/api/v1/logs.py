"""Activity logs reader (admin-only). Append-only: list + detail, no write routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.activity import ActivityLog
from app.models.identity import User
from app.schemas.activity import ActivityLogRead

router = APIRouter()
ADMIN = require_admin()


@router.get("", response_model=list[ActivityLogRead], summary="List activity logs (admin)")
async def list_logs(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(ADMIN),
) -> list[ActivityLog]:
    stmt = select(ActivityLog).order_by(ActivityLog.id.desc())
    if action is not None:
        stmt = stmt.where(ActivityLog.action == action)
    if entity_type is not None:
        stmt = stmt.where(ActivityLog.entity_type == entity_type)
    if user_id is not None:
        stmt = stmt.where(ActivityLog.user_id == user_id)
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())


@router.get("/{log_id}", response_model=ActivityLogRead, summary="Get activity log entry (admin)")
async def get_log(
    log_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> ActivityLog:
    entry = (
        await db.execute(select(ActivityLog).where(ActivityLog.id == log_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="log entry not found")
    return entry
