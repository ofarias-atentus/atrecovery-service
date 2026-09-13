"""Metadata definitions router (reusable metadata structure).

Any authenticated user can list; creating/deleting needs resource:manage.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.identity import User
from app.models.resources import MetadataDefinition
from app.schemas.resources import MetadataDefCreate, MetadataDefRead

router = APIRouter()
MANAGE = require_permission("resource:manage")


@router.get("", response_model=list[MetadataDefRead], summary="List metadata definitions")
async def list_definitions(
    db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> list[MetadataDefRead]:
    result = await db.execute(select(MetadataDefinition).order_by(MetadataDefinition.key))
    return [
        MetadataDefRead(id=d.id, key=d.key, value_type=d.value_type, description=d.description)
        for d in result.scalars().all()
    ]


@router.post(
    "",
    response_model=MetadataDefRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create metadata definition",
)
async def create_definition(
    body: MetadataDefCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> MetadataDefRead:
    dup = await db.execute(select(MetadataDefinition).where(MetadataDefinition.key == body.key))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="definition key already exists")
    d = MetadataDefinition(key=body.key, value_type=body.value_type, description=body.description)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return MetadataDefRead(id=d.id, key=d.key, value_type=d.value_type, description=d.description)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete metadata definition")
async def delete_definition(
    key: str, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> None:
    result = await db.execute(select(MetadataDefinition).where(MetadataDefinition.key == key))
    d = result.scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="definition not found")
    await db.delete(d)  # attached values cascade
    await db.commit()
