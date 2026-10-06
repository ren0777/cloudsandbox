"""Phase 10, milestone 49 — instructor course analytics.

Two things matter most and are asserted directly: every figure is derived from stored rows (no sandbox is
ever touched — proven by reading them after all sandboxes are gone), and the endpoint issues a **fixed**
number of queries, so it does not become an N+1 as a class gets bigger.
"""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import event

from app.analytics import course_analytics
from app.config import get_settings
from app.db import engine, sessionmaker
from app.models import Assignment, Course, CourseStaff, Enrolment, LabSession, SessionState as S
from app.sessions import state as st
from tests.conftest import login, idem, wait_state
from tests.test_sessions import BUCKET, do_full_solution, ready_session

B = "/api/instructor"
S3 = "/api/sessions/{sid}/console/s3"


async def submit(world, mode: str) -> str:
    c = await login(world.alice)
    sid = await ready_session(c, world)
    if mode == "full":
        await do_full_solution(c, sid)
    elif mode == "partial":
        base = S3.format(sid=sid)
        assert (await c.post(f"{base}/buckets", json={"name": BUCKET})).status_code == 201
        assert (await c.put(f"{base}/buckets/{BUCKET}/versioning", json={"status": "Enabled"})).status_code == 200
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    await wait_state(c, sid, {"TERMINATED"})
    return r.json()["attempt"]["id"]


async def measured(fn):
    """Run `fn` and count the SQL statements it issued."""
    counts = {"n": 0}

    def before(*_a, **_k):
        counts["n"] += 1

    eng = engine().sync_engine
    event.listen(eng, "before_cursor_execute", before)
    try:
        out = await fn()
    finally:
        event.remove(eng, "before_cursor_execute", before)
    return out, counts["n"]


# ------------------------------------------------------------------------------------ empty state
async def test_analytics_of_a_course_with_no_labs_is_an_empty_state(world):
    async with sessionmaker()() as db:
        lonely = Course(code="EMPTY1", title="Nothing assigned yet")
        db.add(lonely)
        await db.flush()
        db.add(Enrolment(course_id=lonely.id, user_id=world.alice.id))
        db.add(CourseStaff(course_id=lonely.id, user_id=world.instructor.id))
        await db.commit()
        empty = await course_analytics(db, lonely)

    assert empty["totals"] == {"students": 1, "assignments": 0, "submissions": 0, "submission_rate": 0.0,
                               "late_submissions": 0, "interruptions": 0, "avg_score": None}
    assert empty["assignments"] == [] and empty["most_failed_tasks"] == [] and empty["most_missed_checks"] == []


# ------------------------------------------------------------------------- what the numbers say
async def test_analytics_reports_scores_attempts_time_and_missed_work(world, fake_runner):
    await submit(world, "partial")      # 50
    await submit(world, "full")         # 100

    async with sessionmaker()() as db:
        stats = await course_analytics(db, world.course)

    assert stats["course"]["code"] == world.course.code
    t = stats["totals"]
    assert t["students"] == 2                      # alice and bob are enrolled
    assert t["submissions"] == 1                   # only alice submitted
    assert t["submission_rate"] == 0.5
    assert t["avg_score"] == "100.00"              # grade policy "best"
    assert t["late_submissions"] == 0 and t["interruptions"] == 0

    (row,) = stats["assignments"]
    assert row["assignment_id"] == str(world.assignment.id)
    assert row["lab_title"] and row["max_score"] == "100.00"
    assert row["submitted"] == 1 and row["attempts"] == 2
    assert row["avg_attempts_used"] == "2.00" and row["avg_score"] == "100.00"
    assert row["avg_completion_minutes"] is not None and row["avg_completion_minutes"] >= 0
    assert row["interruptions"] == 0

    failed = {r["task_id"]: r for r in stats["most_failed_tasks"]}
    assert failed["upload-homepage"]["failed"] == 1 and failed["upload-homepage"]["attempts"] == 2
    assert failed["upload-homepage"]["failure_rate"] == 0.5
    assert failed["upload-homepage"]["task_title"].startswith("Upload")
    assert "tag-bucket" in failed and "enable-versioning" not in failed   # versioning was done in both

    checks = {r["check"]: r for r in stats["most_missed_checks"]}
    assert "s3.object_exists" in checks and checks["s3.object_exists"]["failed"] == 1
    assert checks["s3.object_exists"]["assignment_title"] == world.assignment.title
    # nothing failed on both attempts, so passing work never appears in these lists
    assert "s3.bucket_exists" not in checks


async def test_course_submission_rate_counts_every_student_assignment_pair(world, fake_runner):
    """Two assignments, two students: the course rate is over 4 possible submissions, not over 2 students
    (which reported 100% — or more than 100% — once a student submitted more than one lab)."""
    now = st.now()
    async with sessionmaker()() as db:
        second = Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id,
                            title="Second one", open_at=now - timedelta(hours=1),
                            due_at=now + timedelta(days=1), close_at=now + timedelta(days=2),
                            max_attempts=3)
        db.add(second)
        await db.commit()
    await submit(world, "full")                              # alice, first assignment
    await submit(replace(world, assignment=second), "full")  # alice, second assignment

    async with sessionmaker()() as db:
        stats = await course_analytics(db, world.course)

    t = stats["totals"]
    assert t["students"] == 2 and t["assignments"] == 2
    assert t["submissions"] == 2                   # alice twice, bob never
    assert t["submission_rate"] == 0.5             # 2 of 2 × 2
    assert [r["submission_rate"] for r in stats["assignments"]] == [0.5, 0.5]


async def test_analytics_separates_infrastructure_interruptions_from_student_failure(world, fake_runner):
    await submit(world, "partial")
    async with sessionmaker()() as db:
        # a sandbox the platform lost mid-lab: an interruption, never a student's failed attempt
        db.add(LabSession(user_id=world.bob.id, assignment_id=world.assignment.id,
                          lab_version_id=world.lab_version.id, runner_id=get_settings().runner_id,
                          env="test", state=S.FAILED, failure_reason="sandbox_lost",
                          variables={"student_short_id": "bob222"}, resources={}, ttl_minutes=45,
                          idle_minutes=20, created_at=st.now() - timedelta(minutes=5)))
        await db.commit()
        stats = await course_analytics(db, world.course)

    row = stats["assignments"][0]
    assert row["interruptions"] == 1
    assert row["interruption_reasons"] == {"sandbox_lost": 1}
    assert stats["totals"]["interruptions"] == 1
    # the interruption did not become a submission, an attempt, or a lower average
    assert row["submitted"] == 1 and row["attempts"] == 1
    assert row["avg_score"] == "50.00"


# ------------------------------------------------------------------------------ scope and cost
async def test_analytics_is_owner_scoped(world, fake_runner):
    await submit(world, "partial")
    other = await login(world.other_instructor)
    assert (await other.get(f"{B}/courses/{world.course.id}/analytics")).status_code == 404
    stu = await login(world.alice)
    assert (await stu.get(f"{B}/courses/{world.course.id}/analytics")).status_code == 403
    admin = await login(world.admin)
    assert (await admin.get(f"{B}/courses/{world.course.id}/analytics")).status_code == 200
    own = await login(world.instructor)
    assert (await own.get(f"{B}/courses/{world.course.id}/analytics")).status_code == 200
    csv_url = f"{B}/courses/{world.course.id}/analytics.csv"
    assert (await other.get(csv_url)).status_code == 404
    assert (await stu.get(csv_url)).status_code == 403
    assert (await admin.get(csv_url)).status_code == 200


async def test_analytics_csv_matches_the_page(world, fake_runner):
    """The export is the per-assignment table plus an "All labs" totals row, from the same computation as
    the JSON, and a title that looks like a spreadsheet formula is neutralised like the gradebook's."""
    await submit(world, "partial")
    await submit(world, "full")
    async with sessionmaker()() as db:
        a = await db.get(Assignment, world.assignment.id)
        a.title = "=HYPERLINK(\"x\")"
        await db.commit()

    c = await login(world.instructor)
    page = (await c.get(f"{B}/courses/{world.course.id}/analytics")).json()
    r = await c.get(f"{B}/courses/{world.course.id}/analytics.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "analytics" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert len(rows) == 2

    row, total = rows
    want = page["assignments"][0]
    assert row["assignment"] == "'=HYPERLINK(\"x\")"
    assert row["course_code"] == world.course.code and row["lab"] == want["lab_title"]
    assert row["max_score"] == "100.00" and row["submitted"] == "1" and row["counted_attempts"] == "2"
    assert row["submission_rate_pct"] == "50.0" and row["avg_score"] == "100.00"
    assert row["avg_attempts_used"] == "2.00" and row["interruptions"] == "0"

    assert total["assignment"] == "All labs"
    assert total["students"] == "2" and total["submitted"] == "1"
    assert total["submission_rate_pct"] == "50.0" and total["avg_score"] == page["totals"]["avg_score"]


async def test_analytics_issues_a_fixed_number_of_queries(world, fake_runner):
    """Not one query per student or per assignment: the whole view is the same handful of statements
    however much data is behind it."""
    await submit(world, "partial")
    instructor = await login(world.instructor)
    first, q1 = await measured(
        lambda: instructor.get(f"{B}/courses/{world.course.id}/analytics"))
    assert first.status_code == 200

    # a second assignment with its own attempts doubles the data behind the report
    now = st.now()
    async with sessionmaker()() as db:
        from app.models import Assignment
        db.add(Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id,
                          title="Second one", open_at=now - timedelta(hours=1),
                          due_at=now + timedelta(days=1), close_at=now + timedelta(days=2),
                          max_attempts=3))
        await db.commit()
    await submit(world, "full")

    second, q2 = await measured(
        lambda: instructor.get(f"{B}/courses/{world.course.id}/analytics"))
    assert second.status_code == 200 and len(second.json()["assignments"]) == 2
    assert q2 == q1, f"the query count grew with the data: {q1} → {q2}"
    assert q1 <= 20, f"the analytics view should be a fixed handful of queries, used {q1}"

    # and it reads rows, not sandboxes: everything is already stored
    async with sessionmaker()() as db:
        again = await course_analytics(db, world.course)
    assert again["totals"]["submissions"] == second.json()["totals"]["submissions"]
    assert Decimal(again["totals"]["avg_score"]) == Decimal(second.json()["totals"]["avg_score"])
