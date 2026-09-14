"""Catalog + typed JSON resources tests: seed, CRUD, validation, groups, gates."""
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
    hello = next(t for t in templates if t["name"] == "hello.py")
    assert hello["category_name"] == "python"
    assert isinstance(hello["content"], dict) and "hello from template" in hello["content"]["source"]
    types = {t["name"] for t in (await client.get("/api/v1/resource-types", headers=h)).json()}
    assert "mobile_device" in types
    resources = (await client.get("/api/v1/resources", headers=h)).json()
    moto = next(r for r in resources if r["identifier"] == "ZY323S5GHW")
    assert moto["name"] == "Moto G6 3" and moto["resource_type_name"] == "mobile_device"
    assert moto["data"]["plataforma"] == "android"
    assert moto["data"]["hostname"] == "moto-g6-3.lab"
    assert set(moto["data"]) >= {
        "udid", "nombre", "plataforma", "version_plataforma", "descripcion",
        "monitor", "nodo", "hostname", "host", "servidor_log",
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
    assert (await client.get("/api/v1/resource-types", headers=h)).status_code == 200
    assert (await client.post("/api/v1/categories", headers=h, json={"name": "x"})).status_code == 403
    assert (
        await client.post("/api/v1/templates", headers=h, json={"name": "x", "category_id": 1, "content": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/resources", headers=h, json={"name": "x", "identifier": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/resource-types", headers=h, json={"name": "x"})
    ).status_code == 403
    assert (
        await client.post("/api/v1/resource-groups", headers=h, json={"name": "x"})
    ).status_code == 403
    assert (await client.get("/api/v1/templates", headers=h)).status_code == 200


async def test_unauthenticated_denied(client):
    for path in ("/api/v1/categories", "/api/v1/templates", "/api/v1/resources", "/api/v1/resource-groups"):
        assert (await client.get(path)).status_code == 401


async def test_category_template_crud_and_json_validation(client):
    h = await _admin(client)
    cat = (await client.post("/api/v1/categories", headers=h, json={"name": "yaml"})).json()
    assert (await client.post("/api/v1/categories", headers=h, json={"name": "yaml"})).status_code == 409
    tpl = (
        await client.post(
            "/api/v1/templates",
            headers=h,
            json={"name": "deploy.yaml", "category_id": cat["id"], "content": {"steps": []}},
        )
    ).json()
    assert tpl["category_name"] == "yaml"
    assert tpl["content"] == {"steps": []}
    dup = await client.post(
        "/api/v1/templates",
        headers=h,
        json={"name": "deploy.yaml", "category_id": cat["id"], "content": {"steps": ["other"]}},
    )
    assert dup.status_code == 409
    # same name, new version is allowed
    v2 = (
        await client.post(
            "/api/v1/templates",
            headers=h,
            json={"name": "deploy.yaml", "version": 2, "category_id": cat["id"], "content": {"steps": ["v2"]}},
        )
    )
    assert v2.status_code == 201
    # input_schema validation enforced the same way as resource type schemas
    bad_cat = (
        await client.post(
            "/api/v1/categories", headers=h,
            json={"name": "strict", "schema_hint": {"type": "object", "required": ["source"]}},
        )
    ).json()
    bad = await client.post(
        "/api/v1/templates", headers=h,
        json={"name": "bad.py", "category_id": bad_cat["id"], "content": {"nope": 1}},
    )
    assert bad.status_code == 422
    good = await client.post(
        "/api/v1/templates", headers=h,
        json={"name": "good.py", "category_id": bad_cat["id"], "content": {"source": "x"}},
    )
    assert good.status_code == 201
    upd = (
        await client.patch(f"/api/v1/templates/{tpl['id']}", headers=h, json={"content": {"steps": ["a"]}})
    ).json()
    assert upd["content"] == {"steps": ["a"]}
    # soft delete: hidden from default list, visible with include_inactive
    assert (await client.delete(f"/api/v1/templates/{tpl['id']}", headers=h)).status_code == 204
    ids = [t["id"] for t in (await client.get("/api/v1/templates", headers=h)).json()]
    assert tpl["id"] not in ids
    all_ids = [
        t["id"] for t in (await client.get("/api/v1/templates?include_inactive=true", headers=h)).json()
    ]
    assert tpl["id"] in all_ids


async def test_resource_types_and_data_json(client):
    h = await _admin(client)
    op = await _operator(client)
    types = (await client.get("/api/v1/resource-types", headers=op)).json()
    mobile = next(t for t in types if t["name"] == "mobile_device")
    assert mobile["schema"]["required"] == ["udid", "nombre", "plataforma"]
    # invalid data rejected by type schema
    bad = await client.post(
        "/api/v1/resources", headers=h,
        json={"name": "Bad", "identifier": "BAD01",
              "resource_type_id": mobile["id"], "data": {"nombre": "x"}},
    )
    assert bad.status_code == 422
    r = (
        await client.post(
            "/api/v1/resources", headers=h,
            json={"name": "Pixel", "identifier": "PIXEL01",
                  "resource_type_id": mobile["id"],
                  "data": {"udid": "PIXEL01", "nombre": "Pixel", "plataforma": "android"}},
        )
    ).json()
    assert r["data"]["plataforma"] == "android"
    assert r["resource_type_name"] == "mobile_device"
    got = (await client.get(f"/api/v1/resources/{r['id']}", headers=h)).json()
    assert got["data"]["udid"] == "PIXEL01"
    upd = (
        await client.patch(f"/api/v1/resources/{r['id']}", headers=h,
                           json={"data": {"udid": "PIXEL01", "nombre": "Pixel 2", "plataforma": "android"}})
    ).json()
    assert upd["data"]["nombre"] == "Pixel 2"
    # unknown type -> 404; duplicate identifier -> 409; operator write -> 403
    assert (
        await client.post("/api/v1/resources", headers=h, json={"name": "z", "identifier": "Z2", "resource_type_id": 9999})
    ).status_code == 404
    assert (
        await client.post("/api/v1/resources", headers=h, json={"name": "dup", "identifier": "PIXEL01"})
    ).status_code == 409
    assert (
        await client.post("/api/v1/resource-types", headers=op, json={"name": "z"})
    ).status_code == 403
    # type CRUD
    t = (await client.post("/api/v1/resource-types", headers=h, json={"name": "sensor"})).json()
    assert t["name"] == "sensor"
    assert (await client.post("/api/v1/resource-types", headers=h, json={"name": "sensor"})).status_code == 409
    assert (await client.delete(f"/api/v1/resource-types/{t['id']}", headers=h)).status_code == 204


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
