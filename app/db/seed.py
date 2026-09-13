"""Idempotent dev/demo seed (Stages 1-2).

Stage 1: permissions, roles (admin/operator), users (admin/admin123,
operator/operator123) with local auth identities.
Stage 2: template categories (python/json), hello.py template, Moto G6
resource + metadata, lab-phones group assigned to the operator role.

Run: ``python -m app.db.seed`` (uses DATABASE_URL from env/.env).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import get_session_factory, init_db
from app.models.catalog import Template, TemplateCategory
from app.models.identity import AuthIdentity, Permission, Role, RolePermission, User, UserRole
from app.models.resources import (
    GroupAssignment,
    MetadataDefinition,
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceMetadata,
)

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
    await seed_catalog(db)
    return {
        "permissions": len(PERMISSION_DEFS),
        "roles": len(ROLE_DEFS),
        "users": len(USER_DEFS),
        "categories": len(CATEGORY_DEFS),
    }


CATEGORY_DEFS: list[tuple[str, str]] = [
    ("python", "Python templates (executable code relayed to processor services)"),
    ("json", "JSON templates (structured payloads relayed to processor services)"),
]

METADATA_DEFS: list[tuple[str, str, str]] = [
    ("monitor", "str", "Monitor identifier"),
    ("nodo", "str", "Node identifier"),
    ("nombre", "str", "Display name"),
    ("descripcion", "str", "Description"),
    ("hostname", "str", "Host name"),
    ("host", "str", "Host address"),
    ("servidor_log", "str", "Log server"),
]

TEMPLATE_DEFS: list[dict] = [
    {
        "name": "hello.py",
        "version": 1,
        "category": "python",
        "content": 'print("hello from template hello.py")\n',
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
    },
]

RESOURCE_DEFS: list[dict] = [
    {
        "name": "Moto G6 3",
        "identifier": "ZY323S5GHW",
        "platform": "android",
        "platform_version": "8.0.0",
        "description": "random device",
        "metadata": {
            "monitor": "monitor-01",
            "nodo": "nodo-lab",
            "nombre": "Moto G6 3",
            "descripcion": "random device",
            "hostname": "moto-g6-3.lab",
            "host": "10.0.0.31",
            "servidor_log": "logs.lab.local",
        },
    },
]

GROUP_DEFS: list[dict] = [
    {"name": "lab-phones", "description": "Lab test devices", "members": ["ZY323S5GHW"]},
]


async def seed_catalog(db: AsyncSession) -> None:
    """Idempotent catalog seed (Stage 2)."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()

    cats: dict[str, TemplateCategory] = {}
    for name, desc in CATEGORY_DEFS:
        cat = (await db.execute(select(TemplateCategory).where(TemplateCategory.name == name))).scalar_one_or_none()
        if cat is None:
            cat = TemplateCategory(name=name, description=desc)
            db.add(cat)
            await db.flush()
        cats[name] = cat

    for tdef in TEMPLATE_DEFS:
        existing = (
            await db.execute(
                select(Template).where(Template.name == tdef["name"], Template.version == tdef["version"])
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                Template(
                    name=tdef["name"],
                    version=tdef["version"],
                    category_id=cats[tdef["category"]].id,
                    content=tdef["content"],
                    input_schema=tdef["input_schema"],
                    created_by=admin.id,
                )
            )
    await db.flush()

    defns: dict[str, MetadataDefinition] = {}
    for key, vtype, desc in METADATA_DEFS:
        d = (await db.execute(select(MetadataDefinition).where(MetadataDefinition.key == key))).scalar_one_or_none()
        if d is None:
            d = MetadataDefinition(key=key, value_type=vtype, description=desc)
            db.add(d)
            await db.flush()
        defns[key] = d

    resources: dict[str, Resource] = {}
    for rdef in RESOURCE_DEFS:
        r = (await db.execute(select(Resource).where(Resource.identifier == rdef["identifier"]))).scalar_one_or_none()
        if r is None:
            r = Resource(
                name=rdef["name"],
                identifier=rdef["identifier"],
                platform=rdef["platform"],
                platform_version=rdef["platform_version"],
                description=rdef["description"],
            )
            db.add(r)
            await db.flush()
        resources[rdef["identifier"]] = r
        for key, value in rdef["metadata"].items():
            link = (
                await db.execute(
                    select(ResourceMetadata).where(
                        ResourceMetadata.resource_id == r.id,
                        ResourceMetadata.metadata_def_id == defns[key].id,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                db.add(ResourceMetadata(resource_id=r.id, metadata_def_id=defns[key].id, value=value))
    await db.flush()

    operator_role = (await db.execute(select(Role).where(Role.name == "operator"))).scalar_one()
    for gdef in GROUP_DEFS:
        g = (await db.execute(select(ResourceGroup).where(ResourceGroup.name == gdef["name"]))).scalar_one_or_none()
        if g is None:
            g = ResourceGroup(name=gdef["name"], description=gdef["description"])
            db.add(g)
            await db.flush()
        for identifier in gdef["members"]:
            link = (
                await db.execute(
                    select(ResourceGroupMember).where(
                        ResourceGroupMember.group_id == g.id,
                        ResourceGroupMember.resource_id == resources[identifier].id,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                db.add(ResourceGroupMember(group_id=g.id, resource_id=resources[identifier].id))
        assign = (
            await db.execute(
                select(GroupAssignment).where(
                    GroupAssignment.group_id == g.id,
                    GroupAssignment.principal_type == "role",
                    GroupAssignment.principal_id == operator_role.id,
                )
            )
        ).scalar_one_or_none()
        if assign is None:
            db.add(
                GroupAssignment(
                    group_id=g.id, principal_type="role", principal_id=operator_role.id,
                    created_by=admin.id,
                )
            )
    await db.commit()


async def seed_dev() -> dict[str, int]:
    await init_db()
    async with get_session_factory()() as session:
        return await seed_all(session)


if __name__ == "__main__":
    print(asyncio.run(seed_dev()))
