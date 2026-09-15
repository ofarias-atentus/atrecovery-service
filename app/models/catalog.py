"""Catalog models: routine categories + routines.

Terminology rule: `routine` everywhere, never `script`.
Routines are stored as JSON data (``content`` JSON column) and structure
is validated against the owning category ``input_schema`` — same mechanism
as resource data / metadata validation.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ActiveMixin, Base, TimestampMixin


class RoutineCategory(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "routine_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    routines: Mapped[list[Routine]] = relationship(
        back_populates="category", cascade="all, delete-orphan", lazy="selectin"
    )

    def __str__(self) -> str:
        return self.name


class Routine(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "routines"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_routine_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(default=1, server_default="1", nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("routine_categories.id", ondelete="RESTRICT"), index=True
    )
    content: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    category: Mapped[RoutineCategory] = relationship(back_populates="routines", lazy="selectin")

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"
