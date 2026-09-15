"""Template usages router: relay dispatch requests.

Templates never execute standalone: POST needs a ``resource_id`` plus
``template:use`` + use grants on BOTH the template and the resource
(403 without), and the pair must be associated (422 otherwise — closed
world). Listing/detail is scoped: non-admins only see their own usages.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_user_permissions, require_permission
from app.db.session import get_db
from app.models.beacons import ExecutionResult
from app.models.identity import User
from app.models.usage import ExecutionMode, TemplateUsage
from app.schemas.usage import UsageCreate, UsageRead, UsageStatusRead
from app.services.activity import TEMPLATE_USE, client_ip, log_activity
from app.services.usage_svc import create_usage, next_fire_at

router = APIRouter()
USE = require_permission("template:use")
ADMIN = require_permission("admin:manage")


async def _mode_map(db: AsyncSession) -> dict[int, str]:
    result = await db.execute(select(ExecutionMode))
    return {m.id: m.code for m in result.scalars().all()}


def _to_read(u: TemplateUsage, modes: dict[int, str]) -> UsageRead:
    return UsageRead(
        id=u.id,
        template_id=u.template_id,
        resource_id=u.resource_id,
        requested_by=u.requested_by,
        mode=modes.get(u.mode_id, "?"),
        status=u.status,
        external_dispatch_id=u.external_dispatch_id,
        cron=u.cron,
        next_fire_at=next_fire_at(u.cron),
        payload=u.payload,
        use_count=u.use_count,
        created_at=u.created_at,
    )


async def _see_all(db: AsyncSession, user: User) -> bool:
    return user.is_superuser or "admin:manage" in await get_user_permissions(db, user)


async def _can_see(db: AsyncSession, user: User, u: TemplateUsage) -> bool:
    return u.requested_by == user.id or await _see_all(db, user)


@router.post(
    "", response_model=UsageRead, status_code=status.HTTP_201_CREATED, summary="Relay a template usage"
)
async def post_usage(
    body: UsageCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(USE),
) -> UsageRead:
    usage = await create_usage(db, user, body)
    await log_activity(
        db, action=TEMPLATE_USE, user_id=user.id,
        entity_type="usage", entity_id=usage.id,
        meta={"template_id": usage.template_id, "mode": body.mode, "resource_id": usage.resource_id},
        ip=client_ip(request),
    )
    return _to_read(usage, await _mode_map(db))


@router.get("", response_model=list[UsageRead], summary="List usages (own, or all for admin)")
async def list_usages(
    requested_by: int | None = None,
    template_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[UsageRead]:
    stmt = select(TemplateUsage).order_by(TemplateUsage.id.desc())
    if template_id is not None:
        stmt = stmt.where(TemplateUsage.template_id == template_id)
    if await _see_all(db, user):
        if requested_by is not None:
            stmt = stmt.where(TemplateUsage.requested_by == requested_by)
    else:
        stmt = stmt.where(TemplateUsage.requested_by == user.id)
    rows = list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())
    modes = await _mode_map(db)
    return [_to_read(u, modes) for u in rows]


@router.get("/{usage_id}", response_model=UsageRead, summary="Get usage detail")
async def get_usage(
    usage_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageRead:
    u = (await db.execute(select(TemplateUsage).where(TemplateUsage.id == usage_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="usage not found")
    if not await _can_see(db, user, u):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your usage")
    return _to_read(u, await _mode_map(db))


@router.get("/{usage_id}/status", response_model=UsageStatusRead, summary="Usage status incl. voucher id")
async def get_usage_status(
    usage_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageStatusRead:
    u = (await db.execute(select(TemplateUsage).where(TemplateUsage.id == usage_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="usage not found")
    if not await _can_see(db, user, u):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your usage")
    modes = await _mode_map(db)
    beacons = (
        await db.execute(
            select(ExecutionResult.status)
            .where(ExecutionResult.usage_id == u.id)
            .order_by(ExecutionResult.id.desc())
        )
    ).scalars().all()
    return UsageStatusRead(
        id=u.id,
        template_id=u.template_id,
        mode=modes.get(u.mode_id, "?"),
        status=u.status,
        external_dispatch_id=u.external_dispatch_id,
        cron=u.cron,
        next_fire_at=next_fire_at(u.cron),
        created_at=u.created_at,
        beacon_count=len(beacons),
        latest_beacon_status=beacons[0] if beacons else None,
    )
