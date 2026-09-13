"""Stage 3 tests: object grants gate template/resource reads; admin manages grants."""
from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def _ids(client, headers):
    users = (await client.get("/api/v1/users", headers=headers)).json()
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    return (
        next(u["id"] for u in users if u["username"] == "operator"),
        next(r["id"] for r in roles if r["name"] == "operator"),
    )


async def test_seed_grants_operator_hello_and_moto(client):
    op = await _operator(client)
    templates = (await client.get("/api/v1/templates", headers=op)).json()
    assert any(t["name"] == "hello.py" for t in templates)
    hello = next(t for t in templates if t["name"] == "hello.py")
    assert (await client.get(f"/api/v1/templates/{hello['id']}", headers=op)).status_code == 200
    fetch = await client.get(f"/api/v1/templates/{hello['id']}/fetch", headers=op)
    assert fetch.status_code == 200 and "hello from template" in fetch.json()["content"]
    resources = (await client.get("/api/v1/resources", headers=op)).json()
    moto = next(r for r in resources if r["identifier"] == "ZY323S5GHW")
    assert (await client.get(f"/api/v1/resources/{moto['id']}", headers=op)).status_code == 200


async def test_ungranted_template_denied_then_direct_grant_allows(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates",
            headers=admin,
            json={"name": "secret.py", "category_id": 1, "content": "top secret"},
        )
    ).json()
    # filtered from list, 403 on detail + fetch (operator HAS template:view/use codes)
    assert all(t["id"] != tpl["id"] for t in (await client.get("/api/v1/templates", headers=op)).json())
    assert (await client.get(f"/api/v1/templates/{tpl['id']}", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 403
    # view-only direct user grant: GET ok, fetch still 403
    operator_id, _ = await _ids(client, admin)
    g = (
        await client.post(
            "/api/v1/grants/templates",
            headers=admin,
            json={"template_id": tpl["id"], "principal_type": "user",
                  "principal_id": operator_id, "can_view": True, "can_use": False},
        )
    ).json()
    assert (await client.get(f"/api/v1/templates/{tpl['id']}", headers=op)).status_code == 200
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 403
    # use-only grant implies view
    await client.delete(f"/api/v1/grants/templates/{g['id']}", headers=admin)
    await client.post(
        "/api/v1/grants/templates",
        headers=admin,
        json={"template_id": tpl["id"], "principal_type": "user",
              "principal_id": operator_id, "can_view": False, "can_use": True},
    )
    assert (await client.get(f"/api/v1/templates/{tpl['id']}", headers=op)).status_code == 200
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 200
    # deleting the grant revokes access again
    grants = (await client.get("/api/v1/grants/templates", headers=admin)).json()
    gid = next(x["id"] for x in grants if x["template_id"] == tpl["id"])
    await client.delete(f"/api/v1/grants/templates/{gid}", headers=admin)
    assert (await client.get(f"/api/v1/templates/{tpl['id']}", headers=op)).status_code == 403


async def test_ungranted_resource_denied_then_direct_grant_allows(client):
    admin, op = await _admin(client), await _operator(client)
    r = (
        await client.post(
            "/api/v1/resources", headers=admin, json={"name": "Vault", "identifier": "VAULT-1"}
        )
    ).json()
    assert all(x["id"] != r["id"] for x in (await client.get("/api/v1/resources", headers=op)).json())
    assert (await client.get(f"/api/v1/resources/{r['id']}", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/resources/{r['id']}/metadata", headers=op)).status_code == 403
    operator_id, _ = await _ids(client, admin)
    await client.post(
        "/api/v1/grants/resources",
        headers=admin,
        json={"resource_id": r["id"], "principal_type": "user",
              "principal_id": operator_id, "can_view": True, "can_use": True},
    )
    assert (await client.get(f"/api/v1/resources/{r['id']}", headers=op)).status_code == 200


async def test_grant_management_guards(client):
    admin, op = await _admin(client), await _operator(client)
    _, operator_role = await _ids(client, admin)
    hello = next(
        t for t in (await client.get("/api/v1/templates", headers=admin)).json() if t["name"] == "hello.py"
    )
    # operator cannot manage grants
    assert (
        await client.post(
            "/api/v1/grants/templates", headers=op,
            json={"template_id": hello["id"], "principal_type": "role",
                  "principal_id": operator_role, "can_view": True},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/grants/templates", headers=op)).status_code == 403
    # duplicate seed grant -> 409; unknown principal -> 404; bad target -> 422
    dup = await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": hello["id"], "principal_type": "role",
              "principal_id": operator_role, "can_view": True},
    )
    assert dup.status_code == 409
    assert (
        await client.post(
            "/api/v1/grants/templates", headers=admin,
            json={"template_id": hello["id"], "principal_type": "user",
                  "principal_id": 9999, "can_view": True},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/grants/resources", headers=admin,
            json={"principal_type": "role", "principal_id": operator_role, "can_view": True},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/grants/resources", headers=admin,
            json={"resource_id": 1, "group_id": 1, "principal_type": "role",
                  "principal_id": operator_role, "can_view": True},
        )
    ).status_code == 422
    assert (await client.delete("/api/v1/grants/templates/9999", headers=admin)).status_code == 404


async def test_superuser_bypass_and_missing_objects(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates",
            headers=admin,
            json={"name": "hidden.py", "category_id": 1, "content": "x"},
        )
    ).json()
    # superuser sees everything without grants
    assert any(t["id"] == tpl["id"] for t in (await client.get("/api/v1/templates", headers=admin)).json())
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=admin)).status_code == 200
    # 404 still wins over 403 for missing objects
    assert (await client.get("/api/v1/templates/9999", headers=op)).status_code == 404
    assert (await client.get("/api/v1/resources/9999", headers=op)).status_code == 404
