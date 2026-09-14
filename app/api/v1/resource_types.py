"""Resource types router (e.g. mobile_device).

Read: resource:view. Write: resource:manage.
Types carry an optional JSON Schema (``schema``) that validates
``Resource.data`` on create/update — same mechanism as template validation.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models.identity import User
from app.models.resources import ResourceType
from app.schemas.resources import ResourceTypeCreate, ResourceTypeRead, ResourceTypeUpdate

router = APIRouter()
VIEW = require_permission("resource:view")
MANAGE = require_permission("resource:manage")


def _to_read(t: ResourceType) -> ResourceTypeRead:
    return ResourceTypeRead(
        id=t.id,
        name=t.name,
        description=t.description,
        schema_def=t.schema,
        is_active=t.is_active,
    )


@router.get("", response_model=list[ResourceTypeRead], summary="List resource types")
async def list_types(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(VIEW),
) -> list[ResourceTypeRead]:
    result = await db.execute(
        select(ResourceType).order_by(ResourceType.name).limit(limit).offset(offset)
    )
    return [_to_read(t) for t in result.scalars().all()]


@router.get("/{type_id}", response_model=ResourceTypeRead, summary="Get resource type")
async def get_type(
    type_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> ResourceTypeRead:
    result = await db.execute(select(ResourceType).where(ResourceType.id == type_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="resource type not found")
    return _to_read(t)


@router.post(
    "", response_model=ResourceTypeRead, status_code=status.HTTP_201_CREATED, summary="Create type"
)
async def create_type(
    body: ResourceTypeCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> ResourceTypeRead:
    exists = await db.execute(select(ResourceType).where(ResourceType.name == body.name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="resource type already exists")
    t = ResourceType(
        name=body.name, description=body.description, schema=body.schema_def,
        is_active=body.is_active,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _to_read(t)


@router.patch("/{type_id}", response_model=ResourceTypeRead, summary="Update resource type")
async def update_type(
    type_id: int,
    body: ResourceTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> ResourceTypeRead:
    result = await db.execute(select(ResourceType).where(ResourceType.id == type_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="resource type not found")
    if body.description is not None:
        t.description = body.description
    if body.schema_def is not None:
        t.schema = body.schema_def
    if body.is_active is not None:
        t.is_active = body.is_active
    await db.commit()
    await db.refresh(t)
    return _to_read(t)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate type")
async def delete_type(
    type_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> None:
    result = await db.execute(select(ResourceType).where(ResourceType.id == type_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="resource type not found")
    t.is_active = False
    await db.commit()
