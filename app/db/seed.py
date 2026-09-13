"""Idempotent dev/demo seed (Stage 1).

Creates permissions, roles (admin/operator), users (admin/admin123,
operator/operator123) with local auth identities.

Run: ``python -m app.db.seed`` (uses DATABASE_URL from env/.env).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import get_session_factory, init_db
from app.models.identity import AuthIdentity, Permission, Role, RolePermission, User, UserRole

PERMISSION_DEFS: list[tuple[str, str]] = [
    ("users:manage", "Create/list/update users and assign roles"),
    ("admin:manage", "Full admin control (roles, grants, definitions)"),
    ("template:view", "List and read templates"),
    ("template:use", "Fetch/use template content"),
    ("template:manage", "Create/update/delete templates and categories"),
    ("resource:view", "List and read resources"),
    ("resource:use", "Use resources in template usages"),
    ("resource:manage", "Create/update/delete resources, metadata, groups"),
    ("stats:view", "Read statistics values"),
    ("processors:manage", "Manage processor service tokens"),
]

ROLE_DEFS: dict[str, list[str]] = {
    "admin": [code for code, _ in PERMISSION_DEFS],
    "operator": ["template:view", "template:use", "resource:view", "resource:use", "stats:view"],
}

USER_DEFS: list[dict] = [
    {
        "username": "admin",
        "email": "admin@example.com",
        "password": "admin123",
        "is_superuser": True,
        "roles": ["admin"],
    },
    {
        "username": "operator",
        "email": "operator@example.com",
        "password": "operator123",
        "is_superuser": False,
        "roles": ["operator"],
    },
]


async def _get_or_create_role(db: AsyncSession, name: str, description: str) -> Role:
    result = await db.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name=name, description=description)
        db.add(role)
        await db.flush()
    return role


async def seed_all(db: AsyncSession) -> dict[str, int]:
    # Permissions
    perms: dict[str, Permission] = {}
    for code, desc in PERMISSION_DEFS:
        result = await db.execute(select(Permission).where(Permission.code == code))
        perm = result.scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            await db.flush()
        perms[code] = perm

    # Roles + role_permissions
    for role_name, codes in ROLE_DEFS.items():
        role = await _get_or_create_role(db, role_name, f"{role_name} role")
        for code in codes:
            result = await db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perms[code].id,
                )
            )
            if result.scalar_one_or_none() is None:
                db.add(RolePermission(role_id=role.id, permission_id=perms[code].id))
    await db.flush()

    # Users + user_roles + local identities
    for udef in USER_DEFS:
        result = await db.execute(select(User).where(User.username == udef["username"]))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                username=udef["username"],
                email=udef["email"],
                hashed_password=hash_password(udef["password"]),
                is_superuser=udef["is_superuser"],
            )
            db.add(user)
            await db.flush()
        for role_name in udef["roles"]:
            r = await db.execute(select(Role).where(Role.name == role_name))
            role = r.scalar_one()
            exists = await db.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
            )
            if exists.scalar_one_or_none() is None:
                db.add(UserRole(user_id=user.id, role_id=role.id))
        ident = await db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == "local",
                AuthIdentity.provider_sub == udef["username"],
            )
        )
        if ident.scalar_one_or_none() is None:
            db.add(
                AuthIdentity(
                    user_id=user.id, provider="local", provider_sub=udef["username"]
                )
            )
    await db.commit()
    return {"permissions": len(PERMISSION_DEFS), "roles": len(ROLE_DEFS), "users": len(USER_DEFS)}


async def seed_dev() -> dict[str, int]:
    await init_db()
    async with get_session_factory()() as session:
        return await seed_all(session)


if __name__ == "__main__":
    print(asyncio.run(seed_dev()))
