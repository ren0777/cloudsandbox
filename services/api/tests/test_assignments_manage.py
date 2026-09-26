"""Phase 5 — assignment create/update/delete by course staff, with audit rows."""

from __future__ import annotations

from datetime import timedelta

from app.sessions import state as st
from tests.conftest import login, wait_state
from tests.test_courses_roster import audits


def _iso(d):
    return d.isoformat()


async def test_create_update_delete_assignment_audited(world):
    c = await login(world.instructor)
    now = st.now()
    body = {"course_id": str(world.course.id), "lab_version_id": str(world.lab_version.id), "title": "Week 2",
            "open_at": _iso(now), "due_at": _iso(now + timedelta(days=3)), "close_at": _iso(now + timedelta(days=4))}
    r = await c.post("/api/instructor/assignments", json=body)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = await c.patch(f"/api/instructor/assignments/{aid}", json={
        "title": "Week 2: S3", "max_attempts": 5, "due_at": _iso(now + timedelta(days=5)),
        "close_at": _iso(now + timedelta(days=6)), "reason": "moved for the holiday"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["close_at", "due_at", "max_attempts", "title"]
    # no-op patch writes no audit row; invalid ordering is refused
    assert (await c.patch(f"/api/instructor/assignments/{aid}", json={"title": "Week 2: S3"})).json()["changed"] == []
    r = await c.patch(f"/api/instructor/assignments/{aid}", json={"due_at": _iso(now + timedelta(days=30))})
    assert r.status_code == 400
    assert (await c.patch(f"/api/instructor/assignments/{aid}", json={"title": None})).status_code == 400
    assert (await c.delete(f"/api/instructor/assignments/{aid}")).status_code == 204
    assert (await c.get(f"/api/instructor/assignments/{aid}/results")).status_code == 404
    evs = await audits()
    assert [e.action for e in evs] == ["assignment.created", "assignment.updated", "assignment.deleted"]
    upd = evs[1].details
    assert upd["reason"] == "moved for the holiday" and upd["changes"]["max_attempts"] == [3, 5]
    assert upd["changes"]["title"] == ["Week 2", "Week 2: S3"]


async def test_started_assignment_keeps_its_lab_version_and_cannot_be_deleted(world, fake_runner):
    stu = await login(world.alice)
    sid = (await stu.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(stu, sid, {"READY"})
    c = await login(world.instructor)
    url = f"/api/instructor/assignments/{world.assignment.id}"
    r = await c.patch(url, json={"lab_version_id": str(world.lab_version.id)})  # unchanged → fine
    assert r.status_code == 200 and r.json()["changed"] == []
    from app.db import sessionmaker
    from app.labs.importer import import_package
    from app.labs.package import load_pack
    from tests.conftest import LABS
    async with sessionmaker()() as db:
        other_lv, _ = await import_package(db, load_pack(f"{LABS}/dynamodb-basics"))
        await db.commit()
    r = await c.patch(url, json={"lab_version_id": str(other_lv.id)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "assignment_started"
    r = await c.delete(url)
    assert r.status_code == 409 and r.json()["error"]["code"] == "assignment_started"
    # extending the class deadline is still allowed (audited)
    close = st.now() + timedelta(days=10)
    assert (await c.patch(url, json={"close_at": _iso(close)})).status_code == 200
    assert [e.action for e in await audits()] == ["assignment.updated"]


async def test_assignment_management_is_course_scoped(world):
    other = await login(world.other_instructor)
    url = f"/api/instructor/assignments/{world.assignment.id}"
    assert (await other.patch(url, json={"title": "hijack"})).status_code == 404
    assert (await other.delete(url)).status_code == 404
    stu = await login(world.alice)
    assert (await stu.patch(url, json={"title": "x"})).status_code == 403
    assert await audits() == []
