"""sqladmin views + auth guard (Stage 8).

Mounted at ``/admin`` via ``setup_admin(app)``. Auth: local username/password
login; only active superusers or holders of ``admin:manage`` get a session.
``ActivityLog`` and ``ExecutionResult`` are read-only; credential hashes are
excluded from list/detail/forms everywhere.
"""
from __future__ import annotations

from fastapi import FastAPI
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.config import get_settings
from app.core.security import verify_password
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


class UserAdmin(_Base, model=User):
    column_exclude_list = ["hashed_password"]  # noqa: RUF012
    column_details_exclude_list = ["hashed_password"]  # noqa: RUF012
    form_excluded_columns = ["hashed_password"]  # noqa: RUF012


class ProcessorAdmin(_Base, model=ProcessorService):
    column_exclude_list = ["token_hash"]  # noqa: RUF012
    column_details_exclude_list = ["token_hash"]  # noqa: RUF012
    form_excluded_columns = ["token_hash"]  # noqa: RUF012


class ActivityLogAdmin(_Base, model=ActivityLog):
    can_create = False
    can_edit = False
    can_delete = False


class ExecutionResultAdmin(_Base, model=ExecutionResult):
    can_create = False
    can_edit = False
    can_delete = False


class RoleAdmin(_Base, model=Role):
    pass


class PermissionAdmin(_Base, model=Permission):
    pass


class RolePermissionAdmin(_Base, model=RolePermission):
    pass


class UserRoleAdmin(_Base, model=UserRole):
    pass


class AuthIdentityAdmin(_Base, model=AuthIdentity):
    pass


class TemplateCategoryAdmin(_Base, model=TemplateCategory):
    pass


class TemplateAdmin(_Base, model=Template):
    pass


class ResourceAdmin(_Base, model=Resource):
    pass


class ResourceTypeAdmin(_Base, model=ResourceType):
    pass


class MetadataTypeAdmin(_Base, model=MetadataType):
    pass


class ResourceMetadataAdmin(_Base, model=ResourceMetadata):
    pass


class ResourceGroupAdmin(_Base, model=ResourceGroup):
    pass


class ResourceGroupMemberAdmin(_Base, model=ResourceGroupMember):
    pass


class GroupAssignmentAdmin(_Base, model=GroupAssignment):
    pass


class TemplateGrantAdmin(_Base, model=TemplateGrant):
    pass


class ResourceGrantAdmin(_Base, model=ResourceGrant):
    pass


class ExecutionModeAdmin(_Base, model=ExecutionMode):
    pass


class TemplateUsageAdmin(_Base, model=TemplateUsage):
    pass


class UsageLimitAdmin(_Base, model=UsageLimit):
    pass


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
    MetadataTypeAdmin, ResourceMetadataAdmin, ResourceAdmin, ResourceGroupAdmin,
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
