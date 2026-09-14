"""FastAPI application factory (Stage 8: all routers + /admin wired)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.core.config import get_settings
from app.core.logging import RequestIDMiddleware, setup_logging
from app.db.session import dispose_engine, init_db


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    env: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    await init_db()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        description="Template Management PoC — retrieve/maintain/categorize templates; execution is out-of-scope (see plan.md).",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=settings.JWT_SECRET)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", app=settings.APP_NAME, version=__version__, env=settings.ENV)

    @app.get("/version", tags=["system"])
    async def version() -> dict[str, str]:
        return {"app": settings.APP_NAME, "version": __version__}

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {"app": settings.APP_NAME, "docs": "/docs", "health": "/health", "plan": "see plan.md Stage 7"}

    from app.api.v1 import auth as auth_router
    from app.api.v1 import beacons as beacons_router
    from app.api.v1 import categories as categories_router
    from app.api.v1 import grants as grants_router
    from app.api.v1 import groups as groups_router
    from app.api.v1 import limits as limits_router
    from app.api.v1 import logs as logs_router
    from app.api.v1 import metadata_types as metadata_types_router
    from app.api.v1 import modes as modes_router
    from app.api.v1 import processors as processors_router
    from app.api.v1 import resource_types as resource_types_router
    from app.api.v1 import resources as resources_router
    from app.api.v1 import roles as roles_router
    from app.api.v1 import templates as templates_router
    from app.api.v1 import usages as usages_router
    from app.api.v1 import users as users_router

    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users_router.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(roles_router.router, prefix="/api/v1/roles", tags=["roles"])
    app.include_router(categories_router.router, prefix="/api/v1/categories", tags=["categories"])
    app.include_router(templates_router.router, prefix="/api/v1/templates", tags=["templates"])
    app.include_router(resources_router.router, prefix="/api/v1/resources", tags=["resources"])
    app.include_router(
        resource_types_router.router, prefix="/api/v1/resource-types", tags=["resource-types"]
    )
    app.include_router(
        metadata_types_router.router, prefix="/api/v1/metadata-types", tags=["metadata-types"]
    )
    app.include_router(groups_router.router, prefix="/api/v1/resource-groups", tags=["groups"])
    app.include_router(grants_router.router, prefix="/api/v1/grants", tags=["grants"])
    app.include_router(modes_router.router, prefix="/api/v1/execution-modes", tags=["modes"])
    app.include_router(usages_router.router, prefix="/api/v1/usages", tags=["usages"])
    app.include_router(limits_router.router, prefix="/api/v1/usage-limits", tags=["limits"])
    app.include_router(processors_router.router, prefix="/api/v1/processors", tags=["processors"])
    app.include_router(beacons_router.router, prefix="/api/v1/beacons", tags=["beacons"])
    app.include_router(logs_router.router, prefix="/api/v1/activity-logs", tags=["activity"])

    from app.admin.views import setup_admin

    setup_admin(app)
    return app


app = create_app()
