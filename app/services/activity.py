"""Activity logger (Stage 6): one helper to append audit rows.

Call sites pass the request client IP; the helper adds + commits so the row
is persisted even in otherwise read-only endpoints (fetch).
"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityLog

# Canonical action names (also used by Stage 7 stats resolvers).
TEMPLATE_FETCH = "template.fetch"
TEMPLATE_USE = "template.use"
BEACON_RECEIVED = "beacon.received"
GRANT_CHANGED = "grant.changed"
GROUP_CHANGED = "group.changed"


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def log_activity(
    db: AsyncSession,
    *,
    action: str,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        action=action,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=meta,
        ip=ip,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry
