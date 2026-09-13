"""Stage 8 tests: /admin login guard, dashboard access, read-only audit views."""
from tests.conftest import login


async def test_login_page_public_but_data_guarded(client):
    assert (await client.get("/admin/login")).status_code == 200
    anon_list = await client.get("/admin/user/list")
    assert anon_list.status_code in (302, 303)  # bounced to login
    assert "/admin/login" in anon_list.headers.get("location", "")
    followed = await client.get("/admin/user/list", follow_redirects=True)
    assert b"password" in followed.content  # login form, not data
    assert b"admin@example.com" not in followed.content


async def test_admin_login_grants_dashboard_and_lists(client):
    r = await client.post(
        "/admin/login", data={"username": "admin", "password": "admin123"}
    )
    assert r.status_code in (302, 303), r.text
    dashboard = await client.get("/admin/")
    assert dashboard.status_code == 200
    users = await client.get("/admin/user/list")
    assert users.status_code == 200 and b"admin" in users.content
    assert b"pbkdf2" not in users.content and b"bcrypt" not in users.content.lower()


async def test_operator_login_rejected(client):
    await login(client, "operator", "operator123")  # API login works
    r = await client.post(
        "/admin/login", data={"username": "operator", "password": "operator123"}
    )
    assert r.status_code == 400
    # no session was minted: still bounced to login, not data
    anon = await client.get("/admin/user/list", follow_redirects=True)
    assert b"password" in anon.content and b"admin@example.com" not in anon.content


async def test_audit_views_read_only(client):
    await client.post("/admin/login", data={"username": "admin", "password": "admin123"})
    for path in ("/admin/activity-log/create", "/admin/execution-result/create"):
        r = await client.get(path)
        assert r.status_code in (403, 404, 405), (path, r.status_code)
    assert (await client.get("/admin/activity-log/list")).status_code == 200
