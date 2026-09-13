"""Usage-layer schemas (Pydantic v2)."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ModeCode = Literal["direct", "scheduler", "voucher"]
UsageStatus = Literal["pending", "dispatched", "running", "done", "failed"]


class ExecutionModeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: str = ""


class ExecutionModeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    description: str = Field(default="", max_length=255)


class UsageLimitCreate(BaseModel):
    template_id: int
    scope_type: Literal["global", "user", "role", "group"]
    scope_id: int | None = None
    max_uses: int = Field(gt=0)
    window: Literal["total", "daily", "monthly"] = "total"
    is_active: bool = True


class UsageLimitRead(UsageLimitCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class UsageCreate(BaseModel):
    template_id: int
    resource_id: int | None = None
    mode: str = "direct"
    schedule_at: datetime | None = None
    payload: dict[str, Any] | None = None


class UsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    resource_id: int | None = None
    requested_by: int
    mode: str = "direct"
    status: str
    external_dispatch_id: str | None = None
    schedule_at: datetime | None = None
    payload: dict[str, Any] | None = None
    use_count: int
    created_at: datetime | None = None


class UsageStatusRead(BaseModel):
    """Voucher-friendly status view: local state + external dispatch id + beacons."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    mode: str
    status: str
    external_dispatch_id: str | None = None
    schedule_at: datetime | None = None
    created_at: datetime | None = None
    beacon_count: int = 0
    latest_beacon_status: str | None = None
