"""sqladmin views + auth guard (Stage 8).

Mounted at ``/admin`` via ``setup_admin(app)``. Auth: local username/password
login; only active superusers or holders of ``admin:manage`` get a session.
``ActivityLog`` and ``ExecutionResult`` are read-only; credential hashes are
excluded from list/detail, and exposed in forms as write-only password inputs
(hashed in ``on_model_change``).

Lists show human labels (names, not raw ids): models define ``__str__`` and
views add ``column_list`` / ``column_labels`` / ``column_formatters`` that
resolve FK ids to names. Detail pages keep every column for debugging.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request
from wtforms import PasswordField
from wtforms.validators import Length, Optional

from app.core.config import get_settings
from app.core.security import hash_password, hash_service_token, verify_password
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
from app.models.usage import ExecutionMode, TemplateUsage, UsageLimit


def _sync_session_factory() -> sessionmaker:
    url = get_settings().DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _can_admin(session: Session, user: User) -> bool:
    if user.is_superuser:
        return True
    codes = session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).scalars().all()
    return "admin:manage" in codes


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username, password = str(form.get("username", "")), str(form.get("password", ""))
        factory = _sync_session_factory()
        with factory() as session:
            user = session.execute(
                select(User).where(User.username == username, User.is_active.is_(True))
            ).scalar_one_or_none()
            if user is None or not verify_password(password, user.hashed_password):
                return False
            if not _can_admin(session, user):
                return False
            request.session.update({"user_id": user.id})
            return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        user_id = request.session.get("user_id")
        if user_id is None:
            return False
        factory = _sync_session_factory()
        with factory() as session:
            user = session.execute(
                select(User).where(User.id == user_id, User.is_active.is_(True))
            ).scalar_one_or_none()
            return user is not None and _can_admin(session, user)


class _Base(ModelView):
    page_size = 50


# ---- human-readable display helpers ----
#
# sqladmin renders related objects via ``__str__`` (defined on every model),
# but bare FK id columns (principal_id, requested_by, ...) need explicit
# formatters. These do one tiny lookup per cell through a throwaway sync
# session — N+1, acceptable at PoC scale with page_size 50.

def _display_label(model: type, pk: int | None, kind: str) -> str:
    """Resolve a FK id to the row's ``__str__``; fall back to ``kind:id``."""
    if pk is None:
        return "—"
    with _sync_session_factory()() as session:
        obj = session.get(model, pk)
        return str(obj) if obj is not None else f"{kind}:{pk}"


def _fmt_created_by(m, _a) -> str:
    return _display_label(User, m.created_by, "user")


def _fmt_requested_by(m, _a) -> str:
    return _display_label(User, m.requested_by, "user")


def _fmt_user(m, _a) -> str:
    return _display_label(User, m.user_id, "user")


def _fmt_template(m, _a) -> str:
    return _display_label(Template, m.template_id, "template")


def _fmt_resource(m, _a) -> str:
    return _display_label(Resource, m.resource_id, "resource")


def _fmt_group(m, _a) -> str:
    return _display_label(ResourceGroup, m.group_id, "group")


def _fmt_category(m, _a) -> str:
    return _display_label(TemplateCategory, m.category_id, "category")


def _fmt_mode(m, _a) -> str:
    return _display_label(ExecutionMode, m.mode_id, "mode")


def _fmt_processor(m, _a) -> str:
    return _display_label(ProcessorService, m.processor_id, "processor")


_PRINCIPAL_MODELS = {"user": User, "role": Role, "group": ResourceGroup}


def _fmt_principal(m, _a) -> str:
    """``role:operator`` / ``user:operator`` / ``group:lab-phones`` (never a bare id)."""
    model = _PRINCIPAL_MODELS.get(m.principal_type)
    if model is None:
        return f"{m.principal_type}:{m.principal_id}"
    with _sync_session_factory()() as session:
        obj = session.get(model, m.principal_id)
        label = str(obj) if obj is not None else str(m.principal_id)
        return f"{m.principal_type}:{label}"


def _fmt_scope(m, _a) -> str:
    """Usage-limit scope: ``global (all)`` or ``user:operator`` / ``role:…`` / ``group:…``."""
    if m.scope_id is None:
        return f"{m.scope_type} (all)"
    model = _PRINCIPAL_MODELS.get(m.scope_type)
    if model is None:
        return f"{m.scope_type}:{m.scope_id}"
    with _sync_session_factory()() as session:
        obj = session.get(model, m.scope_id)
        label = str(obj) if obj is not None else str(m.scope_id)
        return f"{m.scope_type}:{label}"


def _fmt_usage(m, _a) -> str:
    """``hello.py on ZY323S5GHW (#5)`` instead of a bare usage id."""
    with _sync_session_factory()() as session:
        u = session.get(TemplateUsage, m.usage_id)
        if u is None:
            return f"usage:{m.usage_id}"
        t = session.get(Template, u.template_id)
        r = session.get(Resource, u.resource_id)
        t_label = t.name if t is not None else f"template:{u.template_id}"
        r_label = r.identifier if r is not None else f"resource:{u.resource_id}"
        return f"{t_label} on {r_label} (#{u.id})"


_ENTITY_MODELS = {
    "template": Template,
    "resource": Resource,
    "user": User,
    "resource_group": ResourceGroup,
}


def _fmt_entity(m, _a) -> str:
    """``template:hello.py`` instead of ``template / 3``."""
    if m.entity_type is None or m.entity_id is None:
        return "—"
    model = _ENTITY_MODELS.get(m.entity_type)
    if model is None:
        return f"{m.entity_type}:{m.entity_id}"
    with _sync_session_factory()() as session:
        obj = session.get(model, m.entity_id)
        label = str(obj) if obj is not None else str(m.entity_id)
        return f"{m.entity_type}:{label}"


class UserAdmin(_Base, model=User):
    # NOTE: column_list already omits hashed_password, so no
    # column_exclude_list (sqladmin forbids using both together).
    column_list = ["username", "email", "roles", "is_superuser", "is_active"]  # noqa: RUF012
    column_searchable_list = ["username", "email"]  # noqa: RUF012
    column_details_exclude_list = ["hashed_password"]  # noqa: RUF012
    # hashed_password is exposed as a write-only password input and
    # bcrypt-hashed in on_model_change below. Blank on edit keeps old hash.
    form_columns = ["username", "email", "roles", "is_superuser", "is_active", "hashed_password"]  # noqa: RUF012
    form_overrides = {"hashed_password": PasswordField}  # noqa: RUF012
    form_args = {"hashed_password": {"label": "Password", "validators": [Optional(), Length(min=4, max=128)]}}  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        raw = data.get("hashed_password")
        password = raw if isinstance(raw, str) and raw else ""
        if is_created and not password:
            raise ValueError("Password is required")
        if password:
            data["hashed_password"] = hash_password(password)
        else:
            # Edit with blank input: leave the stored hash untouched.
            data.pop("hashed_password", None)


class ProcessorAdmin(_Base, model=ProcessorService):
    # NOTE: column_list already omits token_hash (see UserAdmin note above).
    column_list = ["name", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012
    column_details_exclude_list = ["token_hash"]  # noqa: RUF012
    # token_hash is exposed as a write-only raw-token input and
    # sha256-hashed in on_model_change below. Blank on edit keeps old hash.
    form_columns = ["name", "is_active", "token_hash"]  # noqa: RUF012
    form_overrides = {"token_hash": PasswordField}  # noqa: RUF012
    form_args = {"token_hash": {"label": "Raw token", "validators": [Optional(), Length(min=4, max=128)]}}  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        raw = data.get("token_hash")
        token = raw if isinstance(raw, str) and raw else ""
        if is_created and not token:
            raise ValueError("Raw token is required")
        if token:
            data["token_hash"] = hash_service_token(token)
        else:
            # Edit with blank input: leave the stored hash untouched.
            data.pop("token_hash", None)


class ActivityLogAdmin(_Base, model=ActivityLog):
    can_create = False
    can_edit = False
    can_delete = False
    column_list = ["action", "user_id", "entity_type", "entity_id", "ip", "created_at"]  # noqa: RUF012
    column_labels = {"user_id": "user", "entity_type": "entity", "entity_id": "entity ref"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user, "entity_id": _fmt_entity}  # noqa: RUF012
    column_formatters_detail = {"user_id": _fmt_user, "entity_id": _fmt_entity}  # noqa: RUF012
    column_searchable_list = ["action"]  # noqa: RUF012


class ExecutionResultAdmin(_Base, model=ExecutionResult):
    can_create = False
    can_edit = False
    can_delete = False
    column_list = ["usage_id", "processor_id", "status", "received_at"]  # noqa: RUF012
    column_labels = {"usage_id": "usage", "processor_id": "processor"}  # noqa: RUF012
    column_formatters = {"usage_id": _fmt_usage, "processor_id": _fmt_processor}  # noqa: RUF012
    column_formatters_detail = {"usage_id": _fmt_usage, "processor_id": _fmt_processor}  # noqa: RUF012


class RoleAdmin(_Base, model=Role):
    column_list = ["name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class PermissionAdmin(_Base, model=Permission):
    column_list = ["code", "description"]  # noqa: RUF012
    column_searchable_list = ["code"]  # noqa: RUF012


class RolePermissionAdmin(_Base, model=RolePermission):
    column_list = ["role_id", "permission_id"]  # noqa: RUF012
    column_labels = {"role_id": "role", "permission_id": "permission"}  # noqa: RUF012
    column_formatters = {  # noqa: RUF012
        "role_id": lambda m, _a: _display_label(Role, m.role_id, "role"),
        "permission_id": lambda m, _a: _display_label(Permission, m.permission_id, "permission"),
    }


class UserRoleAdmin(_Base, model=UserRole):
    column_list = ["user_id", "role_id"]  # noqa: RUF012
    column_labels = {"user_id": "user", "role_id": "role"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user, "role_id": lambda m, _a: _display_label(Role, m.role_id, "role")}  # noqa: RUF012


class AuthIdentityAdmin(_Base, model=AuthIdentity):
    column_list = ["provider", "provider_sub", "user_id"]  # noqa: RUF012
    column_labels = {"provider_sub": "external id", "user_id": "user"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user}  # noqa: RUF012
    column_searchable_list = ["provider", "provider_sub"]  # noqa: RUF012


class TemplateCategoryAdmin(_Base, model=TemplateCategory):
    column_list = ["name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class TemplateAdmin(_Base, model=Template):
    column_list = ["name", "version", "category", "is_active", "created_by", "updated_at"]  # noqa: RUF012
    column_labels = {"category": "category", "created_by": "created by"}  # noqa: RUF012
    column_formatters = {"created_by": _fmt_created_by}  # noqa: RUF012
    column_formatters_detail = {"created_by": _fmt_created_by}  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceAdmin(_Base, model=Resource):
    column_list = ["name", "identifier", "resource_type", "is_active"]  # noqa: RUF012
    column_labels = {"resource_type": "type"}  # noqa: RUF012
    column_searchable_list = ["name", "identifier"]  # noqa: RUF012


class ResourceTypeAdmin(_Base, model=ResourceType):
    column_list = ["name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class MetadataTypeAdmin(_Base, model=MetadataType):
    column_list = ["name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceMetadataAdmin(_Base, model=ResourceMetadata):
    column_list = ["resource", "metadata_type"]  # noqa: RUF012
    column_labels = {"resource": "resource", "metadata_type": "metadata type"}  # noqa: RUF012


class ResourceTemplateAdmin(_Base, model=ResourceTemplate):
    column_list = ["resource_id", "template_id"]  # noqa: RUF012
    column_labels = {"resource_id": "resource", "template_id": "template"}  # noqa: RUF012
    column_formatters = {"resource_id": _fmt_resource, "template_id": _fmt_template}  # noqa: RUF012


class ResourceGroupAdmin(_Base, model=ResourceGroup):
    column_list = ["name", "description"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceGroupMemberAdmin(_Base, model=ResourceGroupMember):
    column_list = ["group_id", "resource_id"]  # noqa: RUF012
    column_labels = {"group_id": "group", "resource_id": "resource"}  # noqa: RUF012
    column_formatters = {"group_id": _fmt_group, "resource_id": _fmt_resource}  # noqa: RUF012


class GroupAssignmentAdmin(_Base, model=GroupAssignment):
    column_list = ["group_id", "principal_type", "principal_id", "created_by"]  # noqa: RUF012
    column_labels = {"group_id": "group", "principal_type": "type", "principal_id": "principal", "created_by": "created by"}  # noqa: RUF012
    column_formatters = {"group_id": _fmt_group, "principal_id": _fmt_principal, "created_by": _fmt_created_by}  # noqa: RUF012
    column_formatters_detail = {"group_id": _fmt_group, "principal_id": _fmt_principal, "created_by": _fmt_created_by}  # noqa: RUF012


class TemplateGrantAdmin(_Base, model=TemplateGrant):
    column_list = ["template_id", "principal_type", "principal_id", "can_view", "can_use"]  # noqa: RUF012
    column_labels = {"template_id": "template", "principal_type": "type", "principal_id": "principal"}  # noqa: RUF012
    column_formatters = {"template_id": _fmt_template, "principal_id": _fmt_principal}  # noqa: RUF012
    column_formatters_detail = {"template_id": _fmt_template, "principal_id": _fmt_principal}  # noqa: RUF012


class ResourceGrantAdmin(_Base, model=ResourceGrant):
    column_list = ["resource_id", "group_id", "principal_type", "principal_id", "can_view", "can_use"]  # noqa: RUF012
    column_labels = {"resource_id": "resource", "group_id": "group", "principal_type": "type", "principal_id": "principal"}  # noqa: RUF012
    column_formatters = {"resource_id": _fmt_resource, "group_id": _fmt_group, "principal_id": _fmt_principal}  # noqa: RUF012
    column_formatters_detail = {"resource_id": _fmt_resource, "group_id": _fmt_group, "principal_id": _fmt_principal}  # noqa: RUF012


class ExecutionModeAdmin(_Base, model=ExecutionMode):
    column_list = ["code", "description"]  # noqa: RUF012
    column_searchable_list = ["code"]  # noqa: RUF012


class TemplateUsageAdmin(_Base, model=TemplateUsage):
    column_list = ["template_id", "resource_id", "requested_by", "mode_id", "status", "external_dispatch_id", "cron", "use_count", "created_at"]  # noqa: RUF012
    column_labels = {"template_id": "template", "resource_id": "resource", "requested_by": "requested by", "mode_id": "mode", "external_dispatch_id": "dispatch id", "use_count": "uses"}  # noqa: RUF012
    column_formatters = {"template_id": _fmt_template, "resource_id": _fmt_resource, "requested_by": _fmt_requested_by, "mode_id": _fmt_mode}  # noqa: RUF012
    column_formatters_detail = {"template_id": _fmt_template, "resource_id": _fmt_resource, "requested_by": _fmt_requested_by, "mode_id": _fmt_mode}  # noqa: RUF012


class UsageLimitAdmin(_Base, model=UsageLimit):
    column_list = ["template_id", "scope_type", "scope_id", "max_uses", "window", "is_active"]  # noqa: RUF012
    column_labels = {"template_id": "template", "scope_type": "scope type", "scope_id": "scope", "max_uses": "max uses"}  # noqa: RUF012
    column_formatters = {"template_id": _fmt_template, "scope_id": _fmt_scope}  # noqa: RUF012
    column_formatters_detail = {"template_id": _fmt_template, "scope_id": _fmt_scope}  # noqa: RUF012


class DocsLinkView(BaseView):
    name = "API Docs"
    icon = "fa-solid fa-book"

    @expose("/docs-link", methods=["GET"])
    async def docs_link(self, request: Request):
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/docs")


_VIEWS = [
    UserAdmin, RoleAdmin, PermissionAdmin, RolePermissionAdmin, UserRoleAdmin,
    AuthIdentityAdmin, TemplateCategoryAdmin, TemplateAdmin, ResourceTypeAdmin,
    MetadataTypeAdmin, ResourceMetadataAdmin, ResourceTemplateAdmin, ResourceAdmin,
    ResourceGroupAdmin,
    ResourceGroupMemberAdmin, GroupAssignmentAdmin, TemplateGrantAdmin,
    ResourceGrantAdmin, ExecutionModeAdmin, TemplateUsageAdmin, UsageLimitAdmin,
    ProcessorAdmin, ExecutionResultAdmin, ActivityLogAdmin,
]


def setup_admin(app: FastAPI) -> None:
    """Create sync engine for the admin + mount sqladmin at /admin."""
    url = get_settings().DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    admin = Admin(app, engine, authentication_backend=AdminAuth(secret_key=get_settings().JWT_SECRET))
    for view in _VIEWS:
        admin.add_view(view)
    admin.add_view(DocsLinkView)
