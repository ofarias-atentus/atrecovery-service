"""Stage 6 tests: audit rows for fetch/usage/beacon/grant/group, admin-only reads."""
from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def _hello_id(client, headers):
    tpls = (await client.get("/api/v1/templates", headers=headers)).json()
    return next(t for t in tpls if t["name"] == "hello.py")["id"]


async def _moto_id(client, headers):
    res = (await client.get("/api/v1/resources", headers=headers)).json()
    return next(r for r in res if r["identifier"] == "ZY323S5GHW")["id"]


async def _operator_id(client, admin_headers):
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()
    return next(u["id"] for u in users if u["username"] == "operator")


async def test_fetch_use_beacon_rows(client):
    admin, op = await _admin(client), await _operator(client)
    opid = await _operator_id(client, admin)
    hello_id = await _hello_id(client, op)

    assert (await client.get(f"/api/v1/templates/{hello_id}/fetch", headers=op)).status_code == 200
    moto_id = await _moto_id(client, op)
    usage = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    proc = (
        await client.post("/api/v1/processors", headers=admin, json={"name": "r1"})
    ).json()
    await client.post(
        "/api/v1/beacons", headers={"X-Processor-Token": proc["token"]},
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0}},
    )

    logs = (await client.get("/api/v1/activity-logs", headers=admin)).json()
    by_action = {e["action"] for e in logs}
    assert {"template.fetch", "template.use", "beacon.received"} <= by_action

    fetch = next(e for e in logs if e["action"] == "template.fetch")
    assert fetch["user_id"] == opid and fetch["entity_type"] == "template"
    assert fetch["entity_id"] == hello_id and fetch["ip"]
    use = next(e for e in logs if e["action"] == "template.use")
    assert use["user_id"] == opid and use["entity_id"] == usage["id"]
    assert use["meta"] == {"template_id": hello_id, "mode": "direct", "resource_id": moto_id}
    beacon = next(e for e in logs if e["action"] == "beacon.received")
    assert beacon["user_id"] is None and beacon["entity_id"] == usage["id"]
    assert beacon["meta"]["processor_name"] == "r1" and beacon["meta"]["status"] == "ok"


async def test_grant_and_group_changes_logged(client):
    admin = await _admin(client)
    opid = await _operator_id(client, admin)
    tpl = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "audited.py", "category_id": 1, "content": {"source": "x"}},
        )
    ).json()
    g = (
        await client.post(
            "/api/v1/grants/templates", headers=admin,
            json={"template_id": tpl["id"], "principal_type": "user",
                  "principal_id": opid, "can_view": True},
        )
    ).json()
    await client.delete(f"/api/v1/grants/templates/{g['id']}", headers=admin)
    grp = (
        await client.post("/api/v1/resource-groups", headers=admin, json={"name": "audit-g"})
    ).json()

    grants = (
        await client.get("/api/v1/activity-logs?action=grant.changed", headers=admin)
    ).json()
    ops = [e["meta"]["op"] for e in grants if e["entity_id"] == g["id"]]
    assert sorted(ops) == ["created", "deleted"]
    assert all(e["user_id"] == 1 for e in grants)  # admin acted
    groups = (
        await client.get("/api/v1/activity-logs?action=group.changed", headers=admin)
    ).json()
    assert any(e["entity_id"] == grp["id"] and e["meta"]["op"] == "created" for e in groups)


async def test_admin_only_and_append_only(client):
    admin, op = await _admin(client), await _operator(client)
    assert (await client.get("/api/v1/activity-logs", headers=op)).status_code == 403
    assert (await client.get("/api/v1/activity-logs")).status_code == 401
    for method in ("post", "put", "patch", "delete"):
        r = await getattr(client, method)("/api/v1/activity-logs", headers=admin)
        assert r.status_code == 405, method
    assert (await client.get("/api/v1/activity-logs/9999", headers=admin)).status_code == 404


async def test_log_aggregation_most_used_and_last_fetch(client):
    admin, op = await _admin(client), await _operator(client)
    opid = await _operator_id(client, admin)
    hello_id = await _hello_id(client, op)
    other = (
        await client.post(
            "/api/v1/templates", headers=admin,
            json={"name": "other.py", "category_id": 1, "content": {"source": "y"}},
        )
    ).json()
    await client.post(
        "/api/v1/grants/templates", headers=admin,
        json={"template_id": other["id"], "principal_type": "user",
              "principal_id": opid, "can_view": True, "can_use": True},
    )
    await client.get(f"/api/v1/templates/{hello_id}/fetch", headers=op)
    await client.get(f"/api/v1/templates/{hello_id}/fetch", headers=op)
    await client.get(f"/api/v1/templates/{other['id']}/fetch", headers=op)

    fetches = (
        await client.get(
            f"/api/v1/activity-logs?action=template.fetch&user_id={opid}", headers=admin
        )
    ).json()
    assert len(fetches) == 3
    counts: dict[int, int] = {}
    for e in fetches:
        counts[e["entity_id"]] = counts.get(e["entity_id"], 0) + 1
    assert counts[hello_id] == 2 and counts[other["id"]] == 1  # most-used: hello.py
    latest = max(fetches, key=lambda e: e["id"])
    assert latest["entity_id"] == other["id"]  # last fetch by operator
