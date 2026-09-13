"""Pydantic v2 schemas (per domain)."""
from app.schemas.identity import (  # noqa: F401
    MeRead,
    PermissionRead,
    RefreshRequest,
    RoleCreate,
    RoleRead,
    Token,
    UserCreate,
    UserRead,
    UserUpdate,
)
