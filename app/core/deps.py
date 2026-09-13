"""Auth dependencies: current user + RBAC permission gates (Stage 1).

Object-level grants (template/resource) arrive in Stage 3 via services/rbac.py;
this module only handles coarse permission codes + superuser bypass.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.session import get_db
from app.models.identity import Permission, Role, RolePermission, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


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
