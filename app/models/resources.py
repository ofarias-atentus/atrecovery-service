"""Resource models: types, JSON-data resources, groups, assignments.

- ResourceType = category of resource (e.g. ``mobile_device``) with an
  optional JSON Schema (``schema``) used to validate ``Resource.data``.
- Resource = ``id / name / identifier / type + data JSON``. All device
  details (udid, plataforma, ...) live inside ``data`` as JSON.
- ResourceGroup + members + GroupAssignment (group -> user/role principal).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ActiveMixin, Base, TimestampMixin


class ResourceType(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "resource_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    resources: Mapped[list[Resource]] = relationship(
        back_populates="resource_type", lazy="selectin"
    )


class Resource(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    identifier: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    resource_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_types.id", ondelete="SET NULL"), nullable=True, index=True
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    resource_type: Mapped[ResourceType | None] = relationship(
        back_populates="resources", lazy="selectin"
    )
    groups: Mapped[list[ResourceGroup]] = relationship(
        secondary="resource_group_members", back_populates="resources", lazy="selectin"
    )


class ResourceGroup(Base, TimestampMixin):
    __tablename__ = "resource_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    resources: Mapped[list[Resource]] = relationship(
        secondary="resource_group_members", back_populates="groups", lazy="selectin"
    )
    assignments: Mapped[list[GroupAssignment]] = relationship(
        back_populates="group", cascade="all, delete-orphan", lazy="selectin"
    )


class ResourceGroupMember(Base):
    __tablename__ = "resource_group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("resource_groups.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )


class GroupAssignment(Base, TimestampMixin):
    """Assigns a resource group to a principal (user or role)."""

    __tablename__ = "group_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("resource_groups.id", ondelete="CASCADE"), index=True
    )
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | role
    principal_id: Mapped[int] = mapped_column(nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group: Mapped[ResourceGroup] = relationship(back_populates="assignments")
