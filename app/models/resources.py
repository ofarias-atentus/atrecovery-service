"""Resource models: resources, reusable metadata, groups, assignments.

- MetadataDefinition = reusable metadata structure (key + value type).
- ResourceMetadata = value of one definition attached to one resource
  (interchangeable: any definition can attach to any resource).
- ResourceGroup + members + GroupAssignment (group -> user/role principal).
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import ActiveMixin, Base, TimestampMixin


class Resource(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    identifier: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    metadata_entries: Mapped[list[ResourceMetadata]] = relationship(
        back_populates="resource", cascade="all, delete-orphan", lazy="selectin"
    )
    groups: Mapped[list[ResourceGroup]] = relationship(
        secondary="resource_group_members", back_populates="resources", lazy="selectin"
    )


class MetadataDefinition(Base, TimestampMixin):
    __tablename__ = "metadata_definitions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value_type: Mapped[str] = mapped_column(String(16), default="str", nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    values: Mapped[list[ResourceMetadata]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", lazy="selectin"
    )


class ResourceMetadata(Base):
    __tablename__ = "resource_metadata"

    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    metadata_def_id: Mapped[int] = mapped_column(
        ForeignKey("metadata_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[dict | str | int | float | bool | None] = mapped_column(JSON, nullable=True)

    resource: Mapped[Resource] = relationship(back_populates="metadata_entries", lazy="selectin")
    definition: Mapped[MetadataDefinition] = relationship(back_populates="values", lazy="selectin")


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
