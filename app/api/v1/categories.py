"""Template categories router.

Read: template:view. Write: template:manage.
(Stage 3 will additionally enforce object-level grants.)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models.catalog import TemplateCategory
from app.models.identity import User
from app.schemas.catalog import CategoryCreate, CategoryRead, CategoryUpdate

router = APIRouter()
VIEW = require_permission("template:view")
MANAGE = require_permission("template:manage")


def _to_read(c: TemplateCategory) -> CategoryRead:
    return CategoryRead(
        id=c.id,
        name=c.name,
        description=c.description,
        schema_hint=c.schema_hint,
        is_active=c.is_active,
        created_at=c.created_at,
    )


@router.get("", response_model=list[CategoryRead], summary="List template categories")
async def list_categories(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(VIEW),
) -> list[CategoryRead]:
    result = await db.execute(
        select(TemplateCategory).order_by(TemplateCategory.name).limit(limit).offset(offset)
    )
    return [_to_read(c) for c in result.scalars().all()]


@router.get("/{category_id}", response_model=CategoryRead, summary="Get category")
async def get_category(
    category_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> CategoryRead:
    result = await db.execute(select(TemplateCategory).where(TemplateCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="category not found")
    return _to_read(cat)


@router.post(
    "", response_model=CategoryRead, status_code=status.HTTP_201_CREATED, summary="Create category"
)
async def create_category(
    body: CategoryCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> CategoryRead:
    exists = await db.execute(select(TemplateCategory).where(TemplateCategory.name == body.name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="category already exists")
    cat = TemplateCategory(name=body.name, description=body.description, schema_hint=body.schema_hint)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return _to_read(cat)


@router.patch("/{category_id}", response_model=CategoryRead, summary="Update category")
async def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> CategoryRead:
    result = await db.execute(select(TemplateCategory).where(TemplateCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="category not found")
    if body.description is not None:
        cat.description = body.description
    if body.schema_hint is not None:
        cat.schema_hint = body.schema_hint
    if body.is_active is not None:
        cat.is_active = body.is_active
    await db.commit()
    await db.refresh(cat)
    return _to_read(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate category")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> None:
    result = await db.execute(select(TemplateCategory).where(TemplateCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail="category not found")
    cat.is_active = False  # soft delete: templates keep their history
    await db.commit()
