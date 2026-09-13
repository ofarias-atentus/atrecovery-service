import httpx
import pytest

from app.db.session import dispose_engine, init_db
from app.main import create_app


@pytest.fixture
async def app():
    application = create_app()
    return application


@pytest.fixture
async def client(app):
    # Use ASGI transport; lifespan (init_db) runs explicitly for test isolation.
    await init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await dispose_engine()
