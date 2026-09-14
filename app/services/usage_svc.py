"""Usage service (Stage 4): limit enforcement + usage creation.

Limits are checked on template fetch (no record) and on usage creation
(check + record). Scope semantics:
- global: every usage of the template counts, applies to everyone.
- user: personal quota — applies only when the requester is that user.
- role: applies to role members, counts usages requested by role members.
- group: applies to users reaching the group, counts usages whose resource
  is a member of the group.
Windows: total (all time), daily (since UTC midnight), monthly (since the
1st, UTC). All timestamps naive UTC to match SQLite storage.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Template
from app.models.identity import User, UserRole
from app.models.resources import Resource, ResourceGroupMember, ResourceTemplate
from app.models.usage import ExecutionMode, TemplateUsage, UsageLimit
from app.schemas.usage import UsageCreate
from app.services.rbac import has_resource_access, has_template_access, user_group_ids


class LimitExceeded(Exception):
    def __init__(self, limit: UsageLimit, count: int):
        self.limit = limit
        self.count = count
        super().__init__(
            f"usage limit exceeded: template {limit.template_id} "
            f"{limit.scope_type}/{limit.scope_id} {limit.window} "
            f"max {limit.max_uses} (used {count})"
        )


def _utcnow_naive() -> datetime:
    # SQLite stores naive timestamps; strip tz so window comparisons line up.
    return datetime.now(UTC).replace(tzinfo=None)


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

        return croniter(cron, _utcnow_naive()).get_next(datetime)
    except (CroniterBadCronError, CroniterBadDateError, ValueError):
        return None


def window_start(window: str) -> datetime | None:
    now = _utcnow_naive()
    if window == "total":
        return None
    if window == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unknown window: {window}")


async def _count_usages(
    db: AsyncSession,
    template_id: int,
    since: datetime | None,
    requested_by: set[int] | None = None,
    resource_ids: set[int] | None = None,
) -> int:
    stmt = select(func.count(TemplateUsage.id)).where(TemplateUsage.template_id == template_id)
    if since is not None:
        stmt = stmt.where(TemplateUsage.created_at >= since)
    if requested_by is not None:
        if not requested_by:
            return 0
        stmt = stmt.where(TemplateUsage.requested_by.in_(requested_by))
    if resource_ids is not None:
        if not resource_ids:
            return 0
        stmt = stmt.where(TemplateUsage.resource_id.in_(resource_ids))
    return (await db.execute(stmt)).scalar_one()


async def check_limits(db: AsyncSession, user: User, template_id: int) -> None:
    """Raise LimitExceeded if any active limit on the template is exhausted."""
    limits = (
        await db.execute(
            select(UsageLimit).where(
                UsageLimit.template_id == template_id, UsageLimit.is_active.is_(True)
            )
        )
    ).scalars().all()
    for lim in limits:
        since = window_start(lim.window)
        if lim.scope_type == "global":
            count = await _count_usages(db, template_id, since)
        elif lim.scope_type == "user":
            if lim.scope_id != user.id:
                continue
            count = await _count_usages(db, template_id, since, requested_by={user.id})
        elif lim.scope_type == "role":
            members = set(
                (
                    await db.execute(
                        select(UserRole.user_id).where(UserRole.role_id == lim.scope_id)
                    )
                ).scalars().all()
            )
            if user.id not in members:
                continue
            count = await _count_usages(db, template_id, since, requested_by=members)
        elif lim.scope_type == "group":
            groups = await user_group_ids(db, user)
            if lim.scope_id not in groups:
                continue
            members = set(
                (
                    await db.execute(
                        select(ResourceGroupMember.resource_id).where(
                            ResourceGroupMember.group_id == lim.scope_id
                        )
                    )
                ).scalars().all()
            )
            count = await _count_usages(db, template_id, since, resource_ids=members)
        else:
            continue
        if count >= lim.max_uses:
            raise LimitExceeded(lim, count)


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


async def create_usage(db: AsyncSession, user: User, body: UsageCreate) -> TemplateUsage:
    """Validate grants + resource association + limits, then record one usage.

    Templates never execute standalone: every usage names a resource, and the
    (template, resource) pair must be associated (closed world — a resource
    with no associations runs nothing). Enforced for everyone, superusers
    included, since association is a compatibility fact, not a permission.
    """
    mode = await get_mode_or_422(db, body.mode)
    t = (
        await db.execute(select(Template).where(Template.id == body.template_id))
    ).scalar_one_or_none()
    if t is None or not t.is_active:
        raise HTTPException(status_code=404, detail="template not found")
    if not await has_template_access(db, user, t.id, "use"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="no use grant for this template"
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
            select(ResourceTemplate).where(
                ResourceTemplate.resource_id == r.id,
                ResourceTemplate.template_id == t.id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="template not associated with this resource",
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
    try:
        await check_limits(db, user, t.id)
    except LimitExceeded as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)
        ) from e
    usage = TemplateUsage(
        template_id=t.id,
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
