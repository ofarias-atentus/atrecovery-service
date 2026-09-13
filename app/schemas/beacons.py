"""Beacon/processor schemas (Pydantic v2)."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BeaconStatus = Literal["ok", "error", "partial"]

#: Usage lifecycle transition applied when a beacon lands.
BEACON_TO_USAGE = {"ok": "done", "error": "failed", "partial": "running"}


class ProcessorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(default_factory=lambda: ["beacon:report"])


class ProcessorRead(BaseModel):
    """Never includes the token or its hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scopes: list[str] | None = None
    is_active: bool


class ProcessorCreateResult(ProcessorRead):
    """Token is shown once here and never again."""

    token: str


class BeaconCreate(BaseModel):
    usage_id: int
    status: BeaconStatus
    result: dict[str, Any] | None = None


class BeaconRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usage_id: int
    processor_id: int
    status: str
    result: dict[str, Any] | None = None
    received_at: datetime | None = None
