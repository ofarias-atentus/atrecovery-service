"""Idempotent dev/demo seed.

- Identity: permissions (no stats permission codes), roles admin/operator,
  users admin/admin123, operator/operator123 with local auth identities.
- Templates: categories python/json; hello.py stored as JSON content with
  input_schema validation.
- Resources: types (mobile_device) + Moto G6 resource with data JSON,
  lab-phones group assigned to the operator role.
- Grants: operator role can view/use hello.py + lab-phones group.
- Usage: modes direct/scheduler/voucher + demo limit (hello.py, 10/day).
- Processors: lab-runner token.
- Stats: definitions + per-principal StatisticGrant rows (operator role can
  view all three; different users/roles can be granted differently).

Run: ``python -m app.db.seed`` (uses DATABASE_URL from env/.env).
NOTE: schema changed (JSON content/data, resource types, stat grants) —
delete any pre-existing ``data/app.db`` before reseeding.
"""
from __future__ import annotations

import asyncio
import os
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import hash_processor_token
from app.core.security import hash_password
from app.db.session import get_session_factory, init_db
from app.models.beacons import ProcessorService
from app.models.catalog import Template, TemplateCategory
from app.models.grants import ResourceGrant, TemplateGrant
from app.models.identity import AuthIdentity, Permission, Role, RolePermission, User, UserRole
from app.models.resources import (
    GroupAssignment,
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceType,
)
from app.models.stats import StatisticDefinition, StatisticGrant
from app.models.usage import ExecutionMode, UsageLimit

PERMISSION_DEFS: list[tuple[str, str]] = [
    ("users:manage", "Create/list/update users and assign roles"),
    ("admin:manage", "Full admin control (roles, grants, definitions)"),
    ("template:view", "List and read templates"),
    ("template:use", "Fetch/use template content"),
    ("template:manage", "Create/update/delete templates and categories"),
    ("resource:view", "List and read resources"),
    ("resource:use", "Use resources in template usages"),
    ("resource:manage", "Create/update/delete resources, types, groups"),
    ("processors:manage", "Manage processor service tokens"),
]

ROLE_DEFS: dict[str, list[str]] = {
    "admin": [code for code, _ in PERMISSION_DEFS],
    "operator": ["template:view", "template:use", "resource:view", "resource:use"],
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
    # Permissions (drop legacy stats:view if present from an old DB)
    perms: dict[str, Permission] = {}
    for code, desc in PERMISSION_DEFS:
        result = await db.execute(select(Permission).where(Permission.code == code))
        perm = result.scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            await db.flush()
        perms[code] = perm
    legacy = (
        await db.execute(select(Permission).where(Permission.code == "stats:view"))
    ).scalar_one_or_none()
    if legacy is not None:
        await db.delete(legacy)
        await db.flush()

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
    await seed_grants(db)
    await seed_usage(db)
    token_note = await seed_processors(db)
    await seed_stats(db)
    counts = {
        "permissions": len(PERMISSION_DEFS),
        "roles": len(ROLE_DEFS),
        "users": len(USER_DEFS),
        "categories": len(CATEGORY_DEFS),
        "resource_types": len(RESOURCE_TYPE_DEFS),
        "grants": 2,
        "modes": len(MODE_DEFS),
        "limits": 1,
        "processors": 1,
        "stats": len(STAT_DEFS),
    }
    if token_note:
        print(token_note)
    return counts


CATEGORY_DEFS: list[tuple[str, str]] = [
    ("python", "Python templates (JSON content relayed to processor services)"),
    ("json", "JSON templates (structured payloads relayed to processor services)"),
]

TEMPLATE_DEFS: list[dict] = [
    {
        "name": "hello.py",
        "version": 1,
        "category": "python",
        "content": {
            "language": "python",
            "source": 'print("hello from template hello.py")\n',
            "description": "Hello template",
        },
        "input_schema": {
            "type": "object",
            "required": ["source"],
            "properties": {
                "language": {"type": "string"},
                "source": {"type": "string"},
                "description": {"type": "string"},
            },
        },
    },
]

RESOURCE_TYPE_DEFS: list[dict] = [
    {
        "name": "mobile_device",
        "description": "Mobile test device (udid, plataforma, ...)",
        "schema": {
            "type": "object",
            "required": ["udid", "nombre", "plataforma"],
            "properties": {
                "udid": {"type": "string"},
                "nombre": {"type": "string"},
                "plataforma": {"type": "string"},
                "version_plataforma": {"type": "string"},
                "descripcion": {"type": "string"},
                "monitor": {"type": "string"},
                "nodo": {"type": "string"},
                "hostname": {"type": "string"},
                "host": {"type": "string"},
                "servidor_log": {"type": "string"},
            },
        },
    },
]

RESOURCE_DEFS: list[dict] = [
    {
        "name": "Moto G6 3",
        "identifier": "ZY323S5GHW",
        "resource_type": "mobile_device",
        "data": {
            "udid": "ZY323S5GHW",
            "nombre": "Moto G6 3",
            "plataforma": "android",
            "version_plataforma": "8.0.0",
            "descripcion": "random device",
            "monitor": "monitor-01",
            "nodo": "nodo-lab",
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
    """Idempotent catalog + resource seed (JSON content/data + types)."""
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
        else:
            # Migrate legacy TEXT content (plain string) to JSON object.
            if isinstance(existing.content, str):
                existing.content = {
                    "language": "python",
                    "source": existing.content,
                }
                if existing.input_schema is None:
                    existing.input_schema = tdef["input_schema"]
    await db.flush()

    types: dict[str, ResourceType] = {}
    for tdef in RESOURCE_TYPE_DEFS:
        t = (await db.execute(select(ResourceType).where(ResourceType.name == tdef["name"]))).scalar_one_or_none()
        if t is None:
            t = ResourceType(
                name=tdef["name"], description=tdef["description"], schema=tdef["schema"]
            )
            db.add(t)
            await db.flush()
        types[tdef["name"]] = t

    resources: dict[str, Resource] = {}
    for rdef in RESOURCE_DEFS:
        r = (await db.execute(select(Resource).where(Resource.identifier == rdef["identifier"]))).scalar_one_or_none()
        if r is None:
            r = Resource(
                name=rdef["name"],
                identifier=rdef["identifier"],
                resource_type_id=types[rdef["resource_type"]].id,
                data=rdef["data"],
            )
            db.add(r)
            await db.flush()
        else:
            # Migrate legacy columns (platform/extra/...) into data JSON when present.
            if not r.data:
                legacy_data = dict(rdef["data"])
                for attr in ("platform", "platform_version", "description", "extra"):
                    if hasattr(r, attr):
                        try:
                            val = getattr(r, attr)
                        except AttributeError:
                            continue
                        if val and attr not in legacy_data:
                            legacy_data[attr] = val
                r.data = legacy_data
            if not r.resource_type_id:
                r.resource_type_id = types[rdef["resource_type"]].id
        resources[rdef["identifier"]] = r
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


async def seed_grants(db: AsyncSession) -> None:
    """Idempotent grant seed: operator role → hello.py + lab-phones."""
    operator_role = (await db.execute(select(Role).where(Role.name == "operator"))).scalar_one()
    hello = (
        await db.execute(select(Template).where(Template.name == "hello.py"))
    ).scalar_one()
    lab = (
        await db.execute(select(ResourceGroup).where(ResourceGroup.name == "lab-phones"))
    ).scalar_one()
    tg = (
        await db.execute(
            select(TemplateGrant).where(
                TemplateGrant.template_id == hello.id,
                TemplateGrant.principal_type == "role",
                TemplateGrant.principal_id == operator_role.id,
            )
        )
    ).scalar_one_or_none()
    if tg is None:
        db.add(
            TemplateGrant(
                template_id=hello.id, principal_type="role",
                principal_id=operator_role.id, can_view=True, can_use=True,
            )
        )
    rg = (
        await db.execute(
            select(ResourceGrant).where(
                ResourceGrant.group_id == lab.id,
                ResourceGrant.principal_type == "role",
                ResourceGrant.principal_id == operator_role.id,
            )
        )
    ).scalar_one_or_none()
    if rg is None:
        db.add(
            ResourceGrant(
                group_id=lab.id, principal_type="role",
                principal_id=operator_role.id, can_view=True, can_use=True,
            )
        )
    await db.commit()


MODE_DEFS: list[tuple[str, str]] = [
    ("direct", "Immediate relay to the processor service"),
    ("scheduler", "Scheduled relay at schedule_at with payload"),
    ("voucher", "Voucher flow: returns an external_dispatch_id for state checks"),
]


async def seed_usage(db: AsyncSession) -> None:
    """Idempotent usage seed: modes + demo 10/day global limit on hello.py."""
    for code, desc in MODE_DEFS:
        m = (await db.execute(select(ExecutionMode).where(ExecutionMode.code == code))).scalar_one_or_none()
        if m is None:
            db.add(ExecutionMode(code=code, description=desc))
    await db.flush()
    hello = (
        await db.execute(select(Template).where(Template.name == "hello.py"))
    ).scalar_one()
    lim = (
        await db.execute(
            select(UsageLimit).where(
                UsageLimit.template_id == hello.id,
                UsageLimit.scope_type == "global",
                UsageLimit.window == "daily",
            )
        )
    ).scalar_one_or_none()
    if lim is None:
        db.add(
            UsageLimit(
                template_id=hello.id, scope_type="global", scope_id=None,
                max_uses=10, window="daily",
            )
        )
    await db.commit()


async def seed_processors(db: AsyncSession) -> str | None:
    """Idempotent processor seed. Returns a shown-once token note, if any."""
    proc = (
        await db.execute(select(ProcessorService).where(ProcessorService.name == "lab-runner"))
    ).scalar_one_or_none()
    if proc is not None:
        return None
    token = os.environ.get("SEED_PROCESSOR_TOKEN") or secrets.token_urlsafe(32)
    db.add(
        ProcessorService(
            name="lab-runner", token_hash=hash_processor_token(token),
            scopes=["beacon:report"],
        )
    )
    await db.commit()
    return f"[seed] lab-runner X-Processor-Token (shown once): {token}"


STAT_DEFS: list[dict] = [
    {
        "name": "most_used_template",
        "source_type": "internal",
        "query_config": {"resolver": "most_used_template"},
        "required_params": [],
    },
    {
        "name": "last_fetch_by_user",
        "source_type": "internal",
        "query_config": {"resolver": "last_fetch_by_user"},
        "required_params": ["user_id"],
    },
    {
        "name": "beacon_success_rate",
        "source_type": "internal",
        "query_config": {"resolver": "beacon_success_rate"},
        "required_params": [],
    },
]


async def seed_stats(db: AsyncSession) -> None:
    """Idempotent stats seed: definitions + operator-role grants (per-user model)."""
    for sdef in STAT_DEFS:
        existing = (
            await db.execute(select(StatisticDefinition).where(StatisticDefinition.name == sdef["name"]))
        ).scalar_one_or_none()
        if existing is None:
            existing = StatisticDefinition(**sdef)
            db.add(existing)
            await db.flush()
    await db.flush()
    operator_role = (await db.execute(select(Role).where(Role.name == "operator"))).scalar_one()
    for sdef in STAT_DEFS:
        stat = (
            await db.execute(select(StatisticDefinition).where(StatisticDefinition.name == sdef["name"]))
        ).scalar_one()
        grant = (
            await db.execute(
                select(StatisticGrant).where(
                    StatisticGrant.statistic_id == stat.id,
                    StatisticGrant.principal_type == "role",
                    StatisticGrant.principal_id == operator_role.id,
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            db.add(
                StatisticGrant(
                    statistic_id=stat.id, principal_type="role",
                    principal_id=operator_role.id, can_view=True,
                )
            )
    await db.commit()


async def seed_dev() -> dict[str, int]:
    await init_db()
    async with get_session_factory()() as session:
        return await seed_all(session)


if __name__ == "__main__":
    print(asyncio.run(seed_dev()))
