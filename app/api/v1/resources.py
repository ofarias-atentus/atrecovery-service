"""Resources router + per-resource metadata attach/detach.

Read: resource:view. Write: resource:manage.
DELETE is a soft deactivate (is_active=False) to preserve usage history.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models.identity import User
from app.models.resources import MetadataDefinition, Resource, ResourceMetadata
from app.schemas.resources import MetadataSet, ResourceCreate, ResourceRead, ResourceUpdate

router = APIRouter()
VIEW = require_permission("resource:view")
MANAGE = require_permission("resource:manage")


def _to_read(r: Resource) -> ResourceRead:
    return ResourceRead(
        id=r.id,
        name=r.name,
        identifier=r.identifier,
        platform=r.platform,
        platform_version=r.platform_version,
        description=r.description,
        extra=r.extra,
        is_active=r.is_active,
        metadata={e.definition.key: e.value for e in r.metadata_entries},
        groups=[g.name for g in r.groups],
    )


async def _get_or_404(db: AsyncSession, resource_id: int) -> Resource:
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="resource not found")
    return r


@router.get("", response_model=list[ResourceRead], summary="List resources")
async def list_resources(
    include_inactive: bool = False,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(VIEW),
) -> list[ResourceRead]:
    stmt = select(Resource).order_by(Resource.id)
    if not include_inactive:
        stmt = stmt.where(Resource.is_active.is_(True))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/{resource_id}", response_model=ResourceRead, summary="Get resource with metadata")
async def get_resource(
    resource_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> ResourceRead:
    return _to_read(await _get_or_404(db, resource_id))


@router.post(
    "", response_model=ResourceRead, status_code=status.HTTP_201_CREATED, summary="Create resource"
)
async def create_resource(
    body: ResourceCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> ResourceRead:
    dup = await db.execute(select(Resource).where(Resource.identifier == body.identifier))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="identifier already exists")
    r = Resource(
        name=body.name,
        identifier=body.identifier,
        platform=body.platform,
        platform_version=body.platform_version,
        description=body.description,
        extra=body.extra,
    )
    db.add(r)
    await db.commit()
    return _to_read(await _get_or_404(db, r.id))


@router.patch("/{resource_id}", response_model=ResourceRead, summary="Update resource")
async def update_resource(
    resource_id: int,
    body: ResourceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> ResourceRead:
    r = await _get_or_404(db, resource_id)
    for field in ("name", "platform", "platform_version", "description", "extra", "is_active"):
        value = getattr(body, field)
        if value is not None:
            setattr(r, field, value)
    await db.commit()
    return _to_read(await _get_or_404(db, resource_id))


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate resource")
async def delete_resource(
    resource_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> None:
    r = await _get_or_404(db, resource_id)
    r.is_active = False
    await db.commit()


@router.get("/{resource_id}/metadata", summary="Get resource metadata dict")
async def get_metadata(
    resource_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> dict[str, Any]:
    r = await _get_or_404(db, resource_id)
    return {e.definition.key: e.value for e in r.metadata_entries}


@router.put("/{resource_id}/metadata", summary="Attach/update one metadata entry (upsert)")
async def set_metadata(
    resource_id: int,
    body: MetadataSet,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> dict[str, Any]:
    r = await _get_or_404(db, resource_id)
    defn = (
        await db.execute(select(MetadataDefinition).where(MetadataDefinition.key == body.key))
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail=f"metadata definition not found: {body.key}")
    existing = (
        await db.execute(
            select(ResourceMetadata).where(
                ResourceMetadata.resource_id == r.id,
                ResourceMetadata.metadata_def_id == defn.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ResourceMetadata(resource_id=r.id, metadata_def_id=defn.id, value=body.value))
    else:
        existing.value = body.value
    await db.commit()
    return {"key": body.key, "value": body.value}


@router.delete(
    "/{resource_id}/metadata/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach one metadata entry",
)
async def delete_metadata(
    resource_id: int, key: str, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> None:
    r = await _get_or_404(db, resource_id)
    defn = (
        await db.execute(select(MetadataDefinition).where(MetadataDefinition.key == key))
    ).scalar_one_or_none()
    if defn is None:
        raise HTTPException(status_code=404, detail=f"metadata definition not found: {key}")
    existing = (
        await db.execute(
            select(ResourceMetadata).where(
                ResourceMetadata.resource_id == r.id,
                ResourceMetadata.metadata_def_id == defn.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="metadata entry not attached")
    await db.delete(existing)
    await db.commit()
