"""Admin association creates + per-view summaries.

Covers the two composite-PK link tables (resource<->routine,
group<->resource): create pages render select inputs, valid pairs persist,
duplicates fail with a readable message, rows are immutable, and
composite-key detail URLs keep working. Also asserts every managed view
defines a non-empty summary shown at the top of list pages.
"""
from sqlalchemy import select

from app.admin.views import _VIEWS, ResourceGroupMemberAdmin, ResourceRoutineAdmin
from app.db.session import get_session_factory
from app.models.catalog import Routine
from app.models.resources import (
    Resource,
    ResourceGroup,
    ResourceGroupMember,
    ResourceRoutine,
)


async def _login(client):
    r = await client.post("/admin/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code in (302, 303), r.text


async def _seed_extra():
    async with get_session_factory()() as session:
        session.add(Routine(name="extra.py", version=1, category_id=1, content={"x": 1}))
        session.add(Resource(name="extra", identifier="EXTRA1"))
        session.add(ResourceGroup(name="extra-group"))
        await session.commit()


def test_every_view_has_summary():
    assert len(_VIEWS) == 23
    blanks = [v.__name__ for v in _VIEWS if not getattr(v, "admin_summary", "")]
    assert blanks == []


async def test_resource_routine_create_form_has_selects_and_summary(client):
    await _login(client)
    r = await client.get("/admin/resource-routine/create")
    assert r.status_code == 200
    assert b"Associate routines with resources" in r.content
    assert b'name="resource"' in r.content and b'name="routine"' in r.content


async def test_resource_group_member_create_form_has_selects_and_summary(client):
    await _login(client)
    r = await client.get("/admin/resource-group-member/create")
    assert r.status_code == 200
    assert b"Add resources to" in r.content
    assert b'name="group"' in r.content and b'name="resource"' in r.content


async def test_create_resource_routine_then_duplicate(client):
    await _login(client)
    await _seed_extra()
    data = {"resource": "1", "routine": "2", "save": "Save"}
    created = await client.post("/admin/resource-routine/create", data=data, follow_redirects=False)
    assert created.status_code in (302, 303), created.text

    async with get_session_factory()() as session:
        row = await session.execute(
            select(ResourceRoutine).where(
                ResourceRoutine.resource_id == 1, ResourceRoutine.routine_id == 2
            )
        )
        assert row.scalar_one_or_none() is not None

    dup = await client.post("/admin/resource-routine/create", data=data)
    assert dup.status_code == 400
    assert b"already associated" in dup.content

    details = await client.get("/admin/resource-routine/details/1;2")
    assert details.status_code == 200
    assert b"Associate routines with resources" in details.content

    for path in ("/admin/resource-routine/edit/1;2",):
        assert (await client.get(path)).status_code == 403


async def test_create_group_member_then_duplicate(client):
    await _login(client)
    await _seed_extra()
    data = {"group": "2", "resource": "1", "save": "Save"}
    created = await client.post("/admin/resource-group-member/create", data=data, follow_redirects=False)
    assert created.status_code in (302, 303), created.text

    async with get_session_factory()() as session:
        row = await session.execute(
            select(ResourceGroupMember).where(
                ResourceGroupMember.group_id == 2, ResourceGroupMember.resource_id == 1
            )
        )
        assert row.scalar_one_or_none() is not None

    dup = await client.post("/admin/resource-group-member/create", data=data)
    assert dup.status_code == 400
    assert b"already a member" in dup.content

    details = await client.get("/admin/resource-group-member/details/2;1")
    assert details.status_code == 200
    assert b"Add resources to" in details.content

    assert (await client.get("/admin/resource-group-member/edit/2;1")).status_code == 403


def test_join_views_are_immutable():
    assert ResourceRoutineAdmin.can_edit is False
    assert ResourceGroupMemberAdmin.can_edit is False
    assert "resource" in ResourceRoutineAdmin.form_columns
    assert "routine" in ResourceRoutineAdmin.form_columns
    assert "group" in ResourceGroupMemberAdmin.form_columns
    assert "resource" in ResourceGroupMemberAdmin.form_columns
