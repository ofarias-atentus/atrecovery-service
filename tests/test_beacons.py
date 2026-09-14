"""Stage 5 tests: processor lifecycle, token auth, beacon linkage + lifecycle."""
from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


def _ph(token: str) -> dict[str, str]:
    return {"X-Processor-Token": token}


async def _make_processor(client, admin_headers, name="runner-1", scopes=None):
    body = {"name": name}
    if scopes is not None:
        body["scopes"] = scopes
    r = await client.post("/api/v1/processors", headers=admin_headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _hello_id(client, headers):
    tpls = (await client.get("/api/v1/templates", headers=headers)).json()
    return next(t for t in tpls if t["name"] == "hello.py")["id"]


async def _moto_id(client, headers):
    res = (await client.get("/api/v1/resources", headers=headers)).json()
    return next(r for r in res if r["identifier"] == "ZY323S5GHW")["id"]


async def test_processor_lifecycle_and_token_shown_once(client):
    admin, op = await _admin(client), await _operator(client)
    created = await _make_processor(client, admin)
    assert created["token"] and len(created["token"]) >= 32
    listed = (await client.get("/api/v1/processors", headers=admin)).json()
    entry = next(p for p in listed if p["name"] == "runner-1")
    assert "token" not in entry and "token_hash" not in entry
    assert (
        await client.post("/api/v1/processors", headers=admin, json={"name": "runner-1"})
    ).status_code == 409
    assert (
        await client.post("/api/v1/processors", headers=op, json={"name": "x"})
    ).status_code == 403
    assert (await client.get("/api/v1/processors", headers=op)).status_code == 403
    assert (await client.delete("/api/v1/processors/9999", headers=admin)).status_code == 404
    assert (await client.delete(f"/api/v1/processors/{created['id']}", headers=admin)).status_code == 204


async def test_beacon_report_drives_usage_lifecycle(client):
    admin, op = await _admin(client), await _operator(client)
    proc = await _make_processor(client, admin)
    hello_id = await _hello_id(client, op)
    moto_id = await _moto_id(client, op)
    usage = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id, "mode": "voucher"},
        )
    ).json()
    partial = (
        await client.post(
            "/api/v1/beacons", headers=_ph(proc["token"]),
            json={"usage_id": usage["id"], "status": "partial", "result": {"pct": 50}},
        )
    ).json()
    assert partial["processor_id"] == proc["id"] and partial["result"] == {"pct": 50}
    st = (await client.get(f"/api/v1/usages/{usage['id']}/status", headers=op)).json()
    assert st["status"] == "running" and st["beacon_count"] == 1 and st["latest_beacon_status"] == "partial"
    await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0}},
    )
    st = (await client.get(f"/api/v1/usages/{usage['id']}/status", headers=op)).json()
    assert st["status"] == "done" and st["beacon_count"] == 2 and st["latest_beacon_status"] == "ok"
    # error path on a second usage
    usage2 = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage2["id"], "status": "error", "result": {"rc": 1}},
    )
    st2 = (await client.get(f"/api/v1/usages/{usage2['id']}/status", headers=op)).json()
    assert st2["status"] == "failed"


async def test_beacon_idempotency_key_replays_and_counts(client):
    """Cron-driven executors may report repeatedly: same key replays (200),
    new keys append (201), and use_count tracks accepted executions."""
    admin, op = await _admin(client), await _operator(client)
    proc = await _make_processor(client, admin)
    hello_id = await _hello_id(client, op)
    moto_id = await _moto_id(client, op)
    usage = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    assert usage["use_count"] == 1
    first = await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0},
              "idem_key": "cron-001"},
    )
    assert first.status_code == 201
    assert first.json()["idem_key"] == "cron-001"
    # exact repeat: replayed, no new row, no extra count
    replay = await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0},
              "idem_key": "cron-001"},
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    st = (await client.get(f"/api/v1/usages/{usage['id']}/status", headers=op)).json()
    assert st["beacon_count"] == 1
    got = (await client.get(f"/api/v1/usages/{usage['id']}", headers=op)).json()
    assert got["use_count"] == 2
    # new key, same content: genuinely new execution, appended + counted
    second = await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage["id"], "status": "ok", "result": {"rc": 0},
              "idem_key": "cron-002"},
    )
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]
    st = (await client.get(f"/api/v1/usages/{usage['id']}/status", headers=op)).json()
    assert st["beacon_count"] == 2
    got = (await client.get(f"/api/v1/usages/{usage['id']}", headers=op)).json()
    assert got["use_count"] == 3
    # keyless beacons keep the legacy append-everything behavior
    third = await client.post(
        "/api/v1/beacons", headers=_ph(proc["token"]),
        json={"usage_id": usage["id"], "status": "partial"},
    )
    assert third.status_code == 201
    got = (await client.get(f"/api/v1/usages/{usage['id']}", headers=op)).json()
    assert got["use_count"] == 4


async def test_beacon_auth_gates(client):
    admin, op = await _admin(client), await _operator(client)
    proc = await _make_processor(client, admin)
    scoped_out = await _make_processor(client, admin, name="narrow", scopes=["other"])
    hello_id = await _hello_id(client, op)
    moto_id = await _moto_id(client, op)
    usage = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    body = {"usage_id": usage["id"], "status": "ok"}
    assert (await client.post("/api/v1/beacons", json=body)).status_code == 401
    assert (await client.post("/api/v1/beacons", headers=_ph("bogus"), json=body)).status_code == 401
    assert (
        await client.post("/api/v1/beacons", headers=_ph(proc["token"] + "x"), json=body)
    ).status_code == 401
    # JWT is not a processor credential
    jwt_headers = {"Authorization": op["Authorization"]}
    assert (await client.post("/api/v1/beacons", headers=jwt_headers, json=body)).status_code == 401
    # unknown usage, bad status, missing scope
    assert (
        await client.post("/api/v1/beacons", headers=_ph(proc["token"]), json={"usage_id": 9999, "status": "ok"})
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/beacons", headers=_ph(proc["token"]),
            json={"usage_id": usage["id"], "status": "bogus"},
        )
    ).status_code == 422
    assert (
        await client.post("/api/v1/beacons", headers=_ph(scoped_out["token"]), json=body)
    ).status_code == 403
    # deactivated processor can no longer report
    await client.delete(f"/api/v1/processors/{proc['id']}", headers=admin)
    assert (
        await client.post("/api/v1/beacons", headers=_ph(proc["token"]), json=body)
    ).status_code == 401


async def test_beacon_read_gates_and_usage_filter(client):
    admin, op = await _admin(client), await _operator(client)
    proc = await _make_processor(client, admin)
    hello_id = await _hello_id(client, op)
    moto_id = await _moto_id(client, op)
    mine = (
        await client.post(
            "/api/v1/usages", headers=op,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    theirs = (
        await client.post(
            "/api/v1/usages", headers=admin,
            json={"template_id": hello_id, "resource_id": moto_id},
        )
    ).json()
    b_mine = (
        await client.post(
            "/api/v1/beacons", headers=_ph(proc["token"]),
            json={"usage_id": mine["id"], "status": "ok"},
        )
    ).json()
    b_theirs = (
        await client.post(
            "/api/v1/beacons", headers=_ph(proc["token"]),
            json={"usage_id": theirs["id"], "status": "ok"},
        )
    ).json()
    listed = (await client.get("/api/v1/beacons", headers=op)).json()
    assert {b["id"] for b in listed} == {b_mine["id"]}
    assert (await client.get(f"/api/v1/beacons/{b_mine['id']}", headers=op)).status_code == 200
    assert (await client.get(f"/api/v1/beacons/{b_theirs['id']}", headers=op)).status_code == 403
    assert (await client.get(f"/api/v1/beacons/{b_theirs['id']}", headers=admin)).status_code == 200
    filtered = (
        await client.get(f"/api/v1/beacons?usage_id={mine['id']}", headers=op)
    ).json()
    assert [b["id"] for b in filtered] == [b_mine["id"]]
    assert (await client.get("/api/v1/beacons")).status_code == 401
    assert (await client.get("/api/v1/beacons/9999", headers=op)).status_code == 404


async def test_lab_runner_seed_processor_exists(client):
    admin = await _admin(client)
    names = {p["name"] for p in (await client.get("/api/v1/processors", headers=admin)).json()}
    assert "lab-runner" in names
