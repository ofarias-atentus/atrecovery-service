"""Usage-layer models (Stage 4): execution modes, template usages, usage limits.

Execution is out-of-scope: rows only relay dispatch requests (direct /
scheduler / voucher) and record state. Status transitions to running/done/
failed arrive via beacons in Stage 5.
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
    schedule_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    is_active: Mapped[bool] = mapped_column(default=True)
