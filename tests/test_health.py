"""Stage 0 smoke tests: health, version, root, docs."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "X-Request-ID" in r.headers


@pytest.mark.asyncio
async def test_version_and_root(client):
    assert (await client.get("/version")).status_code == 200
    assert (await client.get("/")).status_code == 200


@pytest.mark.asyncio
async def test_openapi_available(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"]
