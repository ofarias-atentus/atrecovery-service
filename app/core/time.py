"""UTC time helpers — single source of truth for "now".

Convention (SQLite cannot store time zones; its bind processor silently
drops ``tzinfo`` and reads come back naive):

- persistence + domain logic: :func:`utcnow_naive` (naive UTC everywhere),
- JWT/security claims only: :func:`utcnow` (aware UTC, PyJWT semantics).

Never compare or mix the two families; never use local time
(``datetime.today()``, ``fromtimestamp()``, bare ``datetime.now()``).
"""
from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current time as tz-aware UTC (security/JWT claims only)."""
    return datetime.now(UTC)


def utcnow_naive() -> datetime:
    """Current time as naive UTC (all DB/domain datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)
