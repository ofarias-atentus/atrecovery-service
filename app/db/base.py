"""SQLAlchemy 2.0 DeclarativeBase + shared mixins.

Stages 1+ will add concrete models importing Base from here.
Terminology rule: use `template`, never `script`.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActiveMixin:
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
