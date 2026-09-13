import os
from collections.abc import AsyncGenerator

import httpx
import pytest

from app.core.config import get_settings
from app.db.seed import seed_all
from app.db.session import dispose_engine, get_session_factory, init_db


@pytest.fixture
async def client(tmp_path, monkeypatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Isolated app client: temp SQLite file + seed, so tests never touch ./data/app.db."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()
    # Late import so the app reads the patched settings
    from app.main import create_app

    app = create_app()
    await init_db()
    async with get_session_factory()() as session:
        await seed_all(session)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
    get_settings.cache_clear()
    assert os.environ.get("DATABASE_URL", "").startswith("sqlite")  # sanity, no-op


async def login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    r = await client.post(
        "/api/v1/auth/token", data={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
