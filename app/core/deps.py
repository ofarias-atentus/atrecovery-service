"""Auth dependencies: current user + RBAC permission gates (Stage 1).

Object-level grants (template/resource) arrive in Stage 3 via services/rbac.py;
this module only handles coarse permission codes + superuser bypass.
Stage 5 adds processor-service token auth (X-Processor-Token, sha256).
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.beacons import ProcessorService
from app.models.identity import Permission, Role, RolePermission, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
processor_scheme = APIKeyHeader(name="X-Processor-Token", auto_error=False)


async def get_user_permissions(db: AsyncSession, user: User) -> set[str]:
    if user.is_superuser:
        result = await db.execute(select(Permission.code))
        return set(result.scalars().all())
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    result = await db.execute(select(User).where(User.id == int(payload["sub"])))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return user


def require_permission(*codes: str) -> Callable:
    """Dependency factory: caller must hold ALL listed permission codes (or be superuser)."""

    async def checker(
        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
    ) -> User:
        if user.is_superuser:
            return user
        held = await get_user_permissions(db, user)
        missing = [c for c in codes if c not in held]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permissions: {', '.join(missing)}",
            )
        return user

    return checker


def require_admin() -> Callable:
    return require_permission("admin:manage")


def hash_processor_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_processor(
    token: str | None = Depends(processor_scheme), db: AsyncSession = Depends(get_db)
) -> ProcessorService:
    """Processor auth: X-Processor-Token matched by sha256, constant-time compare."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing processor token"
        )
    incoming = hash_processor_token(token)
    result = await db.execute(
        select(ProcessorService).where(ProcessorService.is_active.is_(True))
    )
    for proc in result.scalars().all():
        if hmac.compare_digest(proc.token_hash, incoming):
            return proc
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid processor token"
    )
