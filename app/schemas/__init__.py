"""Pydantic v2 schemas (per domain)."""
from app.schemas.catalog import (  # noqa: F401
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    TemplateCreate,
    TemplateRead,
    TemplateUpdate,
)
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
from app.schemas.resources import (  # noqa: F401
    AssignmentCreate,
    AssignmentRead,
    GroupCreate,
    GroupRead,
    MemberAdd,
    ResourceCreate,
    ResourceRead,
    ResourceTypeCreate,
    ResourceTypeRead,
    ResourceTypeUpdate,
    ResourceUpdate,
)
