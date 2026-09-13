"""Stage 7 tests: internal resolvers, mocked external fetch, permission gates."""
import httpx

from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def _ids(client, admin_headers):
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()
    return next(u["id"] for u in users if u["username"] == "operator")


async def _hello_id(client, headers):
    tpls = (await client.get("/api/v1/templates", headers=headers)).json()
    return next(t for t in tpls if t["name"] == "hello.py")["id"]


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"outer": {"rate": 0.42}, "other": 1}


class _FakeClient:
    seen = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, params=None, headers=None):
        _FakeClient.seen = (method, url, params, headers)
        return _FakeResponse()


class _FailingClient(_FakeClient):
    async def request(self, method, url, params=None, headers=None):
        raise httpx.ConnectError("down")


async def test_most_used_template(client):
    op = await _operator(client)
    hello_id = await _hello_id(client, op)
    for _ in range(2):
        await client.post("/api/v1/usages", headers=op, json={"template_id": hello_id})
    value = (await client.get("/api/v1/stats/most_used_template", headers=op)).json()
    assert value["name"] == "most_used_template"
    assert value["value"] == {"template_id": hello_id, "template_name": "hello.py", "uses": 2}


async def test_last_fetch_by_user(client):
    admin, op = await _admin(client), await _operator(client)
    opid = await _ids(client, admin)
    hello_id = await _hello_id(client, op)
    await client.get(f"/api/v1/templates/{hello_id}/fetch", headers=op)
    value = (
        await client.get(f"/api/v1/stats/last_fetch_by_user?user_id={opid}", headers=op)
    ).json()
    assert value["value"]["user_id"] == opid and value["value"]["template_id"] == hello_id
    assert value["value"]["fetched_at"]
    # missing param, other user forbidden for operator but ok for admin
    assert (
        await client.get("/api/v1/stats/last_fetch_by_user", headers=op)
    ).status_code == 422
    assert (
        await client.get("/api/v1/stats/last_fetch_by_user?user_id=1", headers=op)
    ).status_code == 403
    admin_view = (
        await client.get("/api/v1/stats/last_fetch_by_user?user_id=1", headers=admin)
    ).json()
    assert admin_view["value"] == {"user_id": 1, "template_id": None, "fetched_at": None}


async def test_beacon_success_rate(client):
    admin, op = await _admin(client), await _operator(client)
    empty = (await client.get("/api/v1/stats/beacon_success_rate", headers=op)).json()
    assert empty["value"] == {"total": 0, "ok": 0, "rate": None}
    proc = (
        await client.post("/api/v1/processors", headers=admin, json={"name": "r1"})
    ).json()
    hello_id = await _hello_id(client, op)
    for verdict in ("ok", "error"):
        usage = (
            await client.post("/api/v1/usages", headers=op, json={"template_id": hello_id})
        ).json()
        await client.post(
            "/api/v1/beacons", headers={"X-Processor-Token": proc["token"]},
            json={"usage_id": usage["id"], "status": verdict},
        )
    value = (await client.get("/api/v1/stats/beacon_success_rate", headers=op)).json()
    assert value["value"] == {"total": 2, "ok": 1, "rate": 0.5}


async def test_external_stat_defined_without_code_change(client, monkeypatch):
    admin, op = await _admin(client), await _operator(client)
    monkeypatch.setattr(
        "app.services.stats_svc.httpx.AsyncClient", _FakeClient
    )
    created = (
        await client.post(
            "/api/v1/stats/definitions", headers=admin,
            json={"name": "fleet_health", "source_type": "external",
                  "query_config": {"url": "https://fleet.example/health",
                                   "mapping": {"rate": "outer.rate"}},
                  "required_params": ["region"],
                  "required_permission_code": "stats:view"},
        )
    ).json()
    assert created["name"] == "fleet_health"
    value = (
        await client.get("/api/v1/stats/fleet_health?region=eu", headers=op)
    ).json()
    assert value["value"]["data"] == {"rate": 0.42}
    assert value["value"]["status_code"] == 200
    method, url, params, _headers = _FakeClient.seen
    assert (method, url, params) == ("GET", "https://fleet.example/health", {"region": "eu"})


async def test_external_fetch_failure_is_502(client, monkeypatch):
    admin = await _admin(client)
    monkeypatch.setattr("app.services.stats_svc.httpx.AsyncClient", _FailingClient)
    await client.post(
        "/api/v1/stats/definitions", headers=admin,
        json={"name": "downstream", "source_type": "external",
              "query_config": {"url": "https://down.example/x"}},
    )
    assert (
        await client.get("/api/v1/stats/downstream", headers=admin)
    ).status_code == 502


async def test_stat_gates_and_definition_guards(client):
    admin, op = await _admin(client), await _operator(client)
    # user without stats:view
    await client.post(
        "/api/v1/users", headers=admin,
        json={"username": "nostats", "email": "n@example.com", "password": "x12345678"},
    )
    no_token = (await login(client, "nostats", "x12345678"))["access_token"]
    no_headers = auth_headers(no_token)
    assert (
        await client.get("/api/v1/stats/most_used_template", headers=no_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/stats/most_used_template")).status_code == 401
    assert (await client.get("/api/v1/stats/nope", headers=op)).status_code == 404
    # definitions are admin-only and validated
    assert (
        await client.post(
            "/api/v1/stats/definitions", headers=op, json={"name": "x"}
        )
    ).status_code == 403
    assert (await client.get("/api/v1/stats/definitions", headers=op)).status_code == 403
    assert (
        await client.post(
            "/api/v1/stats/definitions", headers=admin, json={"name": "most_used_template"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/api/v1/stats/definitions", headers=admin,
            json={"name": "bad", "required_permission_code": "nope"},
        )
    ).status_code == 404
    assert (await client.delete("/api/v1/stats/definitions/nope", headers=admin)).status_code == 404
    defs = (await client.get("/api/v1/stats/definitions", headers=admin)).json()
    assert {"most_used_template", "last_fetch_by_user", "beacon_success_rate"} <= {
        d["name"] for d in defs
    }
    await client.delete("/api/v1/stats/definitions/beacon_success_rate", headers=admin)
    assert (
        await client.get("/api/v1/stats/beacon_success_rate", headers=op)
    ).status_code == 404
