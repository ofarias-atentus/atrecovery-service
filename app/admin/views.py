"""sqladmin views + auth guard (Stage 8).

Mounted at ``/admin`` via ``setup_admin(app)``. Auth: local username/password
login; only active superusers or holders of ``admin:manage`` get a session.
``ActivityLog`` and ``ExecutionResult`` are read-only; credential hashes are
excluded from list/detail. User passwords use a write-only form input (hashed
in ``on_model_change``); processor tokens are auto-generated on create (like
the API) and shown once via flash. Timestamps (``created_at``/``updated_at``/
``received_at``) are excluded from forms: set automatically on insert, with
``updated_at`` refreshed on edit and ``created_at``/``received_at`` immutable.

Lists show human labels (names, not raw ids): models define ``__str__`` and
views add ``column_list`` / ``column_labels`` / ``column_formatters`` that
resolve FK ids to names. Every list starts with the row ``id`` (link tables
without an ``id`` PK keep their composite keys instead). Detail pages keep
every column for debugging.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqladmin import Admin, BaseView, Flash, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request
from wtforms import PasswordField
from wtforms.validators import Length, Optional

from app.core.config import get_settings
from app.core.security import (
    generate_service_token,
    hash_password,
    hash_service_token,
    verify_password,
)
from app.core.time import utcnow_naive
from app.models.activity import ActivityLog
from app.models.beacons import ExecutionResult, ProcessorService
from app.models.catalog import Routine, RoutineCategory
from app.models.grants import ResourceGrant, RoutineGrant
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
    ResourceRoutine,
    ResourceType,
)
from app.models.usage import ExecutionMode, RoutineUsage


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
    # Short explanatory copy shown at the top of every admin page for the
    # view. Every concrete subclass must set a non-empty value (enforced
    # by tests); rendered by the shared ``sqladmin/layout.html`` override.
    admin_summary: str = ""
    # Timestamps are fully automatic: created on insert, updated_at refreshed
    # on edit. They stay visible in list/detail but never appear in forms.
    # NOTE: subclasses using explicit form_columns (UserAdmin, ProcessorAdmin)
    # already omit timestamps; the pops in on_model_change below are still
    # needed there as a guard against crafted POSTs (include beats exclude
    # in sqladmin's _build_column_list).
    form_excluded_columns = ["created_at", "updated_at", "received_at"]  # noqa: RUF012

    async def list_context(self, request: Request) -> dict[str, Any]:
        return {"admin_summary": self.admin_summary}

    async def details_context(self, request: Request) -> dict[str, Any]:
        return {"admin_summary": self.admin_summary}

    async def create_context(self, request: Request) -> dict[str, Any]:
        return {"admin_summary": self.admin_summary}

    async def edit_context(self, request: Request) -> dict[str, Any]:
        return {"admin_summary": self.admin_summary}

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        # created_at / received_at are immutable: always ignore user input so
        # the DB server_default fires on insert and rows stay stable on edit.
        data.pop("created_at", None)
        data.pop("received_at", None)
        if is_created:
            # Let server_default fill updated_at on insert as well.
            data.pop("updated_at", None)
        elif hasattr(model, "updated_at"):
            data["updated_at"] = utcnow_naive()
        else:
            data.pop("updated_at", None)


# ---- human-readable display helpers ----
#
# sqladmin renders related objects via ``__str__`` (defined on every model),
# but bare FK id columns (principal_id, requested_by, ...) need explicit
# formatters. These do one tiny lookup per cell through a throwaway sync
# session — N+1, acceptable at current scale with page_size 50.

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


def _fmt_routine(m, _a) -> str:
    return _display_label(Routine, m.routine_id, "routine")


def _fmt_resource(m, _a) -> str:
    return _display_label(Resource, m.resource_id, "resource")


def _fmt_group(m, _a) -> str:
    return _display_label(ResourceGroup, m.group_id, "group")


def _fmt_category(m, _a) -> str:
    return _display_label(RoutineCategory, m.category_id, "category")


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


def _fmt_usage(m, _a) -> str:
    """``hello.py on ZY323S5GHW (#5)`` instead of a bare usage id."""
    with _sync_session_factory()() as session:
        u = session.get(RoutineUsage, m.usage_id)
        if u is None:
            return f"usage:{m.usage_id}"
        t = session.get(Routine, u.routine_id)
        r = session.get(Resource, u.resource_id)
        t_label = t.name if t is not None else f"routine:{u.routine_id}"
        r_label = r.identifier if r is not None else f"resource:{u.resource_id}"
        return f"{t_label} on {r_label} (#{u.id})"


_ENTITY_MODELS = {
    "routine": Routine,
    "resource": Resource,
    "user": User,
    "resource_group": ResourceGroup,
}


def _fmt_entity(m, _a) -> str:
    """``routine:hello.py`` instead of ``routine / 3``."""
    if m.entity_type is None or m.entity_id is None:
        return "—"
    model = _ENTITY_MODELS.get(m.entity_type)
    if model is None:
        return f"{m.entity_type}:{m.entity_id}"
    with _sync_session_factory()() as session:
        obj = session.get(model, m.entity_id)
        label = str(obj) if obj is not None else str(m.entity_id)
        return f"{m.entity_type}:{label}"


def _rel_id(value: Any) -> int | None:
    """Resolve an admin form value to an int PK.

    Relationship select fields may yield a model instance, an int, or
    a numeric string; raw FK inputs yield ints/strings. Returns None
    when the value is empty or unresolvable.
    """
    if value is None or value == "":
        return None
    if hasattr(value, "id"):
        pk = value.id
        return int(pk) if pk is not None else None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class UserAdmin(_Base, model=User):
    admin_summary = "Manage user accounts, active status, superuser access, and assigned roles."
    # NOTE: column_list already omits hashed_password, so no
    # column_exclude_list (sqladmin forbids using both together).
    column_list = ["id", "username", "email", "roles", "is_superuser", "is_active"]  # noqa: RUF012
    column_searchable_list = ["username", "email"]  # noqa: RUF012
    column_details_exclude_list = ["hashed_password"]  # noqa: RUF012
    # hashed_password is exposed as a write-only password input and
    # bcrypt-hashed in on_model_change below. Blank on edit keeps old hash.
    form_columns = ["username", "email", "roles", "is_superuser", "is_active", "hashed_password"]  # noqa: RUF012
    form_overrides = {"hashed_password": PasswordField}  # noqa: RUF012
    form_args = {"hashed_password": {"label": "Password", "validators": [Optional(), Length(min=4, max=128)]}}  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        await super().on_model_change(data, model, is_created, request)
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
    admin_summary = "Manage external processors that report routine execution results."
    # NOTE: column_list already omits token_hash (see UserAdmin note above).
    column_list = ["id", "name", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012
    column_details_exclude_list = ["token_hash"]  # noqa: RUF012
    # The raw token is never typed in: it is auto-generated on create (like
    # the API), sha256-hashed before persist, and shown once via flash.
    # Token is immutable from the admin; rotation is a separate feature.
    # ``details`` holds free-form dynamic JSON info and is editable here.
    form_columns = ["name", "scopes", "details", "is_active"]  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        await super().on_model_change(data, model, is_created, request)
        # Ignore any forged token_hash input: the token always comes from
        # the generator, so the raw value only ever lives on request.state.
        data.pop("token_hash", None)
        if is_created:
            raw = generate_service_token()
            data["token_hash"] = hash_service_token(raw)
            request.state.generated_processor_token = raw
            # The form has no scopes input: default like the API so the new
            # processor can actually report beacons.
            if not data.get("scopes"):
                data["scopes"] = ["beacon:report"]

    async def after_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        # Implicit None return = normal sqladmin redirect; the toast rides along.
        if is_created:
            raw = getattr(request.state, "generated_processor_token", "")
            if raw:
                Flash.success(
                    request,
                    f"Processor '{model.name}' token (copy now — shown only once): {raw}",
                    "Processor token",
                )
                delattr(request.state, "generated_processor_token")


class ActivityLogAdmin(_Base, model=ActivityLog):
    admin_summary = "Review the append-only audit trail of administrative and operational activity."
    can_create = False
    can_edit = False
    can_delete = False
    column_list = ["id", "action", "user_id", "entity_type", "entity_id", "ip", "created_at"]  # noqa: RUF012
    column_labels = {"user_id": "user", "entity_type": "entity", "entity_id": "entity ref"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user, "entity_id": _fmt_entity}  # noqa: RUF012
    column_formatters_detail = {"user_id": _fmt_user, "entity_id": _fmt_entity}  # noqa: RUF012
    column_searchable_list = ["action"]  # noqa: RUF012


class ExecutionResultAdmin(_Base, model=ExecutionResult):
    admin_summary = "Review processor-reported execution results. This audit data is read-only."
    can_create = False
    can_edit = False
    can_delete = False
    column_list = ["id", "usage_id", "processor_id", "status", "received_at"]  # noqa: RUF012
    column_labels = {"usage_id": "usage", "processor_id": "processor"}  # noqa: RUF012
    column_formatters = {"usage_id": _fmt_usage, "processor_id": _fmt_processor}  # noqa: RUF012
    column_formatters_detail = {"usage_id": _fmt_usage, "processor_id": _fmt_processor}  # noqa: RUF012


class RoleAdmin(_Base, model=Role):
    admin_summary = "Define reusable access roles and their operational purpose."
    column_list = ["id", "name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class PermissionAdmin(_Base, model=Permission):
    admin_summary = "Define permission codes that roles use to authorize actions."
    column_list = ["id", "code", "description"]  # noqa: RUF012
    column_searchable_list = ["code"]  # noqa: RUF012


class RolePermissionAdmin(_Base, model=RolePermission):
    admin_summary = "Assign permission codes to roles."
    column_list = ["role_id", "permission_id"]  # noqa: RUF012
    column_labels = {"role_id": "role", "permission_id": "permission"}  # noqa: RUF012
    column_formatters = {  # noqa: RUF012
        "role_id": lambda m, _a: _display_label(Role, m.role_id, "role"),
        "permission_id": lambda m, _a: _display_label(Permission, m.permission_id, "permission"),
    }


class UserRoleAdmin(_Base, model=UserRole):
    admin_summary = "Assign roles to individual users."
    column_list = ["user_id", "role_id"]  # noqa: RUF012
    column_labels = {"user_id": "user", "role_id": "role"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user, "role_id": lambda m, _a: _display_label(Role, m.role_id, "role")}  # noqa: RUF012


class AuthIdentityAdmin(_Base, model=AuthIdentity):
    admin_summary = "Link local or external provider identities to users."
    column_list = ["id", "provider", "provider_sub", "user_id"]  # noqa: RUF012
    column_labels = {"provider_sub": "external id", "user_id": "user"}  # noqa: RUF012
    column_formatters = {"user_id": _fmt_user}  # noqa: RUF012
    column_searchable_list = ["provider", "provider_sub"]  # noqa: RUF012


class RoutineCategoryAdmin(_Base, model=RoutineCategory):
    admin_summary = "Organize routines and define optional input schemas for their content."
    column_list = ["id", "name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class RoutineAdmin(_Base, model=Routine):
    admin_summary = "Manage versioned routine definitions and their categories."
    column_list = ["id", "name", "version", "category", "is_active", "created_by", "updated_at"]  # noqa: RUF012
    column_labels = {"category": "category", "created_by": "created by"}  # noqa: RUF012
    column_formatters = {"created_by": _fmt_created_by}  # noqa: RUF012
    column_formatters_detail = {"created_by": _fmt_created_by}  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceAdmin(_Base, model=Resource):
    admin_summary = "Manage inventory resources, identifiers, types, data, and active status."
    column_list = ["id", "name", "identifier", "resource_type", "is_active"]  # noqa: RUF012
    column_labels = {"resource_type": "type"}  # noqa: RUF012
    column_searchable_list = ["name", "identifier"]  # noqa: RUF012


class ResourceTypeAdmin(_Base, model=ResourceType):
    admin_summary = "Define resource classes and optional schemas for resource data."
    column_list = ["id", "name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class MetadataTypeAdmin(_Base, model=MetadataType):
    admin_summary = "Define typed metadata records and optional schemas for their data."
    column_list = ["id", "name", "description", "is_active"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceMetadataAdmin(_Base, model=ResourceMetadata):
    admin_summary = "Attach typed metadata entries to resources."
    column_list = ["id", "resource", "metadata_type"]  # noqa: RUF012
    column_labels = {"resource": "resource", "metadata_type": "metadata type"}  # noqa: RUF012


class ResourceRoutineAdmin(_Base, model=ResourceRoutine):
    admin_summary = "Associate routines with resources that are allowed to run them."
    # Composite-PK link table: sqladmin omits PK/FK columns from forms by
    # default, so without relationship form fields the create page has no
    # inputs. The viewonly relations on the model render as selects.
    # Rows are immutable (delete + recreate instead of editing ids).
    can_edit = False
    column_list = ["resource_id", "routine_id"]  # noqa: RUF012
    column_labels = {"resource_id": "resource", "routine_id": "routine"}  # noqa: RUF012
    column_formatters = {"resource_id": _fmt_resource, "routine_id": _fmt_routine}  # noqa: RUF012
    form_columns = ["resource", "routine"]  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        await super().on_model_change(data, model, is_created, request)
        if is_created:
            resource_id = _rel_id(data.get("resource", data.get("resource_id")))
            routine_id = _rel_id(data.get("routine", data.get("routine_id")))
            if resource_id is not None and routine_id is not None:
                with _sync_session_factory()() as session:
                    exists = session.execute(
                        select(ResourceRoutine).where(
                            ResourceRoutine.resource_id == resource_id,
                            ResourceRoutine.routine_id == routine_id,
                        )
                    ).scalar_one_or_none()
                if exists is not None:
                    raise ValueError("This routine is already associated with this resource.")


class ResourceGroupAdmin(_Base, model=ResourceGroup):
    admin_summary = "Organize resources into reusable groups."
    column_list = ["id", "name", "description"]  # noqa: RUF012
    column_searchable_list = ["name"]  # noqa: RUF012


class ResourceGroupMemberAdmin(_Base, model=ResourceGroupMember):
    admin_summary = "Add resources to, or remove them from, resource groups."
    # Same composite-PK treatment as ResourceRoutineAdmin: relationship
    # selects for create, immutable rows (delete + recreate to change).
    can_edit = False
    column_list = ["group_id", "resource_id"]  # noqa: RUF012
    column_labels = {"group_id": "group", "resource_id": "resource"}  # noqa: RUF012
    column_formatters = {"group_id": _fmt_group, "resource_id": _fmt_resource}  # noqa: RUF012
    form_columns = ["group", "resource"]  # noqa: RUF012

    async def on_model_change(self, data: dict[str, Any], model: Any, is_created: bool, request: Request) -> None:
        await super().on_model_change(data, model, is_created, request)
        if is_created:
            group_id = _rel_id(data.get("group", data.get("group_id")))
            resource_id = _rel_id(data.get("resource", data.get("resource_id")))
            if group_id is not None and resource_id is not None:
                with _sync_session_factory()() as session:
                    exists = session.execute(
                        select(ResourceGroupMember).where(
                            ResourceGroupMember.group_id == group_id,
                            ResourceGroupMember.resource_id == resource_id,
                        )
                    ).scalar_one_or_none()
                if exists is not None:
                    raise ValueError("This resource is already a member of this group.")


class GroupAssignmentAdmin(_Base, model=GroupAssignment):
    admin_summary = "Give users or roles access to resource groups."
    column_list = ["id", "group_id", "principal_type", "principal_id", "created_by"]  # noqa: RUF012
    column_labels = {"group_id": "group", "principal_type": "type", "principal_id": "principal", "created_by": "created by"}  # noqa: RUF012
    column_formatters = {"group_id": _fmt_group, "principal_id": _fmt_principal, "created_by": _fmt_created_by}  # noqa: RUF012
    column_formatters_detail = {"group_id": _fmt_group, "principal_id": _fmt_principal, "created_by": _fmt_created_by}  # noqa: RUF012


class RoutineGrantAdmin(_Base, model=RoutineGrant):
    admin_summary = "Grant selected principals permission to view or use specific routines."
    column_list = ["id", "routine_id", "principal_type", "principal_id", "can_view", "can_use"]  # noqa: RUF012
    column_labels = {"routine_id": "routine", "principal_type": "type", "principal_id": "principal"}  # noqa: RUF012
    column_formatters = {"routine_id": _fmt_routine, "principal_id": _fmt_principal}  # noqa: RUF012
    column_formatters_detail = {"routine_id": _fmt_routine, "principal_id": _fmt_principal}  # noqa: RUF012


class ResourceGrantAdmin(_Base, model=ResourceGrant):
    admin_summary = "Grant selected principals permission to view or use a resource or group."
    column_list = ["id", "resource_id", "group_id", "principal_type", "principal_id", "can_view", "can_use"]  # noqa: RUF012
    column_labels = {"resource_id": "resource", "group_id": "group", "principal_type": "type", "principal_id": "principal"}  # noqa: RUF012
    column_formatters = {"resource_id": _fmt_resource, "group_id": _fmt_group, "principal_id": _fmt_principal}  # noqa: RUF012
    column_formatters_detail = {"resource_id": _fmt_resource, "group_id": _fmt_group, "principal_id": _fmt_principal}  # noqa: RUF012


class ExecutionModeAdmin(_Base, model=ExecutionMode):
    admin_summary = "Define dispatch modes such as direct, scheduler, or voucher."
    column_list = ["id", "code", "description"]  # noqa: RUF012
    column_searchable_list = ["code"]  # noqa: RUF012


class RoutineUsageAdmin(_Base, model=RoutineUsage):
    admin_summary = "Review routine dispatch requests, their targets, mode, status, and schedule."
    column_list = ["id", "routine_id", "resource_id", "requested_by", "mode_id", "status", "external_dispatch_id", "cron", "use_count", "created_at"]  # noqa: RUF012
    column_labels = {"routine_id": "routine", "resource_id": "resource", "requested_by": "requested by", "mode_id": "mode", "external_dispatch_id": "dispatch id", "use_count": "uses"}  # noqa: RUF012
    column_formatters = {"routine_id": _fmt_routine, "resource_id": _fmt_resource, "requested_by": _fmt_requested_by, "mode_id": _fmt_mode}  # noqa: RUF012
    column_formatters_detail = {"routine_id": _fmt_routine, "resource_id": _fmt_resource, "requested_by": _fmt_requested_by, "mode_id": _fmt_mode}  # noqa: RUF012


class DocsLinkView(BaseView):
    name = "API Docs"
    icon = "fa-solid fa-book"

    @expose("/docs-link", methods=["GET"])
    async def docs_link(self, request: Request):
        from starlette.responses import RedirectResponse

        return RedirectResponse(url="/docs")


class ResourceImportView(BaseView):
    """Admin-only CSV import for resources + monitor metadata.

    Uses the same shared importer as the REST endpoints, so validation,
    atomic upsert, and audit behavior are identical. Reachable from the
    admin navigation; session auth is enforced by ``AdminAuth``.
    """

    name = "Import Resources"
    icon = "fa-solid fa-upload"

    @expose("/resource-import", methods=["GET", "POST"])
    async def resource_import(self, request: Request):
        import html

        from fastapi import HTTPException
        from starlette.responses import HTMLResponse

        from app.db.session import get_session_factory
        from app.services.resource_import import import_rows, parse_csv_text

        message = ""
        if request.method == "POST":
            form = await request.form()
            upload = form.get("file")
            data = b""
            if upload is not None and hasattr(upload, "read"):
                data = await upload.read()
            try:
                if not data:
                    raise HTTPException(status_code=422, detail="csv: no file uploaded")
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError as e:
                    raise HTTPException(
                        status_code=422, detail="csv: file must be UTF-8"
                    ) from e
                rows = parse_csv_text(text, source="csv")
                user_id = request.session.get("user_id")
                ip = request.client.host if request.client else None
                async with get_session_factory()() as session:
                    result = await import_rows(
                        session, rows, source="csv", user_id=user_id, ip=ip
                    )
                message = (
                    f"<p><strong>Imported {result['total']} rows: "
                    f"{result['created']} created, {result['updated']} updated.</strong><br>"
                    f"Identifiers: {html.escape(', '.join(result['identifiers']))}</p>"
                )
            except HTTPException as e:
                message = f"<p><strong>Import failed:</strong> {html.escape(str(e.detail))}</p>"

        body = f"""<!doctype html><html><head><title>Import Resources</title></head>
<body style="font-family:sans-serif;max-width:720px;margin:2rem auto">
<h1>Import Resources (CSV, admin only)</h1>
<p>Upload the monitor/device CSV. Every row is validated against the
<em>mobile_device</em> and <em>monitor</em> schemas; any invalid row rolls back
the whole file. Existing <em>device_id</em> values are updated.</p>
{message}
<form method="post" enctype="multipart/form-data">
<input type="file" name="file" accept=".csv,text/csv" required>
<button type="submit">Import</button>
</form>
<p>Required headers:<br><code>monitor_id,nodo_id,nombre,descripcion,hostname,
replic_dbhost,servidor_log,id,device_id,device_nombre,activo,
device_descripcion,device_ultima_actualizacion,platform,platform_version,
fecha_ultima_replicacion</code></p>
<p><a href="/admin/">Back to admin</a></p>
</body></html>"""
        return HTMLResponse(body)


_VIEWS = [
    UserAdmin, RoleAdmin, PermissionAdmin, RolePermissionAdmin, UserRoleAdmin,
    AuthIdentityAdmin, RoutineCategoryAdmin, RoutineAdmin, ResourceTypeAdmin,
    MetadataTypeAdmin, ResourceMetadataAdmin, ResourceRoutineAdmin, ResourceAdmin,
    ResourceGroupAdmin,
    ResourceGroupMemberAdmin, GroupAssignmentAdmin, RoutineGrantAdmin,
    ResourceGrantAdmin, ExecutionModeAdmin, RoutineUsageAdmin,
    ProcessorAdmin, ExecutionResultAdmin, ActivityLogAdmin,
]


def setup_admin(app: FastAPI) -> None:
    """Create sync engine for the admin + mount sqladmin at /admin."""
    from pathlib import Path

    url = get_settings().DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    templates_dir = str(Path(__file__).resolve().parents[2] / "templates")
    admin = Admin(
        app,
        engine,
        authentication_backend=AdminAuth(secret_key=get_settings().JWT_SECRET),
        templates_dir=templates_dir,
    )
    for view in _VIEWS:
        admin.add_view(view)
    admin.add_view(DocsLinkView)
    admin.add_view(ResourceImportView)
