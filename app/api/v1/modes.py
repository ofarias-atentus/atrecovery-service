"""Execution modes registry (read: routine:view, write: admin:manage)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin, require_permission
from app.db.session import get_db
from app.models.identity import User
from app.models.usage import ExecutionMode
from app.schemas.usage import ExecutionModeCreate, ExecutionModeRead

router = APIRouter()
VIEW = require_permission("routine:view")
ADMIN = require_admin()


@router.get("", response_model=list[ExecutionModeRead], summary="List execution modes")
async def list_modes(
    db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> list[ExecutionMode]:
    result = await db.execute(select(ExecutionMode).order_by(ExecutionMode.id))
    return list(result.scalars().all())


@router.post(
    "", response_model=ExecutionModeRead, status_code=status.HTTP_201_CREATED, summary="Add execution mode"
)
async def create_mode(
    body: ExecutionModeCreate, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> ExecutionMode:
    if (
        await db.execute(select(ExecutionMode).where(ExecutionMode.code == body.code))
    ).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="mode code already exists")
    m = ExecutionMode(code=body.code, description=body.description)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m
