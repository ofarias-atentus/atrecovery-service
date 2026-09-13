"""Statistics schemas (Pydantic v2)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StatDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    source_type: Literal["internal", "external"] = "internal"
    query_config: dict[str, Any] | None = None
    required_params: list[str] | None = None
    required_permission_code: str = "stats:view"
    is_active: bool = True


class StatDefinitionRead(StatDefinitionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class StatValueRead(BaseModel):
    name: str
    value: dict[str, Any] | None = None
