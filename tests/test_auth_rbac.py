"""Stage 1 tests: login, refresh, /me, RBAC allow/deny matrix."""
from tests.conftest import auth_headers, login


async def test_admin_and_operator_login(client):
    admin = await login(client, "admin", "admin123")
    assert admin["token_type"] == "bearer" and admin["access_token"] and admin["refresh_token"]
    operator = await login(client, "operator", "operator123")
    assert operator["access_token"]


async def test_wrong_password_rejected(client):
    r = await client.post("/api/v1/auth/token", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401


async def test_refresh_flow(client):
    tokens = await login(client, "admin", "admin123")
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200, r.text
    new_access = r.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=auth_headers(new_access))
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


async def test_refresh_with_access_token_rejected(client):
    tokens = await login(client, "admin", "admin123")
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


async def test_me_returns_roles_and_permissions(client):
    tokens = await login(client, "operator", "operator123")
    me = (await client.get("/api/v1/auth/me", headers=auth_headers(tokens["access_token"]))).json()
    assert me["username"] == "operator"
    assert "operator" in me["roles"]
    assert "routine:use" in me["permissions"]
    assert "users:manage" not in me["permissions"]


async def test_unauthenticated_denied(client):
    assert (await client.get("/api/v1/users")).status_code == 401
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_operator_forbidden_on_admin_endpoints(client):
    op = await login(client, "operator", "operator123")
    h = auth_headers(op["access_token"])
    assert (await client.get("/api/v1/users", headers=h)).status_code == 403
    r = await client.post(
        "/api/v1/users",
        headers=h,
        json={"username": "x", "email": "x@example.com", "password": "xxxx1234"},
    )
    assert r.status_code == 403
    assert (await client.post("/api/v1/roles", headers=h, json={"name": "x"})).status_code == 403


async def test_admin_can_list_users_and_roles(client):
    admin = await login(client, "admin", "admin123")
    h = auth_headers(admin["access_token"])
    users = (await client.get("/api/v1/users", headers=h)).json()
    assert {u["username"] for u in users} >= {"admin", "operator"}
    roles = (await client.get("/api/v1/roles", headers=h)).json()
    assert {r["name"] for r in roles} >= {"admin", "operator"}
    perms = (await client.get("/api/v1/roles/permissions", headers=h)).json()
    assert "users:manage" in [p["code"] for p in perms]


async def test_admin_create_assign_login_new_user(client):
    admin = await login(client, "admin", "admin123")
    h = auth_headers(admin["access_token"])
    r = await client.post(
        "/api/v1/users",
        headers=h,
        json={
            "username": "op2",
            "email": "op2@example.com",
            "password": "op212345",
            "role_names": ["operator"],
        },
    )
    assert r.status_code == 201, r.text
    assert "operator" in r.json()["roles"]
    tokens = await login(client, "op2", "op212345")
    me = (await client.get("/api/v1/auth/me", headers=auth_headers(tokens["access_token"]))).json()
    assert "routine:use" in me["permissions"]


async def test_provider_callback_stub(client):
    r = await client.get("/api/v1/auth/business_sso/callback")
    assert r.status_code == 501
    r = await client.get("/api/v1/auth/nope/callback")
    assert r.status_code == 404
