"""Statistics service (Stage 7): internal resolvers + external fetcher.

Internal resolvers aggregate over usages / activity logs / beacons and are
registered by name, so new stats only need a definition row. External defs
are fetched server-side with a timeout; ``query_config.mapping`` optionally
projects dot-paths out of a JSON response.
NOTE (PoC): no egress allowlist — production must restrict target hosts.
"""
from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_user_permissions
from app.models.activity import ActivityLog
from app.models.beacons import ExecutionResult
from app.models.catalog import Template
from app.models.identity import User
from app.models.usage import TemplateUsage
from app.services.activity import TEMPLATE_FETCH

EXTERNAL_TIMEOUT = 10.0


async def most_used_template(db: AsyncSession, params: dict[str, str]) -> dict[str, Any]:
    row = (
        await db.execute(
            select(TemplateUsage.template_id, func.count(TemplateUsage.id).label("uses"))
            .group_by(TemplateUsage.template_id)
            .order_by(func.count(TemplateUsage.id).desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return {"template_id": None, "template_name": None, "uses": 0}
    name = (
        await db.execute(select(Template.name).where(Template.id == row.template_id))
    ).scalar_one_or_none()
    return {"template_id": row.template_id, "template_name": name, "uses": row.uses}


async def last_fetch_by_user(db: AsyncSession, params: dict[str, str]) -> dict[str, Any]:
    user_id = int(params["user_id"])
    row = (
        await db.execute(
            select(ActivityLog)
            .where(ActivityLog.action == TEMPLATE_FETCH, ActivityLog.user_id == user_id)
            .order_by(ActivityLog.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return {"user_id": user_id, "template_id": None, "fetched_at": None}
    fetched_at = row.created_at.isoformat() if row.created_at else None
    return {"user_id": user_id, "template_id": row.entity_id, "fetched_at": fetched_at}


async def beacon_success_rate(db: AsyncSession, params: dict[str, str]) -> dict[str, Any]:
    total = (await db.execute(select(func.count(ExecutionResult.id)))).scalar_one()
    ok = (
        await db.execute(
            select(func.count(ExecutionResult.id)).where(ExecutionResult.status == "ok")
        )
    ).scalar_one()
    return {"total": total, "ok": ok, "rate": (ok / total) if total else None}


RESOLVERS = {
    "most_used_template": most_used_template,
    "last_fetch_by_user": last_fetch_by_user,
    "beacon_success_rate": beacon_success_rate,
}


async def resolve_internal(
    db: AsyncSession, resolver: str, params: dict[str, str]
) -> dict[str, Any]:
    fn = RESOLVERS.get(resolver)
    if fn is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown resolver: {resolver}",
        )
    return await fn(db, params)


def _dot_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


async def fetch_external(query_config: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
    url = query_config.get("url")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="external stat needs query_config.url",
        )
    method = str(query_config.get("method", "GET")).upper()
    headers = query_config.get("headers") or {}
    try:
        async with httpx.AsyncClient(timeout=EXTERNAL_TIMEOUT) as client:
            response = await client.request(method, url, params=params, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"external stat fetch failed: {e}"
        ) from e
    try:
        data = response.json()
    except ValueError:
        data = response.text
    mapping = query_config.get("mapping")
    if isinstance(mapping, dict) and isinstance(data, (dict, list)):
        data = {key: _dot_path(data, path) for key, path in mapping.items()}
    return {"url": url, "status_code": response.status_code, "data": data}


async def _user_role_ids(db: AsyncSession, user: User) -> set[int]:
    from app.models.identity import UserRole

    result = await db.execute(select(UserRole.role_id).where(UserRole.user_id == user.id))
    return set(result.scalars().all())


async def has_stat_access(db: AsyncSession, user: User, statistic_id: int) -> bool:
    """Grant check: superuser always; else direct user grant or role grant."""
    from app.models.stats import StatisticGrant

    if user.is_superuser:
        return True
    held_roles = await _user_role_ids(db, user)
    result = await db.execute(
        select(StatisticGrant).where(
            StatisticGrant.statistic_id == statistic_id,
            StatisticGrant.can_view.is_(True),
        )
    )
    for g in result.scalars().all():
        if g.principal_type == "user" and g.principal_id == user.id:
            return True
        if g.principal_type == "role" and g.principal_id in held_roles:
            return True
    return False


async def granted_statistic_ids(db: AsyncSession, user: User) -> set[int] | None:
    """Statistic ids visible to the user, or None for superuser (all)."""
    from app.models.stats import StatisticGrant

    if user.is_superuser:
        return None
    held_roles = await _user_role_ids(db, user)
    result = await db.execute(
        select(StatisticGrant).where(StatisticGrant.can_view.is_(True))
    )
    ids: set[int] = set()
    for g in result.scalars().all():
        if g.principal_type == "user" and g.principal_id == user.id or g.principal_type == "role" and g.principal_id in held_roles:
            ids.add(g.statistic_id)
    return ids


async def check_stat_access(
    db: AsyncSession, user: User, statistic_id: int, params: dict[str, str]
) -> None:
    """Grant gate + ownership rule for per-user stats.

    Different users/roles see different statistics via StatisticGrant rows.
    ``user_id``-scoped stats additionally require ownership unless the
    caller holds ``admin:manage`` (admins may query any user).
    """
    if user.is_superuser:
        return
    if not await has_stat_access(db, user, statistic_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="no grant for this statistic",
        )
    if "user_id" in params:
        try:
            target = int(params["user_id"])
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="user_id must be an integer",
            )
        if target != user.id:
            held = await get_user_permissions(db, user)
            if "admin:manage" not in held:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="can only query your own user_id",
                )
