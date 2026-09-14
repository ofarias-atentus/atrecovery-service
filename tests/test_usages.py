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


async def _link(client, admin_headers, resource_id, template_id):
    """Associate template↔resource (admin) + assert 201; helper for usage tests."""
    r = await client.post(
        f"/api/v1/resources/{resource_id}/templates", headers=admin_headers,
        json={"template_id": template_id},
    )
    assert r.status_code == 201, r.text


async def _grant_resource(client, admin_headers, resource_id, principal_type, principal_id):
    r = await client.post(
        "/api/v1/grants/resources", headers=admin_headers,
        json={"resource_id": resource_id, "principal_type": principal_type,
              "principal_id": principal_id, "can_view": True, "can_use": True},
    )
    assert r.status_code == 201, r.text


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
    hello, moto = await _hello(client, op), await _moto(client, op)
    u = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "direct"},
        )
    ).json()
    assert u["status"] == "dispatched" and u["use_count"] == 1
    assert u["external_dispatch_id"] is None and u["mode"] == "direct"
    assert (await client.get(f"/api/v1/usages/{u['id']}", headers=op)).status_code == 200
    st = (await client.get(f"/api/v1/usages/{u['id']}/status", headers=op)).json()
    assert st["status"] == "dispatched" and st["external_dispatch_id"] is None


async def test_scheduler_requires_valid_cron(client):
    op = await _operator(client)
    hello, moto = await _hello(client, op), await _moto(client, op)
    # neither cron nor anything else to schedule on → 422
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "scheduler"},
        )
    ).status_code == 422
    # malformed cron → 422
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"],
                  "mode": "scheduler", "cron": "not a cron"},
        )
    ).status_code == 422
    # cron on a non-scheduler mode → 422
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"],
                  "mode": "direct", "cron": "*/15 * * * *"},
        )
    ).status_code == 422
    u = (
        await client.post(
            "/api/v1/usages",
            headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "scheduler",
                  "cron": "*/15 * * * *", "payload": {"name": "ops"}},
        )
    ).json()
    assert u["status"] == "pending" and u["payload"] == {"name": "ops"}
    assert u["cron"] == "*/15 * * * *"
    assert u["next_fire_at"] is not None
    from datetime import UTC, datetime
    assert datetime.fromisoformat(u["next_fire_at"]) > datetime.now(UTC).replace(tzinfo=None)
    st = (await client.get(f"/api/v1/usages/{u['id']}/status", headers=op)).json()
    assert st["cron"] == "*/15 * * * *" and st["next_fire_at"] == u["next_fire_at"]


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
    hello, moto = await _hello(client, op), await _moto(client, op)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "nog.py", "category_id": 1, "content": {"source": "x"}},
        )
    ).json()
    # ungranted template (grant check precedes association): 403
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": tpl["id"], "resource_id": moto["id"]},
        )
    ).status_code == 403
    # missing resource entirely: 422, templates never execute standalone
    assert (
        await client.post("/api/v1/usages", headers=op, json={"template_id": hello["id"]})
    ).status_code == 422
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
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"], "mode": "nope"},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": 9999, "resource_id": moto["id"]},
        )
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": 9999},
        )
    ).status_code == 404
    assert (await client.get("/api/v1/usages/9999", headers=op)).status_code == 404


async def test_global_total_limit_blocks_usage_and_fetch(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "limited.py", "category_id": 1, "content": {"source": "x"}},
        )
    ).json()
    opid = await _operator_id(client, admin)
    await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": tpl["id"], "principal_type": "user", "principal_id": opid,
              "can_view": True, "can_use": True},
    )
    res = (
        await client.post(
            "/api/v1/resources", headers=admin, json={"name": "Lim", "identifier": "LIM-1"}
        )
    ).json()
    await _grant_resource(client, admin, res["id"], "user", opid)
    await _link(client, admin, res["id"], tpl["id"])
    lim = (
        await client.post(
            "/api/v1/usage-limits", headers=admin,
            json={"template_id": tpl["id"], "scope_type": "global", "max_uses": 1, "window": "total"},
        )
    ).json()
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": tpl["id"], "resource_id": res["id"]},
        )
    ).status_code == 201
    blocked = await client.post(
        "/api/v1/usages", headers=op,
        json={"template_id": tpl["id"], "resource_id": res["id"]},
    )
    assert blocked.status_code == 429
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 429
    await client.delete(f"/api/v1/usage-limits/{lim['id']}", headers=admin)
    assert (await client.get(f"/api/v1/templates/{tpl['id']}/fetch", headers=op)).status_code == 200


async def test_user_scoped_limit_counts_only_that_user(client):
    admin, op = await _admin(client), await _operator(client)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "scoped.py", "category_id": 1, "content": {"source": "x"}},
        )
    ).json()
    opid = await _operator_id(client, admin)
    await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": tpl["id"], "principal_type": "user", "principal_id": opid,
              "can_view": True, "can_use": True},
    )
    res = (
        await client.post(
            "/api/v1/resources", headers=admin, json={"name": "Scoped", "identifier": "SCOPED-1"}
        )
    ).json()
    await _grant_resource(client, admin, res["id"], "user", opid)
    await _link(client, admin, res["id"], tpl["id"])
    await client.post(
        "/api/v1/usage-limits", headers=admin,
        json={"template_id": tpl["id"], "scope_type": "user", "scope_id": opid,
              "max_uses": 1, "window": "total"},
    )
    # admin (different user) is unaffected and does not consume the quota;
    # association is enforced for everyone, so admin also names the resource
    assert (await client.post("/api/v1/usages", headers=admin, json={"template_id": tpl["id"], "resource_id": res["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=admin, json={"template_id": tpl["id"], "resource_id": res["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"], "resource_id": res["id"]})).status_code == 201
    assert (await client.post("/api/v1/usages", headers=op, json={"template_id": tpl["id"], "resource_id": res["id"]})).status_code == 429


async def test_usage_visibility_scoped_to_owner(client):
    admin, op = await _admin(client), await _operator(client)
    hello, moto = await _hello(client, op), await _moto(client, op)
    mine = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": moto["id"]},
        )
    ).json()
    theirs = (
        await client.post(
            "/api/v1/usages", headers=admin,
            json={"template_id": hello["id"], "resource_id": moto["id"]},
        )
    ).json()
    listed = (await client.get("/api/v1/usages", headers=op)).json()
    assert {u["id"] for u in listed} == {mine["id"]}
    assert (await client.get(f"/api/v1/usages/{theirs['id']}", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/usages/{theirs['id']}/status", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/usages/{mine['id']}", headers=admin)).status_code == 200
    assert (await client.get("/api/v1/usages", headers=op)).status_code == 200
    assert (await client.get("/api/v1/usages")).status_code == 401


async def test_resource_template_association_discovery_and_enforcement(client):
    """Resource-first flow: curated per-resource template lists, strictly enforced."""
    admin, op = await _admin(client), await _operator(client)
    hello, moto = await _hello(client, op), await _moto(client, op)
    opid = await _operator_id(client, admin)

    # seed: Moto G6 ↔ hello.py associated, visible to the operator
    mine = (await client.get(f"/api/v1/resources/{moto['id']}/templates", headers=op)).json()
    assert [t["name"] for t in mine] == ["hello.py"]

    # association CRUD is admin-only
    assert (
        await client.post(
            f"/api/v1/resources/{moto['id']}/templates", headers=op,
            json={"template_id": hello["id"]},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/resources/{moto['id']}/templates", headers=admin,
            json={"template_id": hello["id"]},
        )
    ).status_code == 409  # seed pair already associated
    assert (
        await client.post(
            f"/api/v1/resources/{moto['id']}/templates", headers=admin,
            json={"template_id": 9999},
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/resources/{moto['id']}/templates/9999", headers=admin)
    ).status_code == 404

    # a resource with no associations runs nothing (closed world)
    bare = (
        await client.post(
            "/api/v1/resources", headers=admin, json={"name": "Bare", "identifier": "BARE-1"}
        )
    ).json()
    await _grant_resource(client, admin, bare["id"], "user", opid)
    assert (await client.get(f"/api/v1/resources/{bare['id']}/templates", headers=op)).json() == []
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello["id"], "resource_id": bare["id"]},
        )
    ).status_code == 422

    # associated-but-ungranted templates stay hidden from discovery,
    # yet the pair is enforced at execution for everyone (incl. superusers)
    other = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "other.py", "category_id": 1, "content": {"source": "y"}},
        )
    ).json()
    await _link(client, admin, moto["id"], other["id"])
    assert [t["name"] for t in (await client.get(f"/api/v1/resources/{moto['id']}/templates", headers=op)).json()] == ["hello.py"]
    assert (
        await client.post(
            "/api/v1/usages", headers=admin,
            json={"template_id": other["id"], "resource_id": moto["id"]},
        )
    ).status_code == 201  # admin bypasses grants, not associations
    assert (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": other["id"], "resource_id": moto["id"]},
        )
    ).status_code == 403  # grant check precedes association

    # dissociate → discovery empties and execution flips to 422
    assert (
        await client.delete(f"/api/v1/resources/{moto['id']}/templates/{other['id']}", headers=admin)
    ).status_code == 204
    assert (
        await client.post(
            "/api/v1/usages", headers=admin,
            json={"template_id": other["id"], "resource_id": moto["id"]},
        )
    ).status_code == 422


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
