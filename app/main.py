"""FastAPI application factory (Stage 1: identity/auth/RBAC wired).

Later stages mount catalog/resource/usage/beacon/stats routers and /admin here.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
        return {"app": settings.APP_NAME, "docs": "/docs", "health": "/health", "plan": "see plan.md Stage 1"}

    from app.api.v1 import auth as auth_router
    from app.api.v1 import roles as roles_router
    from app.api.v1 import users as users_router

    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(users_router.router, prefix="/api/v1/users", tags=["users"])
    app.include_router(roles_router.router, prefix="/api/v1/roles", tags=["roles"])
    # Stage 2+: categories/templates/resources/groups/grants routers
    # Stage 8: mount sqladmin Admin here.
    return app


app = create_app()
