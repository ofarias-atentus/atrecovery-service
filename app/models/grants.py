"""Object-level grant models (Stage 3).

Complements coarse RBAC permission codes: a non-superuser needs BOTH the
relevant permission code (e.g. ``template:view``) AND a grant row.
Grant principals are ``user`` | ``role`` | ``group`` (resource groups).
Group principals resolve through ``GroupAssignment`` (direct user assign
or via one of the user's roles). Deny by default.
"""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PrincipalType = str  # "user" | "role" | "group"


class TemplateGrant(Base):
    """View/use rights on one template for one principal."""

    __tablename__ = "template_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("templates.id", ondelete="CASCADE"), index=True
    )
    principal_type: Mapped[str] = mapped_column(String(10), index=True)
    principal_id: Mapped[int] = mapped_column(Integer, index=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use: Mapped[bool] = mapped_column(Boolean, default=False)


class ResourceGrant(Base):
    """View/use rights on one resource OR one group (exactly one set)."""

    __tablename__ = "resource_grants"
    __table_args__ = (
        CheckConstraint(
            "(resource_id IS NULL) != (group_id IS NULL)",
            name="ck_resource_grants_single_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(10), index=True)
    principal_id: Mapped[int] = mapped_column(Integer, index=True)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False)
    can_use: Mapped[bool] = mapped_column(Boolean, default=False)
