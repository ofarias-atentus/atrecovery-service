"""Object-level access evaluation (Stage 3).

Order per ``plan.md``: ``is_superuser → role permission code → direct grant
→ group assignment + group grant``. Deny by default.

A non-superuser needs BOTH the coarse permission code (``template:view`` for
view, ``template:use`` for use; same for resources) AND a matching grant row.
Grants address principals ``user`` | ``role`` | ``group``; group principals
resolve through ``GroupAssignment`` rows reaching the user directly or via one
of the user's roles. A grant on a group covers its member resources.
"""
from __future__ import annotations

from typing import Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_user_permissions
from app.db.session import get_db
from app.models.catalog import Template
from app.models.grants import ResourceGrant, TemplateGrant
from app.models.identity import User, UserRole
from app.models.resources import GroupAssignment, Resource, ResourceGroupMember

Action = Literal["view", "use"]

TEMPLATE_CODES: dict[Action, str] = {"view": "template:view", "use": "template:use"}
RESOURCE_CODES: dict[Action, str] = {"view": "resource:view", "use": "resource:use"}


async def user_role_ids(db: AsyncSession, user: User) -> set[int]:
    result = await db.execute(select(UserRole.role_id).where(UserRole.user_id == user.id))
    return set(result.scalars().all())


async def user_group_ids(db: AsyncSession, user: User) -> set[int]:
    """Groups reaching the user: direct assignment + assignments to user's roles."""
    roles = await user_role_ids(db, user)
    conds = [
        (GroupAssignment.principal_type == "user") & (GroupAssignment.principal_id == user.id)
    ]
    if roles:
        conds.append(
            (GroupAssignment.principal_type == "role") & (GroupAssignment.principal_id.in_(roles))
        )
    stmt = select(GroupAssignment.group_id).where(or_(*conds))
    result = await db.execute(stmt)
    return set(result.scalars().all())


def _principal_match(
    principal_type: str, principal_id: int, user: User, roles: set[int], groups: set[int]
) -> bool:
    if principal_type == "user":
        return principal_id == user.id
    if principal_type == "role":
        return principal_id in roles
    if principal_type == "group":
        return principal_id in groups
    return False


async def _template_flags(db: AsyncSession, user: User, template_id: int) -> tuple[bool, bool]:
    """Combined (can_view, can_use) from all grants addressing the user."""
    roles = await user_role_ids(db, user)
    groups = await user_group_ids(db, user)
    result = await db.execute(
        select(TemplateGrant).where(TemplateGrant.template_id == template_id)
    )
    view = use = False
    for g in result.scalars().all():
        if _principal_match(g.principal_type, g.principal_id, user, roles, groups):
            view = view or g.can_view
            use = use or g.can_use
    return view, use


async def has_template_access(db: AsyncSession, user: User, template_id: int, action: Action) -> bool:
    if user.is_superuser:
        return True
    if TEMPLATE_CODES[action] not in await get_user_permissions(db, user):
        return False
    view, use = await _template_flags(db, user, template_id)
    return (view or use) if action == "view" else use


async def granted_template_ids(db: AsyncSession, user: User, action: Action) -> set[int] | None:
    """Template ids visible to the user, or None for superuser (all)."""
    if user.is_superuser:
        return None
    if TEMPLATE_CODES[action] not in await get_user_permissions(db, user):
        return set()
    roles = await user_role_ids(db, user)
    groups = await user_group_ids(db, user)
    result = await db.execute(select(TemplateGrant))
    flag = "can_view" if action == "view" else "can_use"
    ids: set[int] = set()
    for g in result.scalars().all():
        # A use grant implies view (fetch returns metadata + content).
        allowed = getattr(g, flag) or (action == "view" and g.can_use)
        if allowed and _principal_match(g.principal_type, g.principal_id, user, roles, groups):
            ids.add(g.template_id)
    return ids


async def _resource_flag_rows(db: AsyncSession, user: User) -> list[ResourceGrant]:
    roles = await user_role_ids(db, user)
    groups = await user_group_ids(db, user)
    result = await db.execute(select(ResourceGrant))
    return [
        g
        for g in result.scalars().all()
        if _principal_match(g.principal_type, g.principal_id, user, roles, groups)
    ]


async def _group_member_ids(db: AsyncSession, group_id: int) -> set[int]:
    result = await db.execute(
        select(ResourceGroupMember.resource_id).where(ResourceGroupMember.group_id == group_id)
    )
    return set(result.scalars().all())


async def resource_access_map(db: AsyncSession, user: User, action: Action) -> set[int] | None:
    """Resource ids visible to the user (direct + via granted groups), None if all."""
    if user.is_superuser:
        return None
    if RESOURCE_CODES[action] not in await get_user_permissions(db, user):
        return set()
    flag = "can_view" if action == "view" else "can_use"
    ids: set[int] = set()
    for g in await _resource_flag_rows(db, user):
        allowed = getattr(g, flag) or (action == "view" and g.can_use)
        if not allowed:
            continue
        if g.resource_id is not None:
            ids.add(g.resource_id)
        elif g.group_id is not None:
            ids |= await _group_member_ids(db, g.group_id)
    return ids


async def has_resource_access(db: AsyncSession, user: User, resource_id: int, action: Action) -> bool:
    ids = await resource_access_map(db, user, action)
    return True if ids is None else resource_id in ids


def require_template_access(action: Action):
    """Dependency factory: 404 if missing, 403 if no grant; returns the Template."""

    async def checker(
        template_id: int,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Template:
        result = await db.execute(select(Template).where(Template.id == template_id))
        t = result.scalar_one_or_none()
        if t is None:
            raise HTTPException(status_code=404, detail="template not found")
        if not await has_template_access(db, user, t.id, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no grant for this template")
        return t

    return checker


def require_resource_access(action: Action):
    """Dependency factory: 404 if missing, 403 if no grant; returns the Resource."""

    async def checker(
        resource_id: int,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Resource:
        result = await db.execute(select(Resource).where(Resource.id == resource_id))
        r = result.scalar_one_or_none()
        if r is None:
            raise HTTPException(status_code=404, detail="resource not found")
        if not await has_resource_access(db, user, r.id, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no grant for this resource")
        return r

    return checker
