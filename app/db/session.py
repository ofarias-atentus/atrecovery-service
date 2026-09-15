"""Async engine/session helpers + init_db (Stage 0).

- SQLite via aiosqlite. data/ dir auto-created.
- get_db: FastAPI dependency yielding AsyncSession.
- init_db: create_all for registered models (Alembic optional, later).
"""
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base

# Import models package so tables register once defined (Stages 1+).
# Must stay tolerant when models/__init__ is still empty (Stage 0).
try:
    import app.models  # noqa: F401
except ImportError:  # pragma: no cover - only during early bootstrap
    pass

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.DATABASE_URL
        if url.startswith("sqlite+aiosqlite:///"):
            path = url.replace("sqlite+aiosqlite:///", "")
            # Handle ./data/app.db relative paths
            db_file = Path(path)
            if str(db_file.parent) not in ("", "."):
                db_file.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if "sqlite" in url else {}
        _engine = create_async_engine(url, echo=False, connect_args=connect_args, future=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
