"""Resource / metadata / group schemas (Pydantic v2)."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["Moto G6 3"])
    identifier: str = Field(min_length=1, max_length=128, examples=["ZY323S5GHW"])
    platform: str | None = Field(default=None, examples=["android"])
    platform_version: str | None = Field(default=None, examples=["8.0.0"])
    description: str | None = Field(default=None, examples=["random device"])
    extra: dict[str, Any] | None = None


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    platform: str | None = None
    platform_version: str | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None
    is_active: bool | None = None


class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    identifier: str
    platform: str | None = None
    platform_version: str | None = None
    description: str | None = None
    extra: dict[str, Any] | None = None
    is_active: bool
    metadata: dict[str, Any] = {}
    groups: list[str] = []


class MetadataDefCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64, examples=["hostname"])
    value_type: Literal["str", "int", "float", "bool", "json"] = "str"
    description: str | None = None


class MetadataDefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    value_type: str
    description: str | None = None


class MetadataSet(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: Any


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["lab-phones"])
    description: str | None = None


class MemberAdd(BaseModel):
    resource_id: int


class AssignmentCreate(BaseModel):
    principal_type: Literal["user", "role"]
    principal_id: int


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    principal_type: str
    principal_id: int


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    resources: list[str] = []  # resource identifiers
    assignments: list[AssignmentRead] = []
