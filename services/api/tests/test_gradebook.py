"""Phase 5 — gradebook (cells, statuses, policy, regrades, extensions) and CSV export."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

from app.db import sessionmaker
from app.labs.importer import definition_of
from app.models import Assignment, Enrolment, StudentOverride
from app.sessions import state as st
from tests.conftest import idem, login, wait_state

BUCKET = "cafe-alice1-site"


async def submit_with_bucket(world, assignment_id, bucket: bool) -> str:
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{assignment_id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    if bucket:
        assert (await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})).status_code in (200, 201)
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    await wait_state(c, sid, {"TERMINATED"})
    return r.json()["attempt"]["id"]


async def late_assignment(world) -> Assignment:
    now = st.now()
    async with sessionmaker()() as db:
        a = Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id, title="Late one",
                       open_at=now - timedelta(days=3), due_at=now - timedelta(days=1), close_at=now + timedelta(days=1),
                       allow_late=True, max_attempts=2, grade_policy="latest")
        closed = Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id, title="Already closed",
                            open_at=now - timedelta(days=5), due_at=now - timedelta(days=4), close_at=now - timedelta(days=3),
                            max_attempts=1)
        future = Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id, title="Next week",
                            open_at=now + timedelta(days=5), due_at=now + timedelta(days=6), close_at=now + timedelta(days=7),
                            max_attempts=1)
        db.add_all([a, closed, future])
        await db.commit()
        return a


async def test_gradebook_cells_statuses_and_totals(world, fake_runner):
    late = await late_assignment(world)
    await submit_with_bucket(world, world.assignment.id, bucket=False)   # attempt 1 → 0
    best = await submit_with_bucket(world, world.assignment.id, bucket=True)  # attempt 2 → higher (best counts)
    await submit_with_bucket(world, late.id, bucket=True)
    async with sessionmaker()() as db:
        db.add(StudentOverride(assignment_id=world.assignment.id, user_id=world.bob.id, extra_attempts=2,
                               reason="sick", created_by=world.instructor.id))
        await db.commit()

    c = await login(world.instructor)
    g = (await c.get(f"/api/instructor/courses/{world.course.id}/gradebook")).json()
    titles = [a["title"] for a in g["assignments"]]
    assert titles == ["Already closed", "Late one", "S3 basics", "Next week"]
    ids = {a["title"]: a["id"] for a in g["assignments"]}
    rows = {r["user"]["email"]: r for r in g["students"]}
    alice, bob = rows["alice@x.edu"], rows["bob@x.edu"]
    main = alice["cells"][ids["S3 basics"]]
    assert main["status"] == "submitted" and main["attempts_used"] == 2 and main["attempts_allowed"] == 3
    assert main["attempt_id"] == best and float(main["score"]) > 0 and main["late"] is False
    assert main["percentage"] == str(round(float(main["score"]) * 100 / float(main["max_score"]), 1))
    assert [x["attempt_no"] for x in main["attempts"]] == [1, 2]
    lc = alice["cells"][ids["Late one"]]
    assert lc["status"] == "submitted" and lc["late"] is True and lc["submitted_at"]
    assert alice["cells"][ids["Already closed"]]["status"] == "missed"
    assert alice["cells"][ids["Next week"]]["status"] == "not_open"
    assert bob["cells"][ids["S3 basics"]]["status"] == "not_started"
    assert bob["cells"][ids["S3 basics"]]["attempts_allowed"] == 5  # 3 + override 2
    assert bob["total"] == "0" and bob["percentage"] == "0.0"
    from decimal import Decimal
    assert Decimal(alice["total"]) == Decimal(main["score"]) + Decimal(lc["score"])
    assert Decimal(alice["possible"]) == 4 * Decimal(main["max_score"])

    # a regrade changes what the gradebook shows (newest grade wins); "latest" policy honoured
    assert (await c.post(f"/api/instructor/attempts/{best}/regrade", json={"reason": "recheck"})).status_code == 200
    g2 = (await c.get(f"/api/instructor/courses/{world.course.id}/gradebook")).json()
    cell = {r["user"]["email"]: r for r in g2["students"]}["alice@x.edu"]["cells"][ids["S3 basics"]]
    assert cell["attempts"][1]["regraded"] is True
    # evidence drill-down lists tasks in the lab's order (not storage order)
    detail = (await c.get(f"/api/instructor/attempts/{best}")).json()
    assert [t["task_id"] for t in detail["tasks"]] == [t.id for t in definition_of(world.lab_version).tasks]


async def test_gradebook_csv_export_fields(world, fake_runner):
    await submit_with_bucket(world, world.assignment.id, bucket=True)
    async with sessionmaker()() as db:  # a student whose name would be a spreadsheet formula
        from app.auth.routes import create_user
        from app.models import Role
        evil = await create_user(db, "evil@x.edu", "=HYPERLINK(\"x\")", Role.student, "whatever-password")
        await db.flush()
        db.add(Enrolment(course_id=world.course.id, user_id=evil.id))
        await db.commit()
    c = await login(world.instructor)
    r = await c.get(f"/api/instructor/courses/{world.course.id}/gradebook.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="cs101-gradebook-' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert list(rows[0]) == ["student_name", "email", "student_id", "course", "assignment", "lab", "score", "max_score",
                             "percentage", "attempts_used", "attempts_allowed", "late", "submitted_at", "status"]
    alice = next(x for x in rows if x["email"] == "alice@x.edu")
    assert (alice["student_id"], alice["course"], alice["assignment"], alice["status"], alice["late"]) == \
        ("alice1", "CS101", "S3 basics", "submitted", "no")
    assert alice["attempts_used"] == "1" and alice["attempts_allowed"] == "3" and alice["submitted_at"]
    assert float(alice["percentage"]) == round(float(alice["score"]) * 100 / float(alice["max_score"]), 1)
    bob = next(x for x in rows if x["email"] == "bob@x.edu")
    assert (bob["score"], bob["percentage"], bob["late"], bob["status"]) == ("", "", "", "not_started")
    assert next(x for x in rows if x["email"] == "evil@x.edu")["student_name"].startswith("'=")
    one = await c.get(f"/api/instructor/assignments/{world.assignment.id}/grades.csv")
    assert one.status_code == 200 and len(list(csv.DictReader(io.StringIO(one.text.lstrip("﻿"))))) == 3


async def test_gradebook_is_course_scoped(world):
    other = await login(world.other_instructor)
    assert (await other.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 404
    assert (await other.get(f"/api/instructor/courses/{world.course.id}/gradebook.csv")).status_code == 404
    assert (await other.get(f"/api/instructor/assignments/{world.assignment.id}/grades.csv")).status_code == 404
    stu = await login(world.alice)
    assert (await stu.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 403
    admin = await login(world.admin)
    assert (await admin.get(f"/api/instructor/courses/{world.course.id}/gradebook")).status_code == 200
