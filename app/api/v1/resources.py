"""Resources router: typed JSON-data resources.

Resources are ``id / name / identifier / type + data JSON``. ``data`` is
validated against the owning ``ResourceType.schema`` when present (same
mechanism as template content validation).

Read: resource:view code + object grant (direct or via granted group).
Write: resource:manage. DELETE is a soft deactivate (is_active=False).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models.identity import User
from app.models.resources import Resource, ResourceType
from app.schemas.resources import ResourceCreate, ResourceRead, ResourceUpdate
from app.services.rbac import require_resource_access, resource_access_map
from app.services.validation import validate_json_data

router = APIRouter()
VIEW = require_permission("resource:view")
MANAGE = require_permission("resource:manage")
VIEW_GRANT = require_resource_access("view")


def _to_read(r: Resource) -> ResourceRead:
    return ResourceRead(
        id=r.id,
        name=r.name,
        identifier=r.identifier,
        resource_type_id=r.resource_type_id,
        resource_type_name=r.resource_type.name if r.resource_type else None,
        data=r.data,
        is_active=r.is_active,
        groups=[g.name for g in r.groups],
    )


async def _get_or_404(db: AsyncSession, resource_id: int) -> Resource:
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    r = result.scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="resource not found")
    return r


async def _resolve_type(db: AsyncSession, resource_type_id: int | None) -> ResourceType | None:
    if resource_type_id is None:
        return None
    t = (
        await db.execute(select(ResourceType).where(ResourceType.id == resource_type_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="resource type not found")
    return t


@router.get("", response_model=list[ResourceRead], summary="List granted resources")
async def list_resources(
    resource_type_id: int | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(VIEW),
) -> list[ResourceRead]:
    stmt = select(Resource).order_by(Resource.id)
    if resource_type_id is not None:
        stmt = stmt.where(Resource.resource_type_id == resource_type_id)
    if not include_inactive:
        stmt = stmt.where(Resource.is_active.is_(True))
    if (allowed := await resource_access_map(db, user, "view")) is not None:
        if not allowed:
            return []
        stmt = stmt.where(Resource.id.in_(allowed))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/{resource_id}", response_model=ResourceRead, summary="Get resource with JSON data")
async def get_resource(r: Resource = Depends(VIEW_GRANT)) -> ResourceRead:
    return _to_read(r)


@router.post(
    "", response_model=ResourceRead, status_code=status.HTTP_201_CREATED, summary="Create resource"
)
async def create_resource(
    body: ResourceCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> ResourceRead:
    dup = await db.execute(select(Resource).where(Resource.identifier == body.identifier))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="identifier already exists")
    rtype = await _resolve_type(db, body.resource_type_id)
    validate_json_data(body.data, rtype.schema if rtype else None, label="data")
    r = Resource(
        name=body.name,
        identifier=body.identifier,
        resource_type_id=body.resource_type_id,
        data=body.data,
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
    new_type_id = body.resource_type_id if body.resource_type_id is not None else r.resource_type_id
    new_data = body.data if body.data is not None else r.data
    if body.data is not None or body.resource_type_id is not None:
        rtype = await _resolve_type(db, new_type_id)
        validate_json_data(new_data, rtype.schema if rtype else None, label="data")
    if body.name is not None:
        r.name = body.name
    if body.resource_type_id is not None:
        r.resource_type_id = body.resource_type_id
    if body.data is not None:
        r.data = body.data
    if body.is_active is not None:
        r.is_active = body.is_active
    await db.commit()
    return _to_read(await _get_or_404(db, resource_id))


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate resource")
async def delete_resource(
    resource_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> None:
    r = await _get_or_404(db, resource_id)
    r.is_active = False
    await db.commit()
