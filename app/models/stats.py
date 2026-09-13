"""Statistics definitions model (Stage 7).

`internal` defs name a registered resolver in ``query_config.resolver``
(aggregation over usages/logs/beacons, no code change to add rows).
`external` defs carry ``query_config={url, method, headers, mapping}`` and
are fetched server-side with ``httpx``. Readers need the linked permission.
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
    required_permission_code: Mapped[str] = mapped_column(
        ForeignKey("permissions.code", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)
