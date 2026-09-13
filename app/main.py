"""FastAPI application factory (Stage 0).

Later stages mount /api/v1 routers and /admin here.
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
        return {"app": settings.APP_NAME, "docs": "/docs", "health": "/health", "plan": "see plan.md Stage 0"}

    # Stage 1+: app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"]) etc.
    # Stage 8: mount sqladmin Admin here.
    return app


app = create_app()
