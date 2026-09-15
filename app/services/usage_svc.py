"""Usage service (Stage 4): usage creation.

All timestamps naive UTC to match SQLite storage.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow_naive
from app.models.catalog import Routine
from app.models.identity import User
from app.models.resources import Resource, ResourceRoutine
from app.models.usage import ExecutionMode, RoutineUsage
from app.schemas.usage import UsageCreate
from app.services.rbac import has_resource_access, has_routine_access


def validate_cron(expr: str) -> None:
    """Raise 422 if ``expr`` is not a valid 5-field cron expression."""
    from croniter import CroniterBadCronError, croniter

    try:
        croniter(expr)
    except (CroniterBadCronError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid cron expression: {expr}",
        ) from e


def next_fire_at(cron: str | None) -> datetime | None:
    """Next fire time for a cron expression (read-time hint for executors).

    Returns None when no cron is set or the stored value is unparseable
    (defensive: rows predate validation or were written by another path).
    Nothing here ticks or dispatches — external systems own execution.
    """
    if not cron:
        return None
    try:
        from croniter import CroniterBadCronError, CroniterBadDateError, croniter

        return croniter(cron, utcnow_naive()).get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError):
        return None


async def get_mode_or_422(db: AsyncSession, code: str) -> ExecutionMode:
    mode = (
        await db.execute(select(ExecutionMode).where(ExecutionMode.code == code))
    ).scalar_one_or_none()
    if mode is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown execution mode: {code}",
        )
    return mode


async def create_usage(db: AsyncSession, user: User, body: UsageCreate) -> RoutineUsage:
    """Validate grants + resource association, then record one usage.

    Routines never execute standalone: every usage names a resource, and the
    (routine, resource) pair must be associated (closed world — a resource
    with no associations runs nothing). Enforced for everyone, superusers
    included, since association is a compatibility fact, not a permission.
    """
    mode = await get_mode_or_422(db, body.mode)
    t = (
        await db.execute(select(Routine).where(Routine.id == body.routine_id))
    ).scalar_one_or_none()
    if t is None or not t.is_active:
        raise HTTPException(status_code=404, detail="routine not found")
    if not await has_routine_access(db, user, t.id, "use"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="no use grant for this routine"
        )
    r = (
        await db.execute(select(Resource).where(Resource.id == body.resource_id))
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="resource not found")
    if not await has_resource_access(db, user, r.id, "use"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="no use grant for this resource"
        )
    link = (
        await db.execute(
            select(ResourceRoutine).where(
                ResourceRoutine.resource_id == r.id,
                ResourceRoutine.routine_id == t.id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="routine not associated with this resource",
        )
    if body.cron is not None:
        validate_cron(body.cron)
    if mode.code == "scheduler" and not body.cron:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="scheduler mode requires cron",
        )
    if mode.code != "scheduler" and body.cron is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cron only applies to scheduler mode",
        )
    usage = RoutineUsage(
        routine_id=t.id,
        resource_id=body.resource_id,
        requested_by=user.id,
        mode_id=mode.id,
        status="dispatched" if mode.code == "direct" else "pending",
        external_dispatch_id=(
            f"V-{uuid.uuid4().hex[:12].upper()}" if mode.code == "voucher" else None
        ),
        cron=body.cron,
        payload=body.payload,
    )
    db.add(usage)
    await db.commit()
    await db.refresh(usage)
    return usage
