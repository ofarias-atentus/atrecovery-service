"""Grant schemas (Pydantic v2)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Principal = Literal["user", "role", "group"]


class TemplateGrantCreate(BaseModel):
    template_id: int
    principal_type: Principal
    principal_id: int
    can_view: bool = True
    can_use: bool = False

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.can_view and not self.can_use:
            raise ValueError("grant must allow view and/or use")
        return self


class TemplateGrantRead(TemplateGrantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class ResourceGrantCreate(BaseModel):
    resource_id: int | None = None
    group_id: int | None = None
    principal_type: Principal
    principal_id: int
    can_view: bool = True
    can_use: bool = False

    @model_validator(mode="after")
    def _single_target(self):
        targets = [self.resource_id is not None, self.group_id is not None]
        if sum(targets) != 1:
            raise ValueError("exactly one of resource_id / group_id must be set")
        if not self.can_view and not self.can_use:
            raise ValueError("grant must allow view and/or use")
        return self


class ResourceGrantRead(ResourceGrantCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
