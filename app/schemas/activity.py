"""Activity log schemas (Pydantic v2). Read-only: no create/update inputs."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    user_id: int | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    meta: dict[str, Any] | None = None
    ip: str | None = None
    created_at: datetime | None = None
