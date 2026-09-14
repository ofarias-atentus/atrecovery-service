"""Usage-layer models (Stage 4): execution modes, template usages, usage limits.

Execution is out-of-scope and owned by external systems: rows only relay
dispatch requests (direct / scheduler / voucher) and record state reported
via beacons. Scheduler usages carry a cron expression describing recurrence;
the external executor reads it (plus the read-time ``next_fire_at`` hint)
and decides when to fire — nothing in this codebase ticks or dispatches.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExecutionMode(Base):
    """Dispatch mode registry (direct|scheduler|voucher + future extensions)."""

    __tablename__ = "execution_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")

    def __str__(self) -> str:
        return self.code


class TemplateUsage(Base):
    """One relayed use of a template against a resource (resource mandatory)."""

    __tablename__ = "template_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mode_id: Mapped[int] = mapped_column(
        ForeignKey("execution_modes.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    external_dispatch_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    cron: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __str__(self) -> str:
        return f"template:{self.template_id} on resource:{self.resource_id} (#{self.id or '?'})"


class UsageLimit(Base):
    """Max uses of one template per scope × window. One template → many limits."""

    __tablename__ = "usage_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    scope_type: Mapped[str] = mapped_column(String(10), index=True)  # global|user|role|group
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer)
    window: Mapped[str] = mapped_column(String(10))  # total|daily|monthly

    def __str__(self) -> str:
        scope = self.scope_type if self.scope_id is None else f"{self.scope_type}:{self.scope_id}"
        return f"template:{self.template_id} {scope}/{self.window} ≤{self.max_uses}"
    is_active: Mapped[bool] = mapped_column(default=True)
