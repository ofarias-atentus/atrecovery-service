"""Resources router: typed JSON-data resources + typed metadata.

Resources are ``id / name / identifier / type + data JSON``. ``data`` is
validated against the owning ``ResourceType.schema`` when present (same
mechanism as template content and metadata validation).

Metadata lives separately: each ``ResourceMetadata`` entry has its own
``MetadataType`` (JSON schema) and ``data`` JSON; a resource can have
multiple metadata entries.

Templates are associated per resource (``resource_templates`` join rows):
a template can only be executed against an associated resource (closed
world — a resource with no associations runs nothing). Discovery via
``GET /{id}/templates`` lists associated templates the caller holds a
use-grant on; execution itself stays ``POST /usages`` with a mandatory
``resource_id``.

Read: resource:view code + object grant (direct or via granted group).
Write: resource:manage. DELETE is a soft deactivate (is_active=False).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.catalog import Template
from app.models.identity import User
from app.models.resources import (
    MetadataType,
    Resource,
    ResourceMetadata,
    ResourceTemplate,
    ResourceType,
)
from app.schemas.catalog import TemplateRead
from app.schemas.resources import (
    ResourceCreate,
    ResourceMetadataCreate,
    ResourceMetadataRead,
    ResourceMetadataUpdate,
    ResourceRead,
    ResourceUpdate,
    TemplateAttach,
)
from app.services.rbac import (
    granted_template_ids,
    require_resource_access,
    resource_access_map,
)
from app.services.validation import validate_json_data

router = APIRouter()
VIEW = require_permission("resource:view")
MANAGE = require_permission("resource:manage")
VIEW_GRANT = require_resource_access("view")


def _meta_to_read(m: ResourceMetadata) -> ResourceMetadataRead:
    return ResourceMetadataRead(
        id=m.id,
        resource_id=m.resource_id,
        metadata_type_id=m.metadata_type_id,
        metadata_type_name=m.metadata_type.name if m.metadata_type else "",
        data=m.data,
    )


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
        metadata=[_meta_to_read(m) for m in (r.metadata_entries or [])],
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


async def _resolve_metadata_type(
    db: AsyncSession, body: ResourceMetadataCreate
) -> MetadataType:
    t: MetadataType | None = None
    if body.metadata_type_id is not None:
        t = (
            await db.execute(
                select(MetadataType).where(MetadataType.id == body.metadata_type_id)
            )
        ).scalar_one_or_none()
    elif body.metadata_type:
        t = (
            await db.execute(select(MetadataType).where(MetadataType.name == body.metadata_type))
        ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="metadata type not found")
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


@router.get(
    "/{resource_id}/metadata",
    response_model=list[ResourceMetadataRead],
    summary="List resource metadata entries",
)
async def list_metadata(r: Resource = Depends(VIEW_GRANT)) -> list[ResourceMetadataRead]:
    return [_meta_to_read(m) for m in (r.metadata_entries or [])]


@router.post(
    "/{resource_id}/metadata",
    response_model=ResourceMetadataRead,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a typed metadata entry to a resource",
)
async def attach_metadata(
    resource_id: int,
    body: ResourceMetadataCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> ResourceMetadataRead:
    r = await _get_or_404(db, resource_id)
    t = await _resolve_metadata_type(db, body)
    validate_json_data(body.data, t.schema, label="metadata.data")
    dup = (
        await db.execute(
            select(ResourceMetadata).where(
                ResourceMetadata.resource_id == r.id,
                ResourceMetadata.metadata_type_id == t.id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="metadata of this type already attached")
    m = ResourceMetadata(resource_id=r.id, metadata_type_id=t.id, data=body.data)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    # reload with type relationship for the computed name field
    fresh = (
        await db.execute(select(ResourceMetadata).where(ResourceMetadata.id == m.id))
    ).scalar_one()
    return _meta_to_read(fresh)


@router.patch(
    "/{resource_id}/metadata/{metadata_id}",
    response_model=ResourceMetadataRead,
    summary="Update a resource metadata entry",
)
async def update_metadata(
    resource_id: int,
    metadata_id: int,
    body: ResourceMetadataUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> ResourceMetadataRead:
    m = (
        await db.execute(
            select(ResourceMetadata).where(
                ResourceMetadata.id == metadata_id,
                ResourceMetadata.resource_id == resource_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="metadata entry not found")
    if body.data is not None:
        t = (
            await db.execute(select(MetadataType).where(MetadataType.id == m.metadata_type_id))
        ).scalar_one()
        validate_json_data(body.data, t.schema, label="metadata.data")
        m.data = body.data
        await db.commit()
    fresh = (
        await db.execute(select(ResourceMetadata).where(ResourceMetadata.id == m.id))
    ).scalar_one()
    return _meta_to_read(fresh)


@router.delete(
    "/{resource_id}/metadata/{metadata_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a metadata entry from a resource",
)
async def detach_metadata(
    resource_id: int,
    metadata_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> None:
    m = (
        await db.execute(
            select(ResourceMetadata).where(
                ResourceMetadata.id == metadata_id,
                ResourceMetadata.resource_id == resource_id,
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="metadata entry not found")
    await db.delete(m)
    await db.commit()


def _template_to_read(t: Template) -> TemplateRead:
    return TemplateRead(
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


@router.get(
    "/{resource_id}/templates",
    response_model=list[TemplateRead],
    summary="List templates associated with this resource that the caller may use",
)
async def list_resource_templates(
    r: Resource = Depends(VIEW_GRANT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateRead]:
    """Resource-first discovery: associated templates ∩ caller's use-grants."""
    associated = set(
        (
            await db.execute(
                select(ResourceTemplate.template_id).where(
                    ResourceTemplate.resource_id == r.id
                )
            )
        )
        .scalars()
        .all()
    )
    if not associated:
        return []
    if (usable := await granted_template_ids(db, user, "use")) is None:
        usable = associated  # superuser: every association is executable
    else:
        usable = associated & usable
    if not usable:
        return []
    rows = (
        await db.execute(
            select(Template)
            .where(Template.id.in_(usable), Template.is_active.is_(True))
            .order_by(Template.name, Template.version)
        )
    ).scalars().all()
    return [_template_to_read(t) for t in rows]


@router.post(
    "/{resource_id}/templates",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Associate a template with a resource",
)
async def attach_template(
    resource_id: int,
    body: TemplateAttach,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> TemplateRead:
    r = await _get_or_404(db, resource_id)
    t = (
        await db.execute(select(Template).where(Template.id == body.template_id))
    ).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="template not found")
    dup = (
        await db.execute(
            select(ResourceTemplate).where(
                ResourceTemplate.resource_id == r.id,
                ResourceTemplate.template_id == t.id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="template already associated")
    db.add(ResourceTemplate(resource_id=r.id, template_id=t.id))
    await db.commit()
    return _template_to_read(t)


@router.delete(
    "/{resource_id}/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dissociate a template from a resource",
)
async def detach_template(
    resource_id: int,
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> None:
    link = (
        await db.execute(
            select(ResourceTemplate).where(
                ResourceTemplate.resource_id == resource_id,
                ResourceTemplate.template_id == template_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="association not found")
    await db.delete(link)
    await db.commit()
