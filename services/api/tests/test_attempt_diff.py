"""Phase 10, milestone 48 — comparing two attempts (the "since your last attempt" panel).

Two things are proven here: the classification is right for every case (a pure unit over stored results),
and the API reads only stored grades — the same newest-grade row the results page shows, so a regrade is
reflected — while never exposing `expected`/`actual` to a student (PLAN §7b).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db import sessionmaker
from app.diff import compare, diff_for, latest_grade, previous_attempt
from app.models import Attempt, Grade
from tests.conftest import login, idem, wait_state
from tests.test_sessions import BUCKET, do_full_solution, ready_session

B = "/api/instructor/builder"
S3 = "/api/sessions/{sid}/console/s3"


# ------------------------------------------------------------------------------------ pure comparison
def _check(type_: str, passed: bool, actual: str, *, hidden=False, params=None):
    return {"task": "t1", "check": type_, "params": params or {"bucket": BUCKET},
            "expected": "yes", "actual": actual, "passed": passed, "hidden": hidden,
            "message": f"{type_} → {actual}",
            "marks_awarded": "5.00" if passed else "0.00", "marks_possible": "5.00"}


def _result(score: str, *checks):
    return {"score": score, "max_score": "25.00",
            "tasks": [{"task_id": "t1", "title": "Create the bucket", "passed": all(c["passed"] for c in checks),
                       "marks_awarded": "25.00", "marks_possible": "25.00", "checks": list(checks)}]}


def test_compare_classifies_every_change():
    before = _result("10.00",
                     _check("s3.bucket_exists", True, "exists"),
                     _check("s3.versioning", False, "Suspended"),
                     _check("s3.object_exists", True, "present"),
                     _check("s3.bucket_tag", False, "missing"),
                     _check("s3.audit_stub", False, "not recorded", hidden=True))
    after = _result("20.00",
                    _check("s3.bucket_exists", True, "exists"),        # unchanged
                    _check("s3.versioning", True, "Enabled"),          # fixed
                    _check("s3.object_exists", False, "missing"),      # regressed
                    _check("s3.upload_part", True, "present"),         # added (different type)
                    _check("s3.audit_stub", True, "recorded", hidden=True))   # fixed (hidden)

    out = compare(before, after, public=False)
    assert out["first_attempt"] is False
    rows = {r["check"]: r for r in out["tasks"][0]["checks"]}
    assert rows["s3.bucket_exists"]["change"] == "unchanged"
    assert rows["s3.versioning"]["change"] == "fixed"
    assert rows["s3.versioning"]["before"]["actual"] == "Suspended"
    assert rows["s3.versioning"]["after"]["actual"] == "Enabled"
    assert rows["s3.object_exists"]["change"] == "regressed"
    assert rows["s3.upload_part"]["change"] == "added" and rows["s3.upload_part"]["before"] is None
    assert rows["s3.bucket_tag"]["change"] == "removed" and rows["s3.bucket_tag"]["after"] is None
    assert rows["s3.audit_stub"]["change"] == "fixed"
    assert out["summary"] == {"fixed": 2, "regressed": 1, "unchanged": 1, "added": 1, "removed": 1,
                              "score_before": "10.00", "score_after": "20.00", "delta": "+10.00"}


def test_compare_is_public_by_default_and_never_leaks_expected_or_actual():
    before = _result("0.00", _check("s3.versioning", False, "Suspended", hidden=True))
    after = _result("25.00", _check("s3.versioning", True, "Enabled", hidden=True))

    student = compare(before, after, public=True)
    row = student["tasks"][0]["checks"][0]
    assert row["hidden"] is True and row["change"] == "fixed"
    for side in (row["before"], row["after"]):
        assert "expected" not in side and "actual" not in side and "params" not in side
    assert row["before"]["message"].startswith("A hidden requirement")
    assert row["after"]["message"] == "Hidden requirement met."
    assert "Create the bucket · Hidden requirement" in row["label"]

    staff = compare(before, after, public=False)
    staff_row = staff["tasks"][0]["checks"][0]
    assert staff_row["before"]["actual"] == "Suspended" and staff_row["after"]["actual"] == "Enabled"
    assert staff_row["before"]["expected"] == "yes"


def test_compare_of_a_first_attempt_is_empty_not_a_wall_of_additions():
    out = compare(None, _result("25.00", _check("s3.bucket_exists", True, "exists")), public=True)
    assert out["first_attempt"] is True and out["tasks"] == []
    assert out["summary"] == {"fixed": 0, "regressed": 0, "unchanged": 0, "added": 0, "removed": 0,
                              "score_before": None, "score_after": "25.00", "delta": None}


# ------------------------------------------------------------------------------ real attempts (DB)
async def submit_attempt(world, mode: str) -> str:
    """One graded attempt: 'empty' (nothing done), 'partial' (bucket + versioning) or 'full'."""
    c = await login(world.alice)
    sid = await ready_session(c, world)
    base = S3.format(sid=sid)
    if mode == "full":
        await do_full_solution(c, sid)
    elif mode == "partial":
        assert (await c.post(f"{base}/buckets", json={"name": BUCKET})).status_code == 201
        assert (await c.put(f"{base}/buckets/{BUCKET}/versioning", json={"status": "Enabled"})).status_code == 200
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    await wait_state(c, sid, {"TERMINATED"})
    return r.json()["attempt"]["id"]


async def student_diff(attempt_id: str):
    c = await login("alice@x.edu")
    r = await c.get(f"/api/attempts/{attempt_id}/diff")
    assert r.status_code == 200, r.text
    return r.json()


async def test_first_attempt_diff_is_graceful(world, fake_runner):
    a1 = await submit_attempt(world, "empty")
    out = await student_diff(a1)
    assert out["first_attempt"] is True and out["previous"] is None and out["tasks"] == []
    assert out["current"]["attempt_no"] == 1 and out["current"]["score"] == "0.00"
    assert out["summary"]["delta"] is None and out["summary"]["regressed"] == 0
    async with sessionmaker()() as db:
        assert await db.scalar(select(Grade).where(Grade.attempt_id == uuid.UUID(a1))) is not None


async def test_diff_reports_fixed_and_unchanged_between_two_attempts(world, fake_runner):
    a1 = await submit_attempt(world, "partial")     # bucket + versioning → 50
    a2 = await submit_attempt(world, "full")        # everything → 100
    out = await student_diff(a2)
    assert out["first_attempt"] is False
    assert out["previous"]["attempt_no"] == 1 and out["previous"]["score"] == "50.00"
    assert out["current"]["attempt_no"] == 2 and out["current"]["score"] == "100.00"
    assert out["summary"]["delta"] == "+50.00"
    changes = {r["check"]: r["change"] for t in out["tasks"] for r in t["checks"]}
    assert changes["s3.bucket_exists"] == "unchanged"
    assert changes["s3.versioning"] == "unchanged"
    assert changes["s3.object_exists"] == "fixed"
    assert changes["s3.bucket_tag"] == "fixed"
    assert changes["s3.object_content_type"] == "fixed"
    assert out["summary"]["regressed"] == 0 and out["summary"]["added"] == 0
    # the hidden check is named but never explained to a student
    hidden = next(r for t in out["tasks"] for r in t["checks"] if r["check"] == "s3.object_content_type")
    assert hidden["hidden"] is True and "Hidden requirement" in hidden["label"]
    for t in out["tasks"]:
        for r in t["checks"]:
            for side in (r["before"], r["after"]):
                if side:
                    assert "expected" not in side and "actual" not in side


async def test_diff_reports_regressed_and_negative_delta(world, fake_runner):
    a1 = await submit_attempt(world, "full")        # 100
    a2 = await submit_attempt(world, "empty")       # 0
    out = await student_diff(a2)
    assert out["summary"]["delta"] == "-100.00"
    changes = {r["check"]: r["change"] for t in out["tasks"] for r in t["checks"]}
    assert changes["s3.bucket_exists"] == "regressed"
    assert changes["s3.versioning"] == "regressed"
    assert changes["s3.object_exists"] == "regressed"
    assert changes["s3.bucket_tag"] == "regressed"
    assert out["summary"]["fixed"] == 0


async def test_diff_compares_only_against_attempts_that_counted(world, fake_runner):
    """An auto-submitted attempt that changed nothing (`counts=False`) never consumed the student's work,
    so it must be stepped over rather than reported as a wall of regressions. `attempts` is append-only, so
    the non-counting row is inserted directly, on its own (never submitted) session."""
    a1 = await submit_attempt(world, "partial")
    spare = await login(world.alice)
    spare_session = await ready_session(spare, world)     # started, never submitted
    async with sessionmaker()() as db:
        src = await db.get(Attempt, uuid.UUID(a1))
        db.add(Attempt(session_id=uuid.UUID(spare_session), user_id=src.user_id,
                       assignment_id=src.assignment_id, lab_version_id=src.lab_version_id,
                       attempt_no=2, trigger="idle", counts=False, late=False, score=Decimal("0.00"),
                       max_score=src.max_score, grader_version=src.grader_version, variables=src.variables))
        await db.commit()
    assert (await spare.post(f"/api/sessions/{spare_session}/stop", headers=idem())).status_code in (200, 204)

    a3 = await submit_attempt(world, "full")          # takes attempt_no 3

    out = await student_diff(a3)
    assert out["previous"]["attempt_no"] == 1 and out["previous"]["score"] == "50.00"
    assert out["current"]["attempt_no"] == 3 and out["current"]["score"] == "100.00"
    changes = {r["check"]: r["change"] for t in out["tasks"] for r in t["checks"]}
    assert changes["s3.bucket_exists"] == "unchanged"    # compared against attempt 1, not the gap


async def test_instructor_diff_includes_expected_and_actual_and_is_owner_scoped(world, fake_runner):
    a1 = await submit_attempt(world, "partial")
    a2 = await submit_attempt(world, "full")

    staff = await login(world.instructor)
    r = await staff.get(f"/api/instructor/attempts/{a2}/diff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["fixed"] == 3 and body["summary"]["delta"] == "+50.00"
    row = next(r_ for t in body["tasks"] for r_ in t["checks"] if r_["check"] == "s3.object_exists")
    assert row["change"] == "fixed"
    assert "expected" in row["before"] and "actual" in row["before"]
    assert row["before"]["actual"] != row["after"]["actual"]      # what changed, concretely

    # the student's copy of the same attempt never carries those fields (PLAN §7b)
    student = await student_diff(a2)
    srow = next(r_ for t in student["tasks"] for r_ in t["checks"] if r_["check"] == "s3.object_exists")
    assert "expected" not in srow["before"] and "actual" not in srow["before"]

    # another instructor doesn't teach the course → 404, not 403
    other = await login(world.other_instructor)
    assert (await other.get(f"/api/instructor/attempts/{a2}/diff")).status_code == 404
    # another student can't reach alice's attempt → 404
    bob = await login("bob@x.edu")
    assert (await bob.get(f"/api/attempts/{a2}/diff")).status_code == 404
    # an instructor route is not reachable by a student at all → 403
    assert (await bob.get(f"/api/instructor/attempts/{a2}/diff")).status_code == 403


async def test_diff_follows_the_newest_grade_after_a_regrade(world, fake_runner):
    """A regrade adds a `grades` row and never edits the old one; the diff must read the same newest row
    the results page shows, so per-check detail follows the regrade too."""
    a1 = await submit_attempt(world, "partial")     # 50
    a2 = await submit_attempt(world, "empty")       # 0
    before = await student_diff(a2)
    assert before["current"]["regraded"] is False
    assert before["summary"]["regressed"] == 2      # the bucket and the versioning check both dropped

    async with sessionmaker()() as db:
        original = await latest_grade(db, uuid.UUID(a2))
        assert original is not None and original.created_by is None
        tweaked = dict(original.result)
        tweaked["score"] = "75.00"                       # JSONB: strings, like `to_json` writes them
        tweaked["tasks"] = [dict(t) for t in tweaked["tasks"]]
        # simulate a grader-version correction that now passes the versioning check
        tweaked["tasks"][1] = {**tweaked["tasks"][1], "passed": True,
                               "checks": [{**c, "passed": True} if c["check"] == "s3.versioning" else c
                                          for c in tweaked["tasks"][1]["checks"]]}
        db.add(Grade(attempt_id=original.attempt_id, grader_version="9.9.9", score=Decimal("75.00"),
                     max_score=original.max_score, result=tweaked, created_by=world.instructor.id,
                     reason="grader corrected a false negative", created_at=datetime.now(timezone.utc)))
        await db.commit()

    after = await student_diff(a2)
    assert after["current"]["regraded"] is True
    assert after["current"]["score"] == "75.00"           # newest grade wins
    changes = {r["check"]: r["change"] for t in after["tasks"] for r in t["checks"]}
    assert changes["s3.versioning"] == "unchanged"        # the regrade cleared it on both sides
    assert changes["s3.bucket_exists"] == "regressed"
    assert after["summary"]["regressed"] == 1
    assert after["summary"]["score_after"] == "75.00" and after["summary"]["delta"] == "+25.00"


async def test_diff_reads_stored_rows_and_creates_nothing(world, fake_runner):
    """No sandbox is touched: the diff works after every session is gone."""
    a1 = await submit_attempt(world, "partial")
    a2 = await submit_attempt(world, "full")
    async with sessionmaker()() as db:
        assert (await db.scalar(select(Attempt.session_id).where(Attempt.id == uuid.UUID(a2)))) is not None
    out = await student_diff(a2)                          # all sessions TERMINATED, sandboxes destroyed
    assert out["summary"]["fixed"] == 3

    async with sessionmaker()() as db:
        at = await db.get(Attempt, uuid.UUID(a2))
        assert await previous_attempt(db, at) is not None
        again = await diff_for(db, at, public=True)       # deterministic: same stored rows, same answer
        assert again["summary"] == out["summary"] and again["tasks"] == out["tasks"]
