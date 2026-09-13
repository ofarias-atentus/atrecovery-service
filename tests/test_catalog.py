"""Stage 2 tests: catalog seed, CRUD, metadata attach/detach, groups, permission gates."""
from tests.conftest import auth_headers, login


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def test_seed_catalog_present(client):
    h = await _admin(client)
    cats = {c["name"] for c in (await client.get("/api/v1/categories", headers=h)).json()}
    assert {"python", "json"} <= cats
    templates = (await client.get("/api/v1/templates", headers=h)).json()
    assert any(t["name"] == "hello.py" and t["category_name"] == "python" for t in templates)
    resources = (await client.get("/api/v1/resources", headers=h)).json()
    moto = next(r for r in resources if r["identifier"] == "ZY323S5GHW")
    assert moto["name"] == "Moto G6 3" and moto["platform"] == "android"
    assert moto["metadata"]["hostname"] == "moto-g6-3.lab"
    assert set(moto["metadata"]) >= {
        "monitor", "nodo", "nombre", "descripcion", "hostname", "host", "servidor_log",
    }
    groups = (await client.get("/api/v1/resource-groups", headers=h)).json()
    lab = next(g for g in groups if g["name"] == "lab-phones")
    assert "ZY323S5GHW" in lab["resources"]
    assert any(a["principal_type"] == "role" for a in lab["assignments"])


async def test_operator_can_read_but_not_write(client):
    h = await _operator(client)
    assert (await client.get("/api/v1/categories", headers=h)).status_code == 200
    assert (await client.get("/api/v1/templates", headers=h)).status_code == 200
    assert (await client.get("/api/v1/resources", headers=h)).status_code == 200
    assert (await client.get("/api/v1/metadata-definitions", headers=h)).status_code == 200
    assert (await client.post("/api/v1/categories", headers=h, json={"name": "x"})).status_code == 403
    assert (
        await client.post("/api/v1/templates", headers=h, json={"name": "x", "category_id": 1, "content": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/resources", headers=h, json={"name": "x", "identifier": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/resource-groups", headers=h, json={"name": "x"})
    ).status_code == 403
    assert (await client.get("/api/v1/templates", headers=h)).status_code == 200


async def test_unauthenticated_denied(client):
    for path in ("/api/v1/categories", "/api/v1/templates", "/api/v1/resources", "/api/v1/resource-groups"):
        assert (await client.get(path)).status_code == 401


async def test_category_template_crud_and_uniqueness(client):
    h = await _admin(client)
    cat = (await client.post("/api/v1/categories", headers=h, json={"name": "yaml"})).json()
    assert (await client.post("/api/v1/categories", headers=h, json={"name": "yaml"})).status_code == 409
    tpl = (
        await client.post(
            "/api/v1/templates",
            headers=h,
            json={"name": "deploy.yaml", "category_id": cat["id"], "content": "steps: []"},
        )
    ).json()
    assert tpl["category_name"] == "yaml"
    dup = await client.post(
        "/api/v1/templates",
        headers=h,
        json={"name": "deploy.yaml", "category_id": cat["id"], "content": "other"},
    )
    assert dup.status_code == 409
    # same name, new version is allowed
    v2 = (
        await client.post(
            "/api/v1/templates",
            headers=h,
            json={"name": "deploy.yaml", "version": 2, "category_id": cat["id"], "content": "v2"},
        )
    )
    assert v2.status_code == 201
    upd = (
        await client.patch(f"/api/v1/templates/{tpl['id']}", headers=h, json={"content": "steps: [a]"})
    ).json()
    assert upd["content"] == "steps: [a]"
    # soft delete: hidden from default list, visible with include_inactive
    assert (await client.delete(f"/api/v1/templates/{tpl['id']}", headers=h)).status_code == 204
    ids = [t["id"] for t in (await client.get("/api/v1/templates", headers=h)).json()]
    assert tpl["id"] not in ids
    all_ids = [
        t["id"] for t in (await client.get("/api/v1/templates?include_inactive=true", headers=h)).json()
    ]
    assert tpl["id"] in all_ids


async def test_resource_metadata_attach_detach(client):
    h = await _admin(client)
    r = (
        await client.post(
            "/api/v1/resources", headers=h, json={"name": "Pixel", "identifier": "PIXEL01"}
        )
    ).json()
    assert r["metadata"] == {}
    put = await client.put(
        f"/api/v1/resources/{r['id']}/metadata", headers=h, json={"key": "hostname", "value": "pixel.lab"}
    )
    assert put.status_code == 200
    got = (await client.get(f"/api/v1/resources/{r['id']}", headers=h)).json()
    assert got["metadata"]["hostname"] == "pixel.lab"
    # unknown definition key -> 404
    bad = await client.put(
        f"/api/v1/resources/{r['id']}/metadata", headers=h, json={"key": "nope", "value": 1}
    )
    assert bad.status_code == 404
    assert (await client.delete(f"/api/v1/resources/{r['id']}/metadata/hostname", headers=h)).status_code == 204
    got2 = (await client.get(f"/api/v1/resources/{r['id']}", headers=h)).json()
    assert "hostname" not in got2["metadata"]
    assert (
        await client.delete(f"/api/v1/resources/{r['id']}/metadata/hostname", headers=h)
    ).status_code == 404


async def test_metadata_definitions_crud(client):
    h = await _admin(client)
    op = await _operator(client)
    keys = [d["key"] for d in (await client.get("/api/v1/metadata-definitions", headers=op)).json()]
    assert "hostname" in keys
    d = (
        await client.post("/api/v1/metadata-definitions", headers=h, json={"key": "rack", "value_type": "str"})
    ).json()
    assert d["key"] == "rack"
    assert (await client.post("/api/v1/metadata-definitions", headers=h, json={"key": "rack"})).status_code == 409
    assert (await client.post("/api/v1/metadata-definitions", headers=op, json={"key": "z"})).status_code == 403
    assert (await client.delete("/api/v1/metadata-definitions/rack", headers=h)).status_code == 204


async def test_groups_members_assignments(client):
    h = await _admin(client)
    g = (await client.post("/api/v1/resource-groups", headers=h, json={"name": "qa"})).json()
    r = (
        await client.post("/api/v1/resources", headers=h, json={"name": "Q1", "identifier": "Q1"})
    ).json()
    g2 = (
        await client.post(f"/api/v1/resource-groups/{g['id']}/members", headers=h, json={"resource_id": r["id"]})
    ).json()
    assert "Q1" in g2["resources"]
    # assign to operator user id 2
    g3 = (
        await client.post(
            f"/api/v1/resource-groups/{g['id']}/assignments",
            headers=h,
            json={"principal_type": "user", "principal_id": 2},
        )
    ).json()
    assert any(a["principal_type"] == "user" and a["principal_id"] == 2 for a in g3["assignments"])
    mine = (
        await client.get("/api/v1/resource-groups/by-principal/user/2", headers=h)
    ).json()
    assert {x["name"] for x in mine} >= {"qa", "lab-phones"}  # role assignment resolves too
    assert (await client.get("/api/v1/resource-groups/by-principal/bogus/2", headers=h)).status_code == 400
    g4 = (await client.delete(f"/api/v1/resource-groups/{g['id']}/members/{r['id']}", headers=h)).json()
    assert "Q1" not in g4["resources"]
    aid = next(a["id"] for a in g3["assignments"] if a["principal_type"] == "user")
    assert (await client.delete(f"/api/v1/resource-groups/assignments/{aid}", headers=h)).status_code == 204
