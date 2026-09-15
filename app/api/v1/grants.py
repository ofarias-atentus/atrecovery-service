"""Grant management router (admin only).

``POST/GET /grants/routines`` + ``DELETE /grants/routines/{id}`` and the
same for ``/grants/resources``. Guards: ``admin:manage``; principals must
exist (user/role/group rows); no duplicate grant for the same target +
principal (409).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.catalog import Routine
from app.models.grants import ResourceGrant, RoutineGrant
from app.models.identity import Role, User
from app.models.resources import Resource, ResourceGroup
from app.schemas.grants import (
    ResourceGrantCreate,
    ResourceGrantRead,
    RoutineGrantCreate,
    RoutineGrantRead,
)
from app.services.activity import GRANT_CHANGED, client_ip, log_activity

router = APIRouter()
ADMIN = require_admin()


async def _check_principal(db: AsyncSession, principal_type: str, principal_id: int) -> None:
    model = {"user": User, "role": Role, "group": ResourceGroup}[principal_type]
    exists = (
        await db.execute(select(model.id).where(model.id == principal_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=404, detail=f"{principal_type} {principal_id} not found"
        )


# ---- routine grants ----


@router.post(
    "/routines",
    response_model=RoutineGrantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Grant routine access to a principal",
)
async def create_routine_grant(
    body: RoutineGrantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> RoutineGrant:
    if (
        await db.execute(select(Routine.id).where(Routine.id == body.routine_id))
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="routine not found")
    await _check_principal(db, body.principal_type, body.principal_id)
    dup = await db.execute(
        select(RoutineGrant).where(
            RoutineGrant.routine_id == body.routine_id,
            RoutineGrant.principal_type == body.principal_type,
            RoutineGrant.principal_id == body.principal_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="grant already exists")
    g = RoutineGrant(**body.model_dump())
    db.add(g)
    await db.commit()
    await db.refresh(g)
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="routine_grant", entity_id=g.id,
        meta={"op": "created", "routine_id": g.routine_id,
              "principal_type": g.principal_type, "principal_id": g.principal_id},
        ip=client_ip(request),
    )
    return g


@router.get("/routines", response_model=list[RoutineGrantRead], summary="List routine grants")
async def list_routine_grants(
    routine_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(ADMIN),
) -> list[RoutineGrant]:
    stmt = select(RoutineGrant).order_by(RoutineGrant.id)
    if routine_id is not None:
        stmt = stmt.where(RoutineGrant.routine_id == routine_id)
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())


@router.delete(
    "/routines/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete routine grant"
)
async def delete_routine_grant(
    grant_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> None:
    g = (await db.execute(select(RoutineGrant).where(RoutineGrant.id == grant_id))).scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail="grant not found")
    meta = {"op": "deleted", "routine_id": g.routine_id,
            "principal_type": g.principal_type, "principal_id": g.principal_id}
    await db.delete(g)
    await db.commit()
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="routine_grant", entity_id=grant_id, meta=meta, ip=client_ip(request),
    )


# ---- resource grants ----


@router.post(
    "/resources",
    response_model=ResourceGrantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Grant resource/group access to a principal",
)
async def create_resource_grant(
    body: ResourceGrantCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> ResourceGrant:
    if body.resource_id is not None and (
        await db.execute(select(Resource.id).where(Resource.id == body.resource_id))
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="resource not found")
    if body.group_id is not None and (
        await db.execute(select(ResourceGroup.id).where(ResourceGroup.id == body.group_id))
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="group not found")
    await _check_principal(db, body.principal_type, body.principal_id)
    if body.resource_id is not None:
        target = (ResourceGrant.resource_id == body.resource_id) & (
            ResourceGrant.group_id.is_(None)
        )
    else:  # schema guarantees group_id is set here
        target = (ResourceGrant.group_id == body.group_id) & (
            ResourceGrant.resource_id.is_(None)
        )
    dup = await db.execute(
        select(ResourceGrant).where(
            target,
            ResourceGrant.principal_type == body.principal_type,
            ResourceGrant.principal_id == body.principal_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="grant already exists")
    g = ResourceGrant(**body.model_dump())
    db.add(g)
    await db.commit()
    await db.refresh(g)
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="resource_grant", entity_id=g.id,
        meta={"op": "created", "resource_id": g.resource_id, "group_id": g.group_id,
              "principal_type": g.principal_type, "principal_id": g.principal_id},
        ip=client_ip(request),
    )
    return g


@router.get("/resources", response_model=list[ResourceGrantRead], summary="List resource grants")
async def list_resource_grants(
    resource_id: int | None = None,
    group_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(ADMIN),
) -> list[ResourceGrant]:
    stmt = select(ResourceGrant).order_by(ResourceGrant.id)
    if resource_id is not None:
        stmt = stmt.where(ResourceGrant.resource_id == resource_id)
    if group_id is not None:
        stmt = stmt.where(ResourceGrant.group_id == group_id)
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())


@router.delete(
    "/resources/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete resource grant"
)
async def delete_resource_grant(
    grant_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(ADMIN),
) -> None:
    g = (await db.execute(select(ResourceGrant).where(ResourceGrant.id == grant_id))).scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail="grant not found")
    meta = {"op": "deleted", "resource_id": g.resource_id, "group_id": g.group_id,
            "principal_type": g.principal_type, "principal_id": g.principal_id}
    await db.delete(g)
    await db.commit()
    await log_activity(
        db, action=GRANT_CHANGED, user_id=user.id,
        entity_type="resource_grant", entity_id=grant_id, meta=meta, ip=client_ip(request),
    )
