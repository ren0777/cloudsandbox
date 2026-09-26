"""Phase 5 — courses, roster CSV import (preview → commit), enrolments, forced password change, audit trail."""

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.audit import ACTIONS
from app.db import sessionmaker
from app.models import AuditEvent, Enrolment, Role, User
from tests.conftest import login

GOOD = "email,name\nnew1@x.edu,New One\nNEW2@x.edu , New Two\nbob@x.edu,Bob\n\n"


async def audits(action: str | None = None) -> list[AuditEvent]:
    async with sessionmaker()() as db:
        q = select(AuditEvent).order_by(AuditEvent.id)
        if action:
            q = q.where(AuditEvent.action == action)
        return list((await db.scalars(q)).all())


async def test_create_course_makes_instructor_staff_and_is_audited(world):
    c = await login(world.instructor)
    r = await c.post("/api/instructor/courses", json={"code": "cs202", "title": "Cloud 202"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["code"] == "CS202"
    assert (await c.post("/api/instructor/courses", json={"code": "CS202", "title": "dup"})).status_code == 409
    courses = (await c.get("/api/instructor/courses")).json()["courses"]
    assert "CS202" in [x["code"] for x in courses]
    roster = (await c.get(f"/api/instructor/courses/{cid}/roster")).json()
    assert [s["email"] for s in roster["staff"]] == ["inst@x.edu"] and roster["students"] == []
    [e] = await audits("course.created")
    assert (e.actor_id, e.actor_role, str(e.course_id), e.details["code"]) == (world.instructor.id, "instructor", cid, "CS202")
    stu = await login(world.alice)
    assert (await stu.post("/api/instructor/courses", json={"code": "X1", "title": "x"})).status_code == 403


async def test_roster_preview_row_level_validation(world):
    c = await login(world.instructor)
    base = f"/api/instructor/courses/{world.course.id}/roster"
    csv = ("Email,Name,Section\n"
           "ok@x.edu,Okay Student,A\n"
           "not-an-email,Broken,A\n"
           "OK@x.edu,Duplicate,A\n"
           "alice@x.edu,Alice Renamed,A\n"
           "inst@x.edu,Ian,A\n"
           "nobody@x.edu,,A\n"
           ",Missing,A\n"
           "extra@x.edu,Extra,A,surplus\n")
    r = (await c.post(f"{base}/preview", json={"csv": csv})).json()
    assert r["ok"] is False and r["preview_token"] is None and r["file_errors"] == []
    rows = {x["row"]: x for x in r["rows"]}
    assert rows[2]["status"] == "create" and rows[2]["warnings"] == ["ignored column(s): section"]
    assert rows[3]["status"] == "error" and "invalid email" in rows[3]["errors"][0]
    assert rows[4]["errors"] == ["duplicate of row 2"]
    assert rows[5]["status"] == "already_enrolled" and "keeps its name 'Alice'" in rows[5]["warnings"][1]
    assert rows[6]["errors"] == ["inst@x.edu is a instructor account, not a student"]
    assert rows[7]["errors"] == ["name is required to create a new student account"]
    assert rows[8]["errors"] == ["email is missing", "name is required to create a new student account"] or \
        rows[8]["errors"][0] == "email is missing"
    assert "header has 2 columns" not in str(rows[9]) and "4 values but the header has 3" in rows[9]["errors"][0]
    assert r["summary"] == {"rows": 8, "create": 1, "enrol": 0, "already_enrolled": 1, "error": 6}
    # nothing was written by a preview
    assert await audits() == []
    for bad, msg in [("", "Field required"), ("name\nx", "'email' column"), ("email,email\na@x.edu,a@x.edu", "repeats"),
                     ("email,name\n", "no student rows")]:
        rr = await c.post(f"{base}/preview", json={"csv": bad})
        body = rr.text
        assert msg.lower() in body.lower() or rr.status_code == 422, (bad, body)


async def test_roster_import_commit_credentials_and_first_sign_in(world):
    c = await login(world.instructor)
    base = f"/api/instructor/courses/{world.course.id}/roster"
    # import without (or with a stale) preview token is refused
    assert (await c.post(f"{base}/import", json={"csv": GOOD, "preview_token": "0" * 64})).status_code == 409
    p = (await c.post(f"{base}/preview", json={"csv": GOOD})).json()
    assert p["ok"] and p["summary"] == {"rows": 3, "create": 2, "enrol": 0, "already_enrolled": 1, "error": 0}
    changed = GOOD + "new3@x.edu,New Three\n"
    assert (await c.post(f"{base}/import", json={"csv": changed, "preview_token": p["preview_token"]})).status_code == 409
    r = await c.post(f"{base}/import", json={"csv": GOOD, "preview_token": p["preview_token"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["created"], out["enrolled"]) == (2, 0)
    creds = {x["email"]: x["temporary_password"] for x in out["credentials"]}
    assert set(creds) == {"new1@x.edu", "new2@x.edu"}
    roster = (await c.get(f"{base}")).json()["students"]
    assert {s["email"]: s["pending_first_sign_in"] for s in roster} == {
        "alice@x.edu": False, "bob@x.edu": False, "new1@x.edu": True, "new2@x.edu": True}
    [e] = await audits("roster.imported")
    assert sorted(e.details["created"]) == ["new1@x.edu", "new2@x.edu"] and e.details["already_enrolled"] == 1

    # re-importing the same file is harmless: everyone is already enrolled
    p2 = (await c.post(f"{base}/preview", json={"csv": GOOD})).json()
    assert p2["summary"]["already_enrolled"] == 3

    # the new student must change the temporary password before doing anything else
    stu = await login("new1@x.edu", creds["new1@x.edu"])
    me = (await stu.get("/api/auth/me")).json()
    assert me["must_change_password"] is True
    r = await stu.get("/api/me/assignments")
    assert r.status_code == 403 and r.json()["error"]["code"] == "password_change_required"
    assert (await stu.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "a-good-password"})).status_code == 400
    r = await stu.post("/api/auth/change-password", json={"current_password": creds["new1@x.edu"], "new_password": "a-good-password"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert (await stu.get("/api/me/assignments")).status_code == 200
    assert (await login("new1@x.edu", "a-good-password")).cookies


async def test_roster_import_all_or_nothing_when_state_changes(world):
    c = await login(world.instructor)
    base = f"/api/instructor/courses/{world.course.id}/roster"
    csv = "email,name\nlate@x.edu,Late\n"
    p = (await c.post(f"{base}/preview", json={"csv": csv})).json()
    # meanwhile the email becomes an instructor account → commit re-validates and refuses
    async with sessionmaker()() as db:
        from app.auth.routes import create_user
        await create_user(db, "late@x.edu", "Late", Role.instructor, "whatever-password")
        await db.commit()
    r = await c.post(f"{base}/import", json={"csv": csv, "preview_token": p["preview_token"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "roster_invalid"
    assert await audits("roster.imported") == []


async def test_roster_and_enrolments_are_course_scoped(world):
    other = await login(world.other_instructor)
    for method, path, body in [
        ("GET", f"/api/instructor/courses/{world.course.id}/roster", None),
        ("POST", f"/api/instructor/courses/{world.course.id}/roster/preview", {"csv": GOOD}),
        ("POST", f"/api/instructor/courses/{world.course.id}/enrolments", {"email": "alice@x.edu"}),
        ("DELETE", f"/api/instructor/courses/{world.course.id}/enrolments/{world.alice.id}", None),
    ]:
        r = await other.request(method, path, json=body)
        assert r.status_code == 404, (path, r.text)
    stu = await login(world.alice)
    assert (await stu.get(f"/api/instructor/courses/{world.course.id}/roster")).status_code == 403
    admin = await login(world.admin)
    assert (await admin.get(f"/api/instructor/courses/{world.course.id}/roster")).status_code == 200


async def test_enrolment_add_remove_audited(world, fake_runner):
    c = await login(world.instructor)
    base = f"/api/instructor/courses/{world.other_course.id}"
    admin = await login(world.admin)
    # enrol an existing student into another course (admin manages every course)
    assert (await admin.post(f"{base}/enrolments", json={"email": "ALICE@x.edu"})).status_code == 201
    assert (await admin.post(f"{base}/enrolments", json={"email": "alice@x.edu"})).status_code == 409
    assert (await admin.post(f"{base}/enrolments", json={"email": "inst@x.edu"})).status_code == 404
    # a student with a running lab can't be removed from that course
    from tests.conftest import wait_state
    stu = await login(world.alice)
    sid = (await stu.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(stu, sid, {"READY"})
    cb = f"/api/instructor/courses/{world.course.id}"
    r = await c.delete(f"{cb}/enrolments/{world.alice.id}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "session_active"
    assert (await stu.post(f"/api/sessions/{sid}/stop")).status_code == 200
    await wait_state(stu, sid, {"TERMINATED"})
    assert (await c.delete(f"{cb}/enrolments/{world.alice.id}")).status_code == 204
    assert (await c.delete(f"{cb}/enrolments/{world.alice.id}")).status_code == 404
    assert (await stu.get(f"/api/assignments/{world.assignment.id}")).status_code == 404
    async with sessionmaker()() as db:
        assert await db.get(Enrolment, (world.course.id, world.alice.id)) is None
    assert [(e.action, e.subject_user_id) for e in await audits() if e.action.startswith("enrolment")] == [
        ("enrolment.added", world.alice.id), ("enrolment.removed", world.alice.id)]


async def test_audit_events_are_append_only_for_the_app_role(world):
    c = await login(world.instructor)
    await c.post("/api/instructor/courses", json={"code": "AUD1", "title": "Audit"})
    async with sessionmaker()() as db:
        for sql in ("UPDATE audit_events SET action = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
            with pytest.raises(Exception):
                await db.execute(text(sql))
            await db.rollback()
    assert len(await audits("course.created")) == 1


def test_audit_action_names_are_a_fixed_set():
    from app import audit
    assert "roster.imported" in ACTIONS
    with pytest.raises(ValueError):
        audit.record(None, None, "made.up")  # type: ignore[arg-type]


async def test_regrade_and_overrides_write_audit_rows(world, fake_runner):
    from tests.conftest import idem, wait_state
    stu = await login(world.alice)
    sid = (await stu.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(stu, sid, {"READY"})
    att = (await stu.post(f"/api/sessions/{sid}/submit", headers=idem())).json()["attempt"]["id"]
    c = await login(world.instructor)
    assert (await c.post(f"/api/instructor/attempts/{att}/regrade", json={"reason": "checker fix"})).status_code == 200
    r = await c.post(f"/api/instructor/assignments/{world.assignment.id}/overrides", json={
        "user_id": str(world.alice.id), "extra_attempts": 1, "close_at_override": "2031-01-01T00:00:00Z",
        "reason": "sick leave"})
    assert r.status_code == 201, r.text
    evs = await audits()
    assert [e.action for e in evs] == ["grade.regraded", "attempts.granted", "deadline.extended"]
    assert all(e.subject_user_id == world.alice.id and e.assignment_id == world.assignment.id for e in evs)
    assert evs[0].details["reason"] == "checker fix" and evs[2].details["close_at"].startswith("2031-01-01")
    async with sessionmaker()() as db:
        u = await db.scalar(select(User).where(User.email == "alice@x.edu"))
        assert u is not None
