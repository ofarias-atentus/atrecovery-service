"""Usage-limits admin router (admin:manage). One template → many limits."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.catalog import Template
from app.models.identity import Role, User
from app.models.resources import ResourceGroup
from app.models.usage import UsageLimit
from app.schemas.usage import UsageLimitCreate, UsageLimitRead

router = APIRouter()
ADMIN = require_admin()


async def _check_scope(db: AsyncSession, scope_type: str, scope_id: int | None) -> None:
    if scope_type == "global":
        if scope_id is not None:
            raise HTTPException(status_code=422, detail="global scope takes no scope_id")
        return
    if scope_id is None:
        raise HTTPException(status_code=422, detail=f"{scope_type} scope requires scope_id")
    model = {"user": User, "role": Role, "group": ResourceGroup}[scope_type]
    exists = (await db.execute(select(model.id).where(model.id == scope_id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"{scope_type} {scope_id} not found")


@router.post(
    "", response_model=UsageLimitRead, status_code=status.HTTP_201_CREATED, summary="Create usage limit"
)
async def create_limit(
    body: UsageLimitCreate, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> UsageLimit:
    if (
        await db.execute(select(Template.id).where(Template.id == body.template_id))
    ).scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="template not found")
    await _check_scope(db, body.scope_type, body.scope_id)
    lim = UsageLimit(**body.model_dump())
    db.add(lim)
    await db.commit()
    await db.refresh(lim)
    return lim


@router.get("", response_model=list[UsageLimitRead], summary="List usage limits")
async def list_limits(
    template_id: int | None = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(ADMIN),
) -> list[UsageLimit]:
    stmt = select(UsageLimit).order_by(UsageLimit.id)
    if template_id is not None:
        stmt = stmt.where(UsageLimit.template_id == template_id)
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars().all())


@router.delete("/{limit_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete usage limit")
async def delete_limit(
    limit_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> None:
    lim = (await db.execute(select(UsageLimit).where(UsageLimit.id == limit_id))).scalar_one_or_none()
    if lim is None:
        raise HTTPException(status_code=404, detail="limit not found")
    await db.delete(lim)
    await db.commit()
