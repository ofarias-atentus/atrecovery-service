"""Models package. Stage 1 adds identity; later stages add catalog, resources, grants, usage, beacons, tracking, stats.

Import concrete models here so Base.metadata.create_all() picks them up.
"""
from app.models.activity import ActivityLog  # noqa: F401
from app.models.beacons import ExecutionResult, ProcessorService  # noqa: F401
from app.models.catalog import Template, TemplateCategory  # noqa: F401
from app.models.grants import ResourceGrant, TemplateGrant  # noqa: F401
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
    MetadataDefinition,
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceMetadata,
)
from app.models.stats import StatisticDefinition  # noqa: F401
from app.models.usage import ExecutionMode, TemplateUsage, UsageLimit  # noqa: F401
