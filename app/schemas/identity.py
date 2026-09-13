"""Identity schemas (Pydantic v2)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, examples=["operator"])
    email: EmailStr = Field(examples=["operator@example.com"])
    password: str = Field(min_length=4, max_length=128, examples=["operator123"])
    role_names: list[str] = Field(default_factory=list, examples=[["operator"]])


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=4, max_length=128)
    is_active: bool | None = None
    is_superuser: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    created_at: datetime | None = None


class MeRead(UserRead):
    permissions: list[str] = []


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64, examples=["operator"])
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    permissions: list[str] = []


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    description: str | None = None
