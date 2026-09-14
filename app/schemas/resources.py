"""Resource / type / group schemas (Pydantic v2).

Resources are ``id / name / identifier / type + data JSON`` — all device
details live inside ``data`` (e.g. mobile device
``{"udid": ..., "nombre": ..., "plataforma": "android", ...}``) and are
validated against the owning ``ResourceType.schema`` when present.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, examples=["mobile_device"])
    description: str | None = None
    schema: dict[str, Any] | None = Field(default=None, alias="schema")
    is_active: bool = True

    model_config = ConfigDict(populate_by_name=True)


class ResourceTypeUpdate(BaseModel):
    description: str | None = None
    schema: dict[str, Any] | None = Field(default=None, alias="schema")
    is_active: bool | None = None

    model_config = ConfigDict(populate_by_name=True)


class ResourceTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    description: str | None = None
    schema: dict[str, Any] | None = Field(default=None, alias="schema")
    is_active: bool


class ResourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, examples=["Moto G6 3"])
    identifier: str = Field(min_length=1, max_length=128, examples=["ZY323S5GHW"])
    resource_type_id: int | None = None
    data: dict[str, Any] | None = Field(
        default=None,
        examples=[{"udid": "ZY323S5GHW", "nombre": "Moto G6 3", "plataforma": "android"}],
    )


class ResourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    resource_type_id: int | None = None
    data: dict[str, Any] | None = None
    is_active: bool | None = None


class ResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    identifier: str
    resource_type_id: int | None = None
    resource_type_name: str | None = None
    data: dict[str, Any] | None = None
    is_active: bool
    groups: list[str] = []


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
