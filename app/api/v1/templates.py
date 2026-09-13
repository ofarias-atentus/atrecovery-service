"""Templates router (retrieve/maintain/categorize; execution is out-of-scope).

Read: template:view code + object grant (direct/role/group). Fetch:
template:use code + use grant. Write: template:manage.
DELETE is a soft deactivate (is_active=False) to preserve usage history.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.catalog import Template, TemplateCategory
from app.models.identity import User
from app.schemas.catalog import TemplateCreate, TemplateFetch, TemplateRead, TemplateUpdate
from app.services.activity import TEMPLATE_FETCH, client_ip, log_activity
from app.services.rbac import granted_template_ids, require_template_access
from app.services.usage_svc import LimitExceeded, check_limits

router = APIRouter()
VIEW = require_permission("template:view")
MANAGE = require_permission("template:manage")
VIEW_GRANT = require_template_access("view")
USE_GRANT = require_template_access("use")


def _to_read(t: Template) -> TemplateRead:
    return TemplateRead(
        id=t.id,
        name=t.name,
        version=t.version,
        category_id=t.category_id,
        category_name=t.category.name if t.category else "",
        content=t.content,
        input_schema=t.input_schema,
        is_active=t.is_active,
        created_by=t.created_by,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=list[TemplateRead], summary="List granted templates")
async def list_templates(
    category_id: int | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(VIEW),
) -> list[TemplateRead]:
    stmt = select(Template).order_by(Template.name, Template.version)
    if category_id is not None:
        stmt = stmt.where(Template.category_id == category_id)
    if not include_inactive:
        stmt = stmt.where(Template.is_active.is_(True))
    if (allowed := await granted_template_ids(db, user, "view")) is not None:
        if not allowed:
            return []
        stmt = stmt.where(Template.id.in_(allowed))
    result = await db.execute(stmt.limit(limit).offset(offset))
    return [_to_read(t) for t in result.scalars().all()]


@router.get("/{template_id}", response_model=TemplateRead, summary="Get template")
async def get_template(t: Template = Depends(VIEW_GRANT)) -> TemplateRead:
    return _to_read(t)


@router.get("/{template_id}/fetch", response_model=TemplateFetch, summary="Fetch template content")
async def fetch_template(
    request: Request,
    t: Template = Depends(USE_GRANT),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Template:
    # Stage 6 adds activity logging.
    if not t.is_active:
        raise HTTPException(status_code=404, detail="template not found")
    try:
        await check_limits(db, user, t.id)
    except LimitExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)) from e
    await log_activity(
        db, action=TEMPLATE_FETCH, user_id=user.id,
        entity_type="template", entity_id=t.id, ip=client_ip(request),
    )
    return t


@router.post(
    "", response_model=TemplateRead, status_code=status.HTTP_201_CREATED, summary="Create template"
)
async def create_template(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> TemplateRead:
    cat = (await db.execute(select(TemplateCategory).where(TemplateCategory.id == body.category_id))).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="category not found")
    dup = await db.execute(
        select(Template).where(Template.name == body.name, Template.version == body.version)
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="template name+version already exists")
    t = Template(
        name=body.name,
        version=body.version,
        category_id=body.category_id,
        content=body.content,
        input_schema=body.input_schema,
        created_by=user.id,
    )
    db.add(t)
    await db.commit()
    result = await db.execute(select(Template).where(Template.id == t.id))
    return _to_read(result.scalar_one())


@router.patch("/{template_id}", response_model=TemplateRead, summary="Update template")
async def update_template(
    template_id: int,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> TemplateRead:
    result = await db.execute(select(Template).where(Template.id == template_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="template not found")
    if body.content is not None:
        t.content = body.content
    if body.input_schema is not None:
        t.input_schema = body.input_schema
    if body.is_active is not None:
        t.is_active = body.is_active
    await db.commit()
    result = await db.execute(select(Template).where(Template.id == template_id))
    return _to_read(result.scalar_one())


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate template")
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> None:
    result = await db.execute(select(Template).where(Template.id == template_id))
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="template not found")
    t.is_active = False  # soft delete: usages/beacons keep their history
    await db.commit()
