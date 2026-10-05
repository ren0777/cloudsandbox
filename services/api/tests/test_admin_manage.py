"""Phase 5 — admin dashboard APIs: users, course staff, all sessions, audit log (admin + course-scoped)."""

from __future__ import annotations

from tests.conftest import PASSWORD, login, wait_state
from tests.test_courses_roster import audits


async def test_admin_user_management_audited(world):
    admin = await login(world.admin)
    users = (await admin.get("/api/admin/users")).json()
    assert users["totals"] == {"admin": 1, "instructor": 2, "student": 2}
    assert [u["email"] for u in (await admin.get("/api/admin/users?q=ALI")).json()["users"]] == ["alice@x.edu"]
    assert {u["role"] for u in (await admin.get("/api/admin/users?role=instructor")).json()["users"]} == {"instructor"}

    # create a staff account with a temporary password
    r = await admin.post("/api/admin/users", json={"email": "ta@x.edu", "name": "Tia TA", "role": "instructor"})
    assert r.status_code == 201, r.text
    tmp = r.json()["temporary_password"]
    assert (await admin.post("/api/admin/users", json={"email": "TA@x.edu", "name": "dup", "role": "student"})).status_code == 409
    ta = await login("ta@x.edu", tmp)
    assert (await ta.get("/api/instructor/courses")).json()["error"]["code"] == "password_change_required"

    # deactivate → signed out and can't sign in; reactivate
    bob = await login(world.bob)
    assert (await admin.patch(f"/api/admin/users/{world.bob.id}", json={"active": False, "reason": "left college"})).status_code == 200
    assert (await bob.get("/api/auth/me")).status_code == 401
    from tests.conftest import client
    c = client()
    assert (await c.post("/api/auth/login", json={"email": "bob@x.edu", "password": PASSWORD})).status_code == 401
    assert (await admin.patch(f"/api/admin/users/{world.bob.id}", json={"active": True})).status_code == 200
    assert (await login(world.bob)).cookies

    # role change applies immediately; admins can't change themselves
    inst2 = await login(world.other_instructor)
    assert (await admin.patch(f"/api/admin/users/{world.other_instructor.id}", json={"role": "student"})).status_code == 200
    assert (await inst2.get("/api/instructor/courses")).status_code in (401, 403)
    r = await admin.patch(f"/api/admin/users/{world.admin.id}", json={"active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "self_change"

    # password reset → temporary password, forced change
    r = await admin.post(f"/api/admin/users/{world.alice.id}/reset-password")
    assert r.status_code == 200
    assert (await c.post("/api/auth/login", json={"email": "alice@x.edu", "password": PASSWORD})).status_code == 401
    alice = await login("alice@x.edu", r.json()["temporary_password"])
    assert (await alice.get("/api/auth/me")).json()["must_change_password"] is True

    actions = [e.action for e in await audits()]
    assert actions == ["user.created", "user.deactivated", "user.reactivated", "user.role_changed", "user.password_reset"]
    ev = (await audits("user.role_changed"))[0]
    assert ev.details["previous"] == "instructor" and ev.details["role"] == "student"

    # none of this is available to instructors or students
    inst = await login(world.instructor)
    for path in ("/api/admin/users", "/api/admin/sessions", "/api/admin/audit", "/api/admin/courses"):
        assert (await inst.get(path)).status_code == 403


async def test_course_staff_management(world):
    admin = await login(world.admin)
    base = f"/api/admin/courses/{world.course.id}/staff"
    assert (await admin.post(base, json={"email": "alice@x.edu"})).status_code == 404  # not an instructor
    assert (await admin.post(base, json={"email": "inst@x.edu"})).status_code == 409   # already staff
    assert (await admin.post(base, json={"email": "inst2@x.edu"})).status_code == 201
    inst2 = await login(world.other_instructor)
    assert (await inst2.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 200
    assert (await admin.delete(f"{base}/{world.other_instructor.id}")).status_code == 204
    assert (await inst2.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 404
    courses = (await admin.get("/api/admin/courses")).json()["courses"]
    assert {c["code"]: [s["email"] for s in c["staff"]] for c in courses} == {"CS101": ["inst@x.edu"], "CS999": ["inst2@x.edu"]}
    assert [e.action for e in await audits()] == ["course.staff_added", "course.staff_removed"]


async def test_admin_sessions_kill_is_audited(world, fake_runner):
    stu = await login(world.alice)
    sid = (await stu.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(stu, sid, {"READY"})
    admin = await login(world.admin)
    [s] = (await admin.get("/api/admin/sessions")).json()["sessions"]
    assert (s["session_id"], s["student"]["email"], s["course"]["code"], s["state"]) == (sid, "alice@x.edu", "CS101", "READY")
    assert (await admin.post(f"/api/admin/sessions/{sid}/kill")).status_code == 200
    await wait_state(stu, sid, {"TERMINATED"})
    [e] = await audits("session.terminated")
    assert e.actor_role == "admin" and str(e.session_id) == sid and e.course_id == world.course.id
    status = (await admin.get("/api/admin/runtime-status")).json()
    assert {"healthy", "drain", "engines", "in_use", "mem_available_mib"} <= set(status["runners"][0])


async def test_audit_log_admin_and_course_scoped(world):
    inst = await login(world.instructor)
    other = await login(world.other_instructor)
    await inst.post(f"/api/instructor/courses/{world.course.id}/enrolments", json={"email": "bob@x.edu"})  # 409, no audit
    await inst.delete(f"/api/instructor/courses/{world.course.id}/enrolments/{world.bob.id}")
    await other.post(f"/api/instructor/courses/{world.other_course.id}/enrolments", json={"email": "bob@x.edu"})
    admin = await login(world.admin)
    log = (await admin.get("/api/admin/audit")).json()
    assert [e["action"] for e in log["events"]] == ["enrolment.added", "enrolment.removed"]  # newest first
    assert log["events"][1]["actor"] == "Ian Instructor" and log["events"][1]["subject"] == "Bob"
    assert log["events"][1]["course"] == "CS101" and "roster.imported" in log["actions"]
    only = (await admin.get("/api/admin/audit?action=enrolment.added")).json()["events"]
    assert [e["course"] for e in only] == ["CS999"]
    page = (await admin.get("/api/admin/audit?limit=1")).json()
    assert len(page["events"]) == 1 and page["next_before"]
    page2 = (await admin.get(f"/api/admin/audit?limit=1&before={page['next_before']}")).json()
    assert page2["events"][0]["action"] == "enrolment.removed"
    # instructors see their own course's audit only
    mine = (await inst.get(f"/api/instructor/courses/{world.course.id}/audit")).json()["events"]
    assert [e["action"] for e in mine] == ["enrolment.removed"]
    assert (await inst.get(f"/api/instructor/courses/{world.other_course.id}/audit")).status_code == 404
    stu = await login(world.alice)
    assert (await stu.get(f"/api/instructor/courses/{world.course.id}/audit")).status_code == 403


async def test_admin_creates_course_with_first_instructor(world):
    admin = await login(world.admin)
    r = await admin.post("/api/instructor/courses", json={"code": "cs341", "title": "Cloud", "instructor_email": "INST2@x.edu"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    courses = {c["code"]: [s["email"] for s in c["staff"]] for c in (await admin.get("/api/admin/courses")).json()["courses"]}
    assert courses["CS341"] == ["inst2@x.edu"]
    assert (await (await login(world.other_instructor)).get(f"/api/instructor/courses/{cid}/roster")).status_code == 200
    assert [e.action for e in await audits()] == ["course.created", "course.staff_added"]
    # unknown or non-instructor email: nothing is created
    r = await admin.post("/api/instructor/courses", json={"code": "cs342", "title": "x", "instructor_email": "alice@x.edu"})
    assert r.status_code == 404
    assert "CS342" not in {c["code"] for c in (await admin.get("/api/admin/courses")).json()["courses"]}
    # instructors can't pick someone else as instructor
    inst = await login(world.instructor)
    r = await inst.post("/api/instructor/courses", json={"code": "cs343", "title": "x", "instructor_email": "inst2@x.edu"})
    assert r.status_code == 403
