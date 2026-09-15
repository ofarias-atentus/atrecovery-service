"""Admin display labels: every model renders a human identifier via __str__.

Lists in /admin rely on these (plus column formatters in app/admin/views.py)
so rows read as names, never raw ids or "<... object at 0x...>".
"""
from app.models.activity import ActivityLog
from app.models.beacons import ExecutionResult, ProcessorService
from app.models.catalog import Template, TemplateCategory
from app.models.grants import ResourceGrant, TemplateGrant
from app.models.identity import (
    AuthIdentity,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.resources import (
    GroupAssignment,
    MetadataType,
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceMetadata,
    ResourceTemplate,
    ResourceType,
)
from app.models.usage import ExecutionMode, TemplateUsage


def test_named_models_render_their_name():
    assert str(Role(name="operator")) == "operator"
    assert str(Permission(code="template:view")) == "template:view"
    assert str(User(username="operator")) == "operator"
    assert str(TemplateCategory(name="python")) == "python"
    assert str(ResourceType(name="mobile_device")) == "mobile_device"
    assert str(MetadataType(name="monitor")) == "monitor"
    assert str(ResourceGroup(name="lab-phones")) == "lab-phones"
    assert str(ExecutionMode(code="voucher")) == "voucher"
    assert str(ProcessorService(name="lab-runner")) == "lab-runner"


def test_entities_render_name_plus_key_identifier():
    assert str(Template(name="hello.py", version=2)) == "hello.py v2"
    assert str(Resource(name="Moto G6 3", identifier="ZY323S5GHW")) == "Moto G6 3 (ZY323S5GHW)"


def test_link_rows_render_both_ends():
    assert str(RolePermission(role_id=1, permission_id=2)) == "role:1 → permission:2"
    assert str(UserRole(user_id=1, role_id=2)) == "user:1 ↔ role:2"
    assert str(AuthIdentity(provider="local", provider_sub="admin")) == "local:admin"
    assert (
        str(ResourceGroupMember(group_id=1, resource_id=2)) == "group:1 ↔ resource:2"
    )
    assert (
        str(GroupAssignment(group_id=1, principal_type="role", principal_id=2))
        == "group:1 → role:2"
    )
    assert (
        str(ResourceMetadata(resource_id=1, metadata_type_id=2))
        == "resource:1 :: metadata-type:2"
    )
    assert (
        str(ResourceTemplate(resource_id=1, template_id=2)) == "resource:1 ↔ template:2"
    )


def test_grants_render_target_principal_and_flags():
    assert (
        str(TemplateGrant(template_id=3, principal_type="role", principal_id=2,
                           can_view=True, can_use=True))
        == "template:3 → role:2 (view+use)"
    )
    assert (
        str(ResourceGrant(resource_id=5, principal_type="user", principal_id=2,
                           can_view=True, can_use=False))
        == "resource:5 → user:2 (view)"
    )
    assert (
        str(ResourceGrant(group_id=1, principal_type="role", principal_id=2,
                           can_view=True, can_use=True))
        == "group:1 → role:2 (view+use)"
    )
    assert (
        str(ResourceGrant(resource_id=5, principal_type="user", principal_id=2,
                           can_view=False, can_use=False))
        == "resource:5 → user:2 (none)"
    )


def test_usage_tracking_rows_render_context():
    assert str(TemplateUsage(id=12, template_id=1, resource_id=2)) == \
        "template:1 on resource:2 (#12)"
    assert str(ExecutionResult(id=3, usage_id=1, status="ok")) == "usage:1 → ok (#3)"
    assert str(ActivityLog(id=7, action="template.fetch", entity_type="template",
                            entity_id=1)) == "template.fetch template:1 (#7)"


def test_no_default_object_repr_leaks():
    rows = [
        Role(name="r"), Permission(code="c"), User(username="u"),
        Template(name="t", version=1), TemplateCategory(name="c"),
        Resource(name="r", identifier="i"), ResourceType(name="t"),
        MetadataType(name="m"), ResourceGroup(name="g"),
        ExecutionMode(code="direct"), ProcessorService(name="p"),
        TemplateUsage(id=1, template_id=1, resource_id=1),
        ExecutionResult(id=1, usage_id=1, status="ok"),
        ActivityLog(id=1, action="a", entity_type="t", entity_id=1),
        TemplateGrant(template_id=1, principal_type="role", principal_id=1),
        ResourceGrant(group_id=1, principal_type="role", principal_id=1),
        RolePermission(role_id=1, permission_id=1), UserRole(user_id=1, role_id=1),
        AuthIdentity(provider="local", provider_sub="x"),
        ResourceMetadata(resource_id=1, metadata_type_id=1),
        ResourceTemplate(resource_id=1, template_id=1),
        ResourceGroupMember(group_id=1, resource_id=1),
        GroupAssignment(group_id=1, principal_type="role", principal_id=1),
    ]
    for row in rows:
        assert "object at 0x" not in str(row), row
