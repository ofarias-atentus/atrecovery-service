"""Resource models: types, JSON-data resources, typed metadata, groups.

- ResourceType = category of resource (e.g. ``mobile_device``) with an
  optional JSON Schema (``schema``) used to validate ``Resource.data``.
- Resource = ``id / name / identifier / type + data JSON``. Device
  details (udid, plataforma, ...) live inside ``data`` as JSON.
- MetadataType = category of metadata (e.g. ``monitor``) with an optional
  JSON Schema used to validate ``ResourceMetadata.data``.
- ResourceMetadata = one typed JSON metadata entry attached to a resource.
  A resource can have multiple metadata entries (one per type).
- ResourceGroup + members + GroupAssignment (group -> user/role principal).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
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

    def __str__(self) -> str:
        return self.name


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
    metadata_entries: Mapped[list[ResourceMetadata]] = relationship(
        back_populates="resource", cascade="all, delete-orphan", lazy="selectin"
    )

    def __str__(self) -> str:
        return f"{self.name} ({self.identifier})"


class MetadataType(Base, TimestampMixin, ActiveMixin):
    __tablename__ = "metadata_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    entries: Mapped[list[ResourceMetadata]] = relationship(
        back_populates="metadata_type", lazy="selectin"
    )

    def __str__(self) -> str:
        return self.name


class ResourceMetadata(Base, TimestampMixin):
    __tablename__ = "resource_metadata"
    __table_args__ = (
        UniqueConstraint("resource_id", "metadata_type_id", name="uq_resource_metadata"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    metadata_type_id: Mapped[int] = mapped_column(
        ForeignKey("metadata_types.id", ondelete="RESTRICT"), index=True
    )
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    resource: Mapped[Resource] = relationship(back_populates="metadata_entries", lazy="selectin")
    metadata_type: Mapped[MetadataType] = relationship(back_populates="entries", lazy="selectin")

    def __str__(self) -> str:
        return f"resource:{self.resource_id} :: metadata-type:{self.metadata_type_id}"


class ResourceTemplate(Base):
    """Associates one template with one resource (resource-first execution).

    A template can only be executed against a resource it is associated
    with; a resource with no rows here runs nothing (closed world).
    """

    __tablename__ = "resource_templates"

    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True
    )

    def __str__(self) -> str:
        return f"resource:{self.resource_id} ↔ template:{self.template_id}"


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

    def __str__(self) -> str:
        return self.name


class ResourceGroupMember(Base):
    __tablename__ = "resource_group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("resource_groups.id", ondelete="CASCADE"), primary_key=True
    )
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )

    def __str__(self) -> str:
        return f"group:{self.group_id} ↔ resource:{self.resource_id}"


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

    def __str__(self) -> str:
        return f"group:{self.group_id} → {self.principal_type}:{self.principal_id}"
