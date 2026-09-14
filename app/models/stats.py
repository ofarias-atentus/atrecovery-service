"""Statistics definitions + per-principal grants.

Access is NOT permission-code based anymore: each definition is visible
only to explicitly granted principals (``user`` | ``role``), so different
users/roles can see different statistics. Superusers (or ``admin:manage``
holders for administration) bypass the grant check.
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StatisticDefinition(Base):
    __tablename__ = "statistics_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(10))  # internal|external
    query_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    required_params: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class StatisticGrant(Base):
    """Grant statistic visibility to a user or role principal."""

    __tablename__ = "statistic_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    statistic_id: Mapped[int] = mapped_column(
        ForeignKey("statistics_definitions.id", ondelete="CASCADE"), index=True
    )
    principal_type: Mapped[str] = mapped_column(String(10), index=True)  # user | role
    principal_id: Mapped[int] = mapped_column(Integer, index=True)
    can_view: Mapped[bool] = mapped_column(default=True)
