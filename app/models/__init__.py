"""Models package. Stage 1 adds identity; later stages add catalog, resources, grants, usage, beacons, tracking, stats.

Import concrete models here so Base.metadata.create_all() picks them up.
"""
from app.models.identity import (  # noqa: F401
    AuthIdentity,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
