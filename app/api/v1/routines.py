"""Routines router (retrieve/maintain/categorize).

Routines store JSON ``content`` validated against the owning category
``input_schema`` (same mechanism as resource data / metadata validation).
Read: routine:view code + object grant (direct/role/group). Fetch:
routine:use code + use grant. Write: routine:manage.
DELETE is a soft deactivate (is_active=False) to preserve usage history.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.catalog import Routine, RoutineCategory
from app.models.identity import User
from app.schemas.catalog import RoutineCreate, RoutineFetch, RoutineRead, RoutineUpdate
from app.services.activity import ROUTINE_FETCH, client_ip, log_activity
from app.services.rbac import granted_routine_ids, require_routine_access
from app.services.validation import category_schema, validate_json_data

router = APIRouter()
VIEW = require_permission("routine:view")
MANAGE = require_permission("routine:manage")
VIEW_GRANT = require_routine_access("view")
USE_GRANT = require_routine_access("use")


def _to_read(t: Routine) -> RoutineRead:
    return RoutineRead(
        id=t.id,
        name=t.name,
        version=t.version,
        category_id=t.category_id,
        category_name=t.category.name if t.category else "",
        content=t.content,
        is_active=t.is_active,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=list[RoutineRead], summary="List granted routines")
async def list_routines(
    category_id: int | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(VIEW),
) -> list[RoutineRead]:
    stmt = select(Routine).order_by(Routine.name, Routine.version)
    if category_id is not None:
        stmt = stmt.where(Routine.category_id == category_id)
    if not include_inactive:
        stmt = stmt.where(Routine.is_active.is_(True))
    if (allowed := await granted_routine_ids(db, user, "view")) is not None:
        if not allowed:
            return []
        stmt = stmt.where(Routine.id.in_(allowed))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [_to_read(t) for t in result.scalars().all()]


@router.get("/{routine_id}", response_model=RoutineRead, summary="Get routine")
async def get_routine(t: Routine = Depends(VIEW_GRANT)) -> RoutineRead:
    return _to_read(t)


@router.get("/{routine_id}/fetch", response_model=RoutineFetch, summary="Fetch routine content")
async def fetch_routine(
    request: Request,
    t: Routine = Depends(USE_GRANT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Routine:
    # Stage 6 adds activity logging.
    if not t.is_active:
        raise HTTPException(status_code=404, detail="routine not found")
    await log_activity(
        db, action=ROUTINE_FETCH, user_id=user.id,
        entity_type="routine", entity_id=t.id, ip=client_ip(request),
    )
    return t


@router.post(
    "", response_model=RoutineRead, status_code=status.HTTP_201_CREATED, summary="Create routine"
)
async def create_routine(
    body: RoutineCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> RoutineRead:
    cat = (await db.execute(select(RoutineCategory).where(RoutineCategory.id == body.category_id))).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="category not found")
    dup = await db.execute(
        select(Routine).where(Routine.name == body.name, Routine.version == body.version)
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="routine name+version already exists")
    validate_json_data(body.content, category_schema(cat), label="content")
    t = Routine(
        name=body.name,
        version=body.version,
        category_id=body.category_id,
        content=body.content,
        created_by=user.id,
    )
    db.add(t)
    await db.commit()
    result = await db.execute(select(Routine).where(Routine.id == t.id))
    return _to_read(result.scalar_one())


@router.patch("/{routine_id}", response_model=RoutineRead, summary="Update routine")
async def update_routine(
    routine_id: int,
    body: RoutineUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> RoutineRead:
    result = await db.execute(select(Routine).where(Routine.id == routine_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="routine not found")
    if body.content is not None:
        cat = (
            await db.execute(
                select(RoutineCategory).where(RoutineCategory.id == t.category_id)
            )
        ).scalar_one_or_none()
        validate_json_data(body.content, category_schema(cat), label="content")
        t.content = body.content
    if body.is_active is not None:
        t.is_active = body.is_active
    await db.commit()
    result = await db.execute(select(Routine).where(Routine.id == routine_id))
    return _to_read(result.scalar_one())


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate routine")
async def delete_routine(
    routine_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> None:
    result = await db.execute(select(Routine).where(Routine.id == routine_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="routine not found")
    t.is_active = False  # soft delete: usages/beacons keep their history
    await db.commit()
