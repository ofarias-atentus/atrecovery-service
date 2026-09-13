"""Processor services admin router (admin:manage).

The raw token is shown ONCE in the create response; only its sha256 is
stored. DELETE is a soft deactivate so beacon history keeps its link —
deactivated processors can no longer authenticate.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import hash_processor_token, require_admin
from app.db.session import get_db
from app.models.beacons import ProcessorService
from app.models.identity import User
from app.schemas.beacons import ProcessorCreate, ProcessorCreateResult, ProcessorRead

router = APIRouter()
ADMIN = require_admin()


@router.post(
    "", response_model=ProcessorCreateResult, status_code=status.HTTP_201_CREATED,
    summary="Register processor (token shown once)",
)
async def create_processor(
    body: ProcessorCreate, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> ProcessorCreateResult:
    if (
        await db.execute(select(ProcessorService).where(ProcessorService.name == body.name))
    ).scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="processor name already exists")
    token = secrets.token_urlsafe(32)
    proc = ProcessorService(
        name=body.name, token_hash=hash_processor_token(token), scopes=body.scopes
    )
    db.add(proc)
    await db.commit()
    await db.refresh(proc)
    return ProcessorCreateResult(
        id=proc.id, name=proc.name, scopes=proc.scopes, is_active=proc.is_active, token=token
    )


@router.get("", response_model=list[ProcessorRead], summary="List processors (no tokens)")
async def list_processors(
    db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> list[ProcessorService]:
    result = await db.execute(select(ProcessorService).order_by(ProcessorService.id))
    return list(result.scalars().all())


@router.delete("/{processor_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deactivate processor")
async def delete_processor(
    processor_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(ADMIN)
) -> None:
    proc = (
        await db.execute(select(ProcessorService).where(ProcessorService.id == processor_id))
    ).scalar_one_or_none()
    if proc is None:
        raise HTTPException(status_code=404, detail="processor not found")
    proc.is_active = False
    await db.commit()
