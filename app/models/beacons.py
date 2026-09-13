"""Beacon-layer models (Stage 5): processor services + execution results.

External processors authenticate with an ``X-Processor-Token`` (sha256 hash
stored, constant-time compare in ``get_processor``) and report one-to-many
beacons per usage. Beacon status drives the usage lifecycle:
ok → done, error → failed, partial → running.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProcessorService(Base):
    """External processor identity. Only the sha256 of the token is stored."""

    __tablename__ = "processor_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class ExecutionResult(Base):
    """Beacon: one result report from a processor for a usage."""

    __tablename__ = "execution_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_id: Mapped[int] = mapped_column(
        ForeignKey("template_usages.id", ondelete="CASCADE"), index=True
    )
    processor_id: Mapped[int] = mapped_column(
        ForeignKey("processor_services.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True)  # ok|error|partial
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
