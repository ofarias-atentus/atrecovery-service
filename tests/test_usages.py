"""Stage 4 tests: modes, usage CRUD per mode, voucher flow, grant gates, limits."""
from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def _hello(client, headers):
    tpls = (await client.get("/api/v1/templates", headers=headers)).json()
    return next(t for t in tpls if t["name"] == "hello.py")


async def _moto(client, headers):
    res = (await client.get("/api/v1/resources", headers=headers)).json()
    return next(r for r in res if r["identifier"] == "ZY323S5GHW")


async def _operator_id(client, admin_headers):
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()
    return next(u["id"] for u in users if u["username"] == "operator")


async def test_modes_seeded_and_guarded(client):
    admin, op = await _admin(client), await _operator(client)
    codes = {m["code"] for m in (await client.get("/api/v1/execution-modes", headers=op)).json()}
    assert {"direct", "scheduler", "voucher"} <= codes
    assert (
        await client.post("/api/v1/execution-modes", headers=op, json={"code": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/execution-modes", headers=admin, json={"code": "batch"})
    ).status_code == 201
    assert (
        await client.post("/api/v1/execution-modes", headers=admin, json={"code": "batch"})
    ).status_code == 409


async def test_direct_usage_roundtrip(client):
    op = await _operator(client)
    hello = await _hello(client, op)
    u = (
        await client.post(
            "/api/v1/usages", headers=op, json={"template_id": hello["id"], "mode": "direct"}
        )
    ).json()
    assert u["status"] == "dispatched" and u["use_count"] == 1
    assert u["external_dispatch_id"] is None and u["mode"] == "direct"
    assert (await client.get(f"/api/v1/usages/{u['id']}", headers=op)).status_code == 200
    st = (await client.get(f"/api/v1/usages/{u['id']}/status", headers=op)).json()
    assert st["status"] == "dispatched" and st["external_dispatch_id"] is None


async def test_scheduler_requires_schedule_at(client):
    op = await _operator(client)
    hello = await _hello(client, op)
    assert (
        await client.post(
            "/api/v1/usages", headers=op, json={"template_id": hello["id"], "mode": "scheduler"}
        )
    ).status_code == 422
    u = (
        await client.post(
            "/api/v1/usages",
            headers=op,
            json={"template_id": hello["id"], "mode": "scheduler",
                  "schedule_at": "2030-01-01T00:00:00", "payload": {"name": "ops"}},
        )
    ).json()
    assert u["status"] == "pending" and u["payload"] == {"name": "ops"}
    assert u["schedule_at"].startswith("2030-01-01")


async def test_voucher_flow_returns_dispatch_id(client):
    op = await _operator(client)
    hello, moto = await _hello(client, op), await _moto(client, op)
    u = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "voucher"},
        )
    ).json()
    assert u["status"] == "pending"
    assert u["external_dispatch_id"].startswith("V-")
    st = (await client.get(f"/api/v1/usages/{u['id']}/status", headers=op)).json()
    assert st["external_dispatch_id"] == u["external_dispatch_id"] and st["mode"] == "voucher"


async def test_usage_grant_and_input_gates(client):
    admin, op = await _admin(client), await _operator(client)
    hello = await _hello(client, op)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "nog.py", "category_id": 1, "content": "x"},
        )
    ).json()
    assert (
        await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"]})
    ).status_code == 403
    res = (
        await client.post(
            "/api/v1/resources", headers=admin, json={"name": "Vault", "identifier": "VAULT-9"}
        )
    ).json()
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": res["id"]},
        )
    ).status_code == 403
    assert (
        await client.post("/api/v1/usages", headers=op, json={"template_id": hello["id"], "mode": "nope"})
    ).status_code == 422
    assert (
        await client.post("/api/v1/usages", headers=op, json={"template_id": 9999})
    ).status_code == 404
    assert (await client.get("/api/v1/usages/9999", headers=op)).status_code == 404


async def test_global_total_limit_blocks_usage_and_fetch(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "limited.py", "category_id": 1, "content": "x"},
        )
    ).json()
    opid = await _operator_id(client, admin)
    await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": tpl["id"], "principal_type": "user", "principal_id": opid,
              "can_view": True, "can_use": True},
    )
    lim = (
        await client.post(
            "/api/v1/usage-limits", headers=admin,
            json={"template_id": tpl["id"], "scope_type": "global", "max_uses": 1, "window": "total"},
        )
    ).json()
    assert (
        await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"]})
    ).status_code == 201
    blocked = await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"]})
    assert blocked.status_code == 429
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 429
    await client.delete(f"/api/v1/usage-limits/{lim['id']}", headers=admin)
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 200


async def test_user_scoped_limit_counts_only_that_user(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "scoped.py", "category_id": 1, "content": "x"},
        )
    ).json()
    opid = await _operator_id(client, admin)
    await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": tpl["id"], "principal_type": "user", "principal_id": opid,
              "can_view": True, "can_use": True},
    )
    await client.post(
        "/api/v1/usage-limits", headers=admin,
        json={"template_id": tpl["id"], "scope_type": "user", "scope_id": opid,
              "max_uses": 1, "window": "total"},
    )
    # admin (different user) is unaffected and does not consume the quota
    assert (await client.post("/api/v1/usages", headers=admin, json={"template_id": tpl["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=admin, json={"template_id": tpl["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"]})).status_code == 429


async def test_usage_visibility_scoped_to_owner(client):
    admin, op = await _admin(client), await _operator(client)
    hello = await _hello(client, op)
    mine = (
        await client.post("/api/v1/usages", headers=op, json={"template_id": hello["id"]})
    ).json()
    theirs = (
        await client.post("/api/v1/usages", headers=admin, json={"template_id": hello["id"]})
    ).json()
    listed = (await client.get("/api/v1/usages", headers=op)).json()
    assert {u["id"] for u in listed} == {mine["id"]}
    assert (await client.get(f"/api/v1/usages/{theirs['id']}", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/usages/{theirs['id']}/status", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/usages/{mine['id']}", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/usages", headers=op)).status_code == 200
    assert (await client.get("/api/v1/usages")).status_code == 401


async def test_limits_admin_only_and_validated(client):
    admin, op = await _admin(client), await _operator(client)
    hello = await _hello(client, op)
    assert (
        await client.post(
            "/api/v1/usage-limits", headers=op,
            json={"template_id": hello["id"], "scope_type": "global", "max_uses": 1},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/usage-limits", headers=op)).status_code == 403
    # global takes no scope_id; non-global requires one; unknown refs 404
    bad_global = await client.post(
        "/api/v1/usage-limits", headers=admin,
        json={"template_id": hello["id"], "scope_type": "global", "scope_id": 1, "max_uses": 1},
    )
    assert bad_global.status_code == 422
    missing_scope = await client.post(
        "/api/v1/usage-limits", headers=admin,
        json={"template_id": hello["id"], "scope_type": "user", "max_uses": 1},
    )
    assert missing_scope.status_code == 422
    assert (
        await client.post(
            "/api/v1/usage-limits", headers=admin,
            json={"template_id": 9999, "scope_type": "global", "max_uses": 1},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/usage-limits", headers=admin,
            json={"template_id": hello["id"], "scope_type": "user", "scope_id": 9999, "max_uses": 1},
        )
    ).status_code == 404
    assert (await client.delete("/api/v1/usage-limits/9999", headers=admin)).status_code == 404
