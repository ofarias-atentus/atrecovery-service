"""Admin-only bulk resource import: CSV/JSON validation + atomic upsert."""
from tests.conftest import auth_headers, login

HEADER = (
    "monitor_id,nodo_id,nombre,descripcion,hostname,replic_dbhost,servidor_log,"
    "id,device_id,device_nombre,activo,device_descripcion,"
    "device_ultima_actualizacion,platform,platform_version,fecha_ultima_replicacion"
)
ROW = (
    "4787,2270,galaxy-a36-mx-3,galaxy-a36-mx-3,"
    "monmobile-mx-32.internal.atentus.com,10.20.15.68,"
    "Monmobile-mx-32.internal.atentus.com:5000,1757,RFGYC356WTJ,"
    "galaxy-a36-mx-3,true,galaxy-a36-mx-3,2026-08-14 19:45:43.399,"
    "android,15.0,2026-08-14 19:45:43.399"
)
CSV_OK = f"{HEADER}\n{ROW}\n"

JSON_ROW = {
    "monitor_id": "4787",
    "nodo_id": "2270",
    "nombre": "galaxy-a36-mx-3",
    "descripcion": "galaxy-a36-mx-3",
    "hostname": "monmobile-mx-32.internal.atentus.com",
    "replic_dbhost": "10.20.15.68",
    "servidor_log": "Monmobile-mx-32.internal.atentus.com:5000",
    "id": "1757",
    "device_id": "RFGYC356WTJ",
    "device_nombre": "galaxy-a36-mx-3",
    "activo": "true",
    "device_descripcion": "galaxy-a36-mx-3",
    "device_ultima_actualizacion": "2026-08-14 19:45:43.399",
    "platform": "android",
    "platform_version": "15.0",
    "fecha_ultima_replicacion": "2026-08-14 19:45:43.399",
}


async def _admin(client):
    return auth_headers((await login(client, "admin", "admin123"))["access_token"])


async def _operator(client):
    return auth_headers((await login(client, "operator", "operator123"))["access_token"])


async def _resource_by_identifier(client, headers, identifier):
    resources = (
        await client.get("/api/v1/resources?include_inactive=true", headers=headers)
    ).json()
    return next((r for r in resources if r["identifier"] == identifier), None)


async def test_csv_import_creates_resource_and_monitor(client):
    h = await _admin(client)
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert r.json() == {
        "created": 1,
        "updated": 0,
        "total": 1,
        "identifiers": ["RFGYC356WTJ"],
    }
    got = await _resource_by_identifier(client, h, "RFGYC356WTJ")
    assert got is not None
    assert got["name"] == "galaxy-a36-mx-3"
    assert got["resource_type_name"] == "mobile_device"
    assert got["is_active"] is True
    assert got["data"] == {
        "udid": "RFGYC356WTJ",
        "nombre": "galaxy-a36-mx-3",
        "plataforma": "android",
        "version_plataforma": "15.0",
        "descripcion": "galaxy-a36-mx-3",
        "device_ultima_actualizacion": "2026-08-14 19:45:43.399",
        "fecha_ultima_replicacion": "2026-08-14 19:45:43.399",
    }
    assert len(got["metadata"]) == 1
    assert got["metadata"][0]["metadata_type_name"] == "monitor"
    assert got["metadata"][0]["data"] == {
        "monitor": "4787",
        "nodo": "2270",
        "nombre": "galaxy-a36-mx-3",
        "descripcion": "galaxy-a36-mx-3",
        "hostname": "monmobile-mx-32.internal.atentus.com",
        "host": "10.20.15.68",
        "servidor_log": "Monmobile-mx-32.internal.atentus.com:5000",
        "source_id": "1757",
    }
    logs = (await client.get("/api/v1/activity-logs", headers=h)).json()
    assert any(
        entry["action"] == "resource.imported"
        and entry["meta"] == {"source": "csv", "created": 1, "updated": 0}
        for entry in logs
    )


async def test_json_import_matches_csv_result(client):
    h = await _admin(client)
    r = await client.post(
        "/api/v1/resources/import/json", headers=h, json={"rows": [JSON_ROW]}
    )
    assert r.status_code == 201, r.text
    assert r.json()["identifiers"] == ["RFGYC356WTJ"]
    got = await _resource_by_identifier(client, h, "RFGYC356WTJ")
    assert got["data"]["udid"] == "RFGYC356WTJ"
    assert got["metadata"][0]["data"]["source_id"] == "1757"


async def test_import_upserts_existing_identifier(client):
    h = await _admin(client)
    first = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
    )
    assert first.status_code == 201
    changed = CSV_OK.replace("galaxy-a36-mx-3,true,", "galaxy-a36-mx-3-renamed,false,", 1)
    second = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", changed.encode(), "text/csv")},
    )
    assert second.status_code == 201, second.text
    assert second.json() == {
        "created": 0,
        "updated": 1,
        "total": 1,
        "identifiers": ["RFGYC356WTJ"],
    }
    got = await _resource_by_identifier(client, h, "RFGYC356WTJ")
    assert got["name"] == "galaxy-a36-mx-3-renamed"
    assert got["is_active"] is False
    assert got["data"]["nombre"] == "galaxy-a36-mx-3-renamed"


async def test_import_rejects_non_admin(client):
    op = await _operator(client)
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=op,
        files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/resources/import/json", headers=op, json={"rows": [JSON_ROW]}
    )
    assert r.status_code == 403
    assert (await client.post("/api/v1/resources/import/json", json={"rows": [JSON_ROW]})).status_code == 401
    assert (
        await client.post(
            "/api/v1/resources/import/csv",
            files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
        )
    ).status_code == 401


async def test_invalid_csv_header_rolls_back(client):
    h = await _admin(client)
    before = len((await client.get("/api/v1/resources", headers=h)).json())
    bad = "monitor_id,device_id\n1,x\n"
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("bad.csv", bad.encode(), "text/csv")},
    )
    assert r.status_code == 422
    after = len((await client.get("/api/v1/resources", headers=h)).json())
    assert after == before
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is None


async def test_invalid_rows_are_atomic(client):
    h = await _admin(client)
    second = ROW.replace("RFGYC356WTJ", "SECOND01").replace(
        "2026-08-14 19:45:43.399", "not-a-timestamp"
    )
    payload = f"{HEADER}\n{ROW}\n{second}\n"
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", payload.encode(), "text/csv")},
    )
    assert r.status_code == 422, r.text
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is None
    assert await _resource_by_identifier(client, h, "SECOND01") is None


async def test_invalid_boolean_and_duplicates_rejected(client):
    h = await _admin(client)
    bad_bool = CSV_OK.replace(",true,", ",maybe,")
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", bad_bool.encode(), "text/csv")},
    )
    assert r.status_code == 422
    dup = f"{HEADER}\n{ROW}\n{ROW}\n"
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", dup.encode(), "text/csv")},
    )
    assert r.status_code == 422
    assert "duplicate device_id" in r.text
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is None


async def test_missing_metadata_field_rejected(client):
    h = await _admin(client)
    row = dict(JSON_ROW)
    row["hostname"] = "  "
    r = await client.post(
        "/api/v1/resources/import/json", headers=h, json={"rows": [row]}
    )
    assert r.status_code == 422
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is None


async def test_inactive_type_rejected(client):
    h = await _admin(client)
    types = (await client.get("/api/v1/metadata-types", headers=h)).json()
    monitor = next(t for t in types if t["name"] == "monitor")
    assert (await client.delete(f"/api/v1/metadata-types/{monitor['id']}", headers=h)).status_code == 204
    r = await client.post(
        "/api/v1/resources/import/csv",
        headers=h,
        files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
    )
    assert r.status_code == 422
    assert "inactive" in r.text
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is None


async def test_admin_import_view_guarded_and_working(client):
    anon = await client.get("/admin/resource-import")
    assert anon.status_code in (302, 303)
    assert "/admin/login" in anon.headers.get("location", "")
    await client.post("/admin/login", data={"username": "admin", "password": "admin123"})
    form = await client.get("/admin/resource-import")
    assert form.status_code == 200
    assert "Import Resources" in form.text
    uploaded = await client.post(
        "/admin/resource-import",
        files={"file": ("import.csv", CSV_OK.encode(), "text/csv")},
    )
    assert uploaded.status_code == 200
    assert "1 created" in uploaded.text
    h = await _admin(client)
    assert await _resource_by_identifier(client, h, "RFGYC356WTJ") is not None
