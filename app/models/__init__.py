"""Models package. Stage 1 adds identity; later stages add catalog, resources, grants, usage, beacons, tracking, stats.

Import concrete models here so Base.metadata.create_all() picks them up.
"""
from app.models.activity import ActivityLog  # noqa: F401
from app.models.beacons import ExecutionResult, ProcessorService  # noqa: F401
from app.models.catalog import Routine, RoutineCategory  # noqa: F401
from app.models.grants import ResourceGrant, RoutineGrant  # noqa: F401
from app.models.identity import (  # noqa: F401
    AuthIdentity,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.resources import (  # noqa: F401
    GroupAssignment,
    MetadataType,
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceMetadata,
    ResourceRoutine,
    ResourceType,
)
from app.models.usage import ExecutionMode, RoutineUsage  # noqa: F401
