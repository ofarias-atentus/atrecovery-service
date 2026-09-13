"""Roles & permissions router."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.identity import Permission, Role, RolePermission, User
from app.schemas.identity import PermissionRead, RoleCreate, RoleRead

router = APIRouter()


def _to_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=sorted([p.code for p in role.permissions]),
    )


@router.get("", response_model=list[RoleRead], summary="List roles")
async def list_roles(
    db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> list[RoleRead]:
    result = await db.execute(select(Role).order_by(Role.id))
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/permissions", response_model=list[PermissionRead], summary="List permissions")
async def list_permissions(
    db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> list[PermissionRead]:
    result = await db.execute(select(Permission).order_by(Permission.code))
    return [
        PermissionRead(id=p.id, code=p.code, description=p.description)
        for p in result.scalars().all()
    ]


@router.get("/{role_name}", response_model=RoleRead, summary="Get role by name")
async def get_role(
    role_name: str, db: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)
) -> RoleRead:
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    return _to_read(role)


@router.post(
    "",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create role (admin)",
    dependencies=[Depends(require_permission("admin:manage"))],
)
async def create_role(body: RoleCreate, db: AsyncSession = Depends(get_db)) -> RoleRead:
    exists = await db.execute(select(Role).where(Role.name == body.name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="role already exists")
    role = Role(name=body.name, description=body.description)
    db.add(role)
    await db.flush()
    for code in body.permission_codes:
        p = await db.execute(select(Permission).where(Permission.code == code))
        perm = p.scalar_one_or_none()
        if perm is None:
            raise HTTPException(status_code=404, detail=f"permission not found: {code}")
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await db.commit()
    result = await db.execute(select(Role).where(Role.id == role.id))
    return _to_read(result.scalar_one())
