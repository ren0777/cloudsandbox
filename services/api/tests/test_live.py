"""Phase 5 — live progress view and staff terminate/extend controls (audited, course-scoped)."""

from __future__ import annotations

from datetime import timedelta

from app.db import sessionmaker
from app.models import Attempt, LabSession
from app.sessions import state as st
from sqlalchemy import select
from tests.conftest import login, wait_state
from tests.test_courses_roster import audits

BUCKET = "cafe-alice1-site"


async def running(world, who=None) -> tuple:
    c = await login(who or world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    return c, sid


async def test_live_view_shows_running_sessions_with_latest_progress(world, fake_runner):
    stu, sid = await running(world)
    inst = await login(world.instructor)
    url = f"/api/instructor/courses/{world.course.id}/live"
    [row] = (await inst.get(url)).json()["sessions"]
    assert row["session_id"] == sid and row["state"] == "READY" and row["student"]["email"] == "alice@x.edu"
    assert row["progress"] is None and row["tasks_passed"] is None and row["tasks_total"] == 4
    assert row["expires_at"] and row["idle_deadline_at"]
    # the student's own "Check progress" is what staff see (staff never read the sandbox themselves)
    assert (await stu.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})).status_code in (200, 201)
    assert (await stu.post(f"/api/sessions/{sid}/progress")).status_code == 200
    [row] = (await inst.get(url)).json()["sessions"]
    assert row["tasks_passed"] >= 1 and row["progress"]["score"] != "0.00" and row["progress_at"]
    assert {t["task_id"] for t in row["progress"]["tasks"]} and "checks" not in row["progress"]["tasks"][0]
    # scoping
    assert (await (await login(world.other_instructor)).get(url)).status_code == 404
    assert (await stu.get(url)).status_code == 403


async def test_extend_running_session_capped_and_audited(world, fake_runner):
    _, sid = await running(world)
    inst = await login(world.instructor)
    async with sessionmaker()() as db:
        before = (await db.get(LabSession, sid)).expires_at
    r = await inst.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 30, "reason": "slow network in lab"})
    assert r.status_code == 200, r.text
    assert r.json()["added_minutes"] == 30
    async with sessionmaker()() as db:
        after = (await db.get(LabSession, sid)).expires_at
    assert after - before == timedelta(minutes=30)
    assert (await inst.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 90, "reason": "x y z"})).status_code == 422
    # keep extending until the platform cap (240 min lifetime) stops it
    codes = [(await inst.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 60, "reason": "again"})).status_code
             for _ in range(6)]
    assert codes[-1] == 409 and 200 in codes
    async with sessionmaker()() as db:
        s = await db.get(LabSession, sid)
        assert s.expires_at - (s.ready_at or s.created_at) <= timedelta(minutes=240)
    evs = await audits("session.extended")
    assert evs[0].details["added_minutes"] == 30 and evs[0].details["reason"] == "slow network in lab"
    assert all(str(e.session_id) == sid and e.subject_user_id == world.alice.id for e in evs)
    other = await login(world.other_instructor)
    assert (await other.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 5, "reason": "hijack"})).status_code == 404


async def test_extend_is_capped_by_the_assignment_close(world, fake_runner):
    _, sid = await running(world)
    async with sessionmaker()() as db:  # the class closes in 10 minutes
        from app.models import Assignment
        a = await db.get(Assignment, world.assignment.id)
        a.due_at = st.now() + timedelta(minutes=5)
        a.close_at = st.now() + timedelta(minutes=10)
        a.allow_late = True  # effective close = close_at (without late submissions it would be due_at)
        s = await db.get(LabSession, sid)
        s.expires_at = st.now() + timedelta(minutes=8)
        await db.commit()
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 30, "reason": "more time"})
    assert r.status_code == 200 and r.json()["added_minutes"] <= 2
    r = await inst.post(f"/api/instructor/sessions/{sid}/extend", json={"minutes": 30, "reason": "more time"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "extension_limit"


async def test_terminate_discard_uses_no_attempt(world, fake_runner):
    stu, sid = await running(world)
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/sessions/{sid}/terminate", json={"mode": "discard", "reason": "wrong lab"})
    assert r.status_code == 200, r.text
    s = await wait_state(stu, sid, {"TERMINATED"})
    assert s["state"] == "TERMINATED"
    async with sessionmaker()() as db:
        assert (await db.scalar(select(Attempt).where(Attempt.session_id == sid))) is None
    [e] = await audits("session.terminated")
    assert e.details["mode"] == "discard" and str(e.session_id) == sid
    # a second terminate on the finished session is refused and not audited
    r = await inst.post(f"/api/instructor/sessions/{sid}/terminate", json={"mode": "discard", "reason": "again"})
    assert r.status_code == 409
    assert len(await audits("session.terminated")) == 1


async def test_terminate_grade_counts_only_if_work_was_done(world, fake_runner):
    # untouched sandbox: graded as staff-ended, but not counted (same rule as automatic submits)
    stu, sid = await running(world)
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/sessions/{sid}/terminate", json={"mode": "grade", "reason": "class over"})
    assert r.status_code == 200, r.text
    assert r.json()["counts"] is False
    await wait_state(stu, sid, {"TERMINATED"})
    # with work done: counted
    stu, sid2 = await running(world)
    assert (await stu.post(f"/api/sessions/{sid2}/console/s3/buckets", json={"name": BUCKET})).status_code in (200, 201)
    r = await inst.post(f"/api/instructor/sessions/{sid2}/terminate", json={"mode": "grade", "reason": "class over"})
    assert r.status_code == 200 and r.json()["counts"] is True and float(r.json()["score"]) > 0
    async with sessionmaker()() as db:
        at = await db.scalar(select(Attempt).where(Attempt.session_id == sid2))
        assert at.trigger == "staff"
    evs = await audits("session.terminated")
    assert [e.details["mode"] for e in evs] == ["grade", "grade"] and evs[1].details["attempt_id"] == str(at.id)
