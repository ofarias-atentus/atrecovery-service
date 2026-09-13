"""Resource groups router: members + assignments to user/role principals.

Read: resource:view. Write: resource:manage.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models.identity import Role, User, UserRole
from app.models.resources import GroupAssignment, Resource, ResourceGroup, ResourceGroupMember
from app.schemas.resources import (
    AssignmentCreate,
    AssignmentRead,
    GroupCreate,
    GroupRead,
    MemberAdd,
)
from app.services.activity import GROUP_CHANGED, client_ip, log_activity

router = APIRouter()
VIEW = require_permission("resource:view")
MANAGE = require_permission("resource:manage")


def _to_read(g: ResourceGroup) -> GroupRead:
    return GroupRead(
        id=g.id,
        name=g.name,
        description=g.description,
        resources=sorted([r.identifier for r in g.resources]),
        assignments=[
            AssignmentRead(
                id=a.id, group_id=a.group_id, principal_type=a.principal_type, principal_id=a.principal_id
            )
            for a in g.assignments
        ],
    )


async def _get_or_404(db: AsyncSession, group_id: int) -> ResourceGroup:
    result = await db.execute(select(ResourceGroup).where(ResourceGroup.id == group_id))
    g = result.scalar_one_or_none()
    if g is None:
        raise HTTPException(status_code=404, detail="group not found")
    return g


async def _fresh_group(db: AsyncSession, group_id: int) -> ResourceGroup:
    # The session identity map may hold a stale resources/assignments collection
    # loaded before the mutation; expire so the re-read sees the new rows.
    db.expire_all()
    return await _get_or_404(db, group_id)


async def _check_principal(db: AsyncSession, principal_type: str, principal_id: int) -> None:
    if principal_type == "user":
        exists = await db.execute(select(User).where(User.id == principal_id))
        if exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="principal user not found")
    else:
        exists = await db.execute(select(Role).where(Role.id == principal_id))
        if exists.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="principal role not found")


@router.get("", response_model=list[GroupRead], summary="List resource groups")
async def list_groups(
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(VIEW),
) -> list[GroupRead]:
    result = await db.execute(select(ResourceGroup).order_by(ResourceGroup.name).limit(limit).offset(offset))
    return [_to_read(g) for g in result.scalars().all()]


@router.get("/{group_id}", response_model=GroupRead, summary="Get group with members + assignments")
async def get_group(
    group_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(VIEW)
) -> GroupRead:
    return _to_read(await _get_or_404(db, group_id))


@router.post(
    "", response_model=GroupRead, status_code=status.HTTP_201_CREATED, summary="Create group"
)
async def create_group(
    body: GroupCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> GroupRead:
    dup = await db.execute(select(ResourceGroup).where(ResourceGroup.name == body.name))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="group already exists")
    g = ResourceGroup(name=body.name, description=body.description)
    db.add(g)
    await db.commit()
    await log_activity(
        db, action=GROUP_CHANGED, user_id=user.id,
        entity_type="resource_group", entity_id=g.id,
        meta={"op": "created", "name": g.name}, ip=client_ip(request),
    )
    return _to_read(await _get_or_404(db, g.id))


@router.post("/{group_id}/members", response_model=GroupRead, summary="Add resource to group")
async def add_member(
    group_id: int,
    body: MemberAdd,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> GroupRead:
    g = await _get_or_404(db, group_id)
    r = (await db.execute(select(Resource).where(Resource.id == body.resource_id))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="resource not found")
    link = await db.execute(
        select(ResourceGroupMember).where(
            ResourceGroupMember.group_id == g.id, ResourceGroupMember.resource_id == r.id
        )
    )
    if link.scalar_one_or_none() is None:
        db.add(ResourceGroupMember(group_id=g.id, resource_id=r.id))
        await db.commit()
        await log_activity(
            db, action=GROUP_CHANGED, user_id=user.id,
            entity_type="resource_group", entity_id=g.id,
            meta={"op": "member_added", "resource_id": r.id}, ip=client_ip(request),
        )
    return _to_read(await _fresh_group(db, group_id))


@router.delete(
    "/{group_id}/members/{resource_id}",
    response_model=GroupRead,
    summary="Remove resource from group",
)
async def remove_member(
    group_id: int,
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> GroupRead:
    link = await db.execute(
        select(ResourceGroupMember).where(
            ResourceGroupMember.group_id == group_id, ResourceGroupMember.resource_id == resource_id
        )
    )
    obj = link.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="membership not found")
    await db.delete(obj)
    await db.commit()
    await log_activity(
        db, action=GROUP_CHANGED, user_id=user.id,
        entity_type="resource_group", entity_id=group_id,
        meta={"op": "member_removed", "resource_id": resource_id}, ip=client_ip(request),
    )
    return _to_read(await _fresh_group(db, group_id))


@router.post("/{group_id}/assignments", response_model=GroupRead, summary="Assign group to user/role")
async def add_assignment(
    group_id: int,
    body: AssignmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> GroupRead:
    g = await _get_or_404(db, group_id)
    await _check_principal(db, body.principal_type, body.principal_id)
    dup = await db.execute(
        select(GroupAssignment).where(
            GroupAssignment.group_id == g.id,
            GroupAssignment.principal_type == body.principal_type,
            GroupAssignment.principal_id == body.principal_id,
        )
    )
    if dup.scalar_one_or_none() is None:
        db.add(
            GroupAssignment(
                group_id=g.id,
                principal_type=body.principal_type,
                principal_id=body.principal_id,
                created_by=user.id,
            )
        )
        await db.commit()
        await log_activity(
            db, action=GROUP_CHANGED, user_id=user.id,
            entity_type="resource_group", entity_id=g.id,
            meta={"op": "assigned", "principal_type": body.principal_type,
                  "principal_id": body.principal_id},
            ip=client_ip(request),
        )
    return _to_read(await _fresh_group(db, group_id))


@router.delete(
    "/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove assignment"
)
async def remove_assignment(
    assignment_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(MANAGE),
) -> None:
    result = await db.execute(select(GroupAssignment).where(GroupAssignment.id == assignment_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="assignment not found")
    meta = {"op": "unassigned", "group_id": obj.group_id,
            "principal_type": obj.principal_type, "principal_id": obj.principal_id}
    group_id = obj.group_id
    await db.delete(obj)
    await db.commit()
    await log_activity(
        db, action=GROUP_CHANGED, user_id=user.id,
        entity_type="resource_group", entity_id=group_id, meta=meta, ip=client_ip(request),
    )


@router.get(
    "/by-principal/{principal_type}/{principal_id}",
    response_model=list[GroupRead],
    summary="Groups assigned to a user or role (incl. role's groups for a user)",
)
async def groups_for_principal(
    principal_type: str,
    principal_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(VIEW),
) -> list[GroupRead]:
    if principal_type not in ("user", "role"):
        raise HTTPException(status_code=400, detail="principal_type must be user|role")
    pairs = [(principal_type, principal_id)]
    if principal_type == "user":
        rows = (
            await db.execute(select(UserRole.role_id).where(UserRole.user_id == principal_id))
        ).scalars().all()
        pairs += [("role", rid) for rid in rows]
    group_ids: set[int] = set()
    for ptype, pid in pairs:
        rows = (
            await db.execute(
                select(GroupAssignment.group_id).where(
                    GroupAssignment.principal_type == ptype, GroupAssignment.principal_id == pid
                )
            )
        ).scalars().all()
        group_ids.update(rows)
    if not group_ids:
        return []
    result = await db.execute(select(ResourceGroup).where(ResourceGroup.id.in_(group_ids)))
    return [_to_read(g) for g in result.scalars().all()]
