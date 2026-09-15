"""Beacons router: processors report (token auth, no JWT), users read (JWT).

POST requires the ``beacon:report`` scope and moves the usage lifecycle
(ok → done, error → failed, partial → running). Cron-driven executors may
report repeatedly: repeating a seen (usage_id, idem_key) replays the stored
row (200) instead of recording a duplicate (201). Each accepted beacon bumps
the usage ``use_count``. GET needs ``routine:view`` and is scoped to the
caller's own usages unless admin.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_processor, get_user_permissions, require_permission
from app.db.session import get_db
from app.models.beacons import ExecutionResult, ProcessorService
from app.models.identity import User
from app.models.usage import RoutineUsage
from app.schemas.beacons import BEACON_TO_USAGE, BeaconCreate, BeaconRead
from app.services.activity import BEACON_RECEIVED, client_ip, log_activity

router = APIRouter()
VIEW = require_permission("routine:view")


async def _see_all(db: AsyncSession, user: User) -> bool:
    return user.is_superuser or "admin:manage" in await get_user_permissions(db, user)


@router.post(
    "", response_model=BeaconRead, status_code=status.HTTP_201_CREATED,
    summary="Report a beacon (processor token)",
)
async def post_beacon(
    body: BeaconCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    proc: ProcessorService = Depends(get_processor),
) -> ExecutionResult:
    if "beacon:report" not in (proc.scopes or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="processor lacks beacon:report scope"
        )
    usage = (
        await db.execute(select(RoutineUsage).where(RoutineUsage.id == body.usage_id))
    ).scalar_one_or_none()
    if usage is None:
        raise HTTPException(status_code=404, detail="usage not found")
    if body.idem_key is not None:
        replay = (
            await db.execute(
                select(ExecutionResult).where(
                    ExecutionResult.usage_id == usage.id,
                    ExecutionResult.idem_key == body.idem_key,
                )
            )
        ).scalar_one_or_none()
        if replay is not None:
            response.status_code = status.HTTP_200_OK
            return replay
    beacon = ExecutionResult(
        usage_id=usage.id, processor_id=proc.id, status=body.status,
        result=body.result, idem_key=body.idem_key,
    )
    db.add(beacon)
    usage.status = BEACON_TO_USAGE[body.status]
    usage.use_count = (usage.use_count or 0) + 1
    await db.commit()
    await db.refresh(beacon)
    await log_activity(
        db, action=BEACON_RECEIVED, user_id=None,
        entity_type="usage", entity_id=usage.id,
        meta={"beacon_id": beacon.id, "processor_id": proc.id,
              "processor_name": proc.name, "status": body.status},
        ip=client_ip(request),
    )
    return beacon


@router.get("", response_model=list[BeaconRead], summary="List beacons (own usages, or all for admin)")
async def list_beacons(
    usage_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(VIEW),
) -> list[ExecutionResult]:
    stmt = select(ExecutionResult).order_by(ExecutionResult.id.desc())
    if usage_id is not None:
        stmt = stmt.where(ExecutionResult.usage_id == usage_id)
    if not await _see_all(db, user):
        own = select(RoutineUsage.id).where(RoutineUsage.requested_by == user.id)
        stmt = stmt.where(ExecutionResult.usage_id.in_(own))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return list(result.scalars().all())


@router.get("/{beacon_id}", response_model=BeaconRead, summary="Get beacon")
async def get_beacon(
    beacon_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(VIEW),
) -> ExecutionResult:
    b = (
        await db.execute(select(ExecutionResult).where(ExecutionResult.id == beacon_id))
    ).scalar_one_or_none()
    if b is None:
        raise HTTPException(status_code=404, detail="beacon not found")
    if not await _see_all(db, user):
        owner = (
            await db.execute(
                select(RoutineUsage.requested_by).where(RoutineUsage.id == b.usage_id)
            )
        ).scalar_one_or_none()
        if owner != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your beacon")
    return b
