"""Users router: admin list/create, self-or-admin read/update, role assignment."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_user_permissions, require_permission
from app.core.security import hash_password
from app.db.session import get_db
from app.models.identity import Role, User, UserRole
from app.schemas.identity import UserCreate, UserRead, UserUpdate

router = APIRouter()
MANAGE = require_permission("users:manage")


def _to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[r.name for r in user.roles],
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserRead], summary="List users (admin)")
async def list_users(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> list[UserRead]:
    result = await db.execute(select(User).order_by(User.id).limit(limit).offset(offset))
    return [_to_read(u) for u in result.scalars().all()]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Create user (admin)")
async def create_user(
    body: UserCreate, db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> UserRead:
    exists = await db.execute(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="username or email already exists")
    user = User(username=body.username, email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    await db.flush()
    for role_name in body.role_names:
        r = await db.execute(select(Role).where(Role.name == role_name))
        role = r.scalar_one_or_none()
        if role is None:
            raise HTTPException(status_code=404, detail=f"role not found: {role_name}")
        db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.commit()
    await db.refresh(user)
    # reload roles relationship for response
    result = await db.execute(select(User).where(User.id == user.id))
    return _to_read(result.scalar_one())


@router.get("/count/total", summary="User count (admin)")
async def count_users(
    db: AsyncSession = Depends(get_db), _: User = Depends(MANAGE)
) -> dict[str, int]:
    total = (await db.execute(select(func.count(User.id)))).scalar_one()
    return {"total": total}


@router.get("/{user_id}", response_model=UserRead, summary="Get user (self or admin)")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> UserRead:
    if user_id != current.id and not current.is_superuser:
        held = await get_user_permissions(db, current)
        if "users:manage" not in held:
            raise HTTPException(status_code=403, detail="missing permissions: users:manage")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _to_read(user)


@router.patch("/{user_id}", response_model=UserRead, summary="Update user (self or admin)")
async def update_user(
    user_id: int,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
) -> UserRead:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    is_self = user_id == current.id
    if not is_self and not current.is_superuser:
        held = await get_user_permissions(db, current)
        if "users:manage" not in held:
            raise HTTPException(status_code=403, detail="missing permissions: users:manage")
    if body.email is not None:
        user.email = body.email
    if body.password is not None:
        user.hashed_password = hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_superuser is not None:
        if not current.is_superuser:
            raise HTTPException(status_code=403, detail="only superusers can grant superuser")
        user.is_superuser = body.is_superuser
    await db.commit()
    result = await db.execute(select(User).where(User.id == user_id))
    return _to_read(result.scalar_one())


@router.post("/{user_id}/roles/{role_name}", response_model=UserRead, summary="Assign role (admin)")
async def assign_role(
    user_id: int,
    role_name: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> UserRead:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role not found: {role_name}")
    exists = await db.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    )
    if exists.scalar_one_or_none() is None:
        db.add(UserRole(user_id=user_id, role_id=role.id))
        await db.commit()
    result = await db.execute(select(User).where(User.id == user_id))
    return _to_read(result.scalar_one())


@router.delete("/{user_id}/roles/{role_name}", response_model=UserRead, summary="Unassign role (admin)")
async def unassign_role(
    user_id: int,
    role_name: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(MANAGE),
) -> UserRead:
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role not found: {role_name}")
    link = await db.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
    )
    obj = link.scalar_one_or_none()
    if obj is not None:
        await db.delete(obj)
        await db.commit()
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _to_read(user)
