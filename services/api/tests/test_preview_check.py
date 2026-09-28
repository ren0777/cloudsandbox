"""Phase 10, milestone 47 — running a **single** grading check against a draft's preview sandbox.

The point of these tests is what the feature must *not* do as much as what it does: the result must come
from the same check function and the same evidence the real grader uses, and it must never create an
attempt, grade, evidence row, badge or leaderboard event. The FakeRunner gives every preview a real Moto,
so all of this runs in the fast suite.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import sessionmaker
from app.grader import evidence as ev
from app.grader.checks import load_all
from app.grader.grade import collectors_for, grade, probes_for
from app.labs import drafts as dr
from app.labs.render import compute_variables
from app.models import Attempt, Grade, GradingEvidence, LabSession, SessionEvent, TaskResult, UserBadge
from tests.conftest import login, seed_runner_row

B = "/api/instructor/builder"
TASK = "create-bucket"


async def new_draft(c, **body) -> dict:
    r = await c.post(f"{B}/drafts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def start(c, draft_id: str) -> dict:
    r = await c.post(f"{B}/drafts/{draft_id}/preview-sandbox")
    assert r.status_code == 201, r.text
    return r.json()["preview"]


async def run(c, draft_id: str, task: str = TASK, check: int = 1):
    return await c.post(f"{B}/drafts/{draft_id}/preview-sandbox/check", json={"task": task, "check": check})


@pytest.fixture
def no_spacing(monkeypatch):
    """Tests that run a check more than once shouldn't wait out the rate limit."""
    monkeypatch.setattr(get_settings(), "preview_check_min_interval_s", 0.0)


async def nothing_graded() -> None:
    async with sessionmaker()() as db:
        for model in (LabSession, Attempt, Grade, TaskResult, GradingEvidence, SessionEvent, UserBadge):
            n = await db.scalar(select(func.count()).select_from(model))
            assert n == 0, f"a single check run must never create {model.__tablename__} rows ({n})"


# ------------------------------------------------------------------------------- what the check reports
async def test_single_check_runs_against_the_preview_and_grades_nothing(world, fake_runner, no_spacing):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Run one check")
    url = f"{B}/drafts/{d['id']}/preview-sandbox/check"
    assert d["preview_status"] == "stopped"                       # the Tasks tab uses this to enable the button

    r = await run(c, d["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "preview_not_running"

    p = await start(c, d["id"])
    assert (await c.get(f"{B}/drafts/{d['id']}")).json()["preview_status"] == "running"

    # an empty sandbox: the bucket the task asks for is missing
    r = await run(c, d["id"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ran" and out["engine"] == "moto"
    assert out["task"] == {"id": TASK, "title": "Create the S3 bucket lab-{}".format(world.instructor.short_id)}
    assert out["check"]["type"] == "s3.bucket_exists" and out["check"]["index"] == 1
    assert out["check"]["hidden"] is False and out["check"]["scoring"] == "all"
    assert out["check"]["marks_possible"] == "100.00"             # the whole task, one check
    assert out["passed"] is False
    assert out["expected"] == "exists" and out["actual"] == "missing"
    assert "was not found" in out["message"]
    assert out["params"]["bucket"] == f"lab-{world.instructor.short_id}"   # rendered, not "{{ bucket }}"

    # do the work in the console, run it again → the grader's own pass result
    bucket = f"lab-{world.instructor.short_id}"
    assert (await c.post(f"/api/sessions/{p['sandbox_id']}/console/s3/buckets",
                         json={"name": bucket})).status_code == 201
    out = (await run(c, d["id"])).json()
    assert out["status"] == "ran" and out["passed"] is True
    assert out["actual"] == "exists" and "exists" in out["message"]

    await nothing_graded()                                        # no attempt, grade, evidence or badge
    assert (await c.delete(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 204


async def test_single_check_gives_the_same_answer_as_the_real_grader(world, fake_runner, no_spacing):
    """Parity with `grade()`: identical passed/expected/actual/message/marks, from the same code path."""
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Parity")
    p = await start(c, d["id"])
    bucket = f"lab-{world.instructor.short_id}"
    assert (await c.post(f"/api/sessions/{p['sandbox_id']}/console/s3/buckets",
                         json={"name": bucket})).status_code == 201

    pkg = dr.package(d["content"])
    variables = compute_variables(pkg.definition, world.instructor.short_id)
    payload = await ev.capture(await endpoint_of(d["id"]), collectors_for(pkg.definition), p["engine"],
                               probes_for(pkg.definition, variables))
    graded = grade(pkg.definition, variables, payload)
    ref = graded["tasks"][0]["checks"][0]

    out = (await run(c, d["id"], task=graded["tasks"][0]["task_id"], check=1)).json()
    assert out["status"] == "ran"
    for field in ("passed", "expected", "actual", "message"):
        assert out[field] == ref[field], f"{field}: single check {out[field]!r} != grader {ref[field]!r}"
    assert out["check"]["marks_possible"] == str(ref["marks_possible"])   # JSON turns Decimal into a string
    assert out["check"]["type"] == ref["check"] and out["task"]["id"] == ref["task"]


async def endpoint_of(draft_id: str) -> str:
    from app.models import LabDraft
    async with sessionmaker()() as db:
        row = await db.get(LabDraft, uuid.UUID(draft_id))
        return row.last_preview["emulator_endpoint"]


async def test_single_check_marks_follow_the_task_scoring(world, fake_runner, no_spacing):
    """Two checks with equal weight share the task's marks — exactly the share `grade()` awards."""
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Shared marks")
    lab = d["content"]["lab"]
    lab["tasks"][0]["marks"] = 40
    lab["tasks"][0]["checks"] = [{"type": "s3.bucket_exists", "bucket": "{{ bucket }}"},
                                 {"type": "s3.bucket_exists", "bucket": "some-other-bucket"}]
    lab["tasks"][0]["scoring"] = "proportional"
    r = await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})
    assert r.status_code == 200, r.text
    await start(c, d["id"])

    for index in (1, 2):
        out = (await run(c, d["id"], check=index)).json()
        assert out["status"] == "ran"
        assert out["check"]["marks_possible"] == "20.00", out["check"]
    # the author's feedback replaces the check's own message when it fails
    lab["tasks"][0]["checks"][1]["feedback"] = "The second bucket is the one that must exist."
    r = await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})
    out = (await run(c, d["id"], check=2)).json()
    assert out["passed"] is False and out["message"] == "The second bucket is the one that must exist."


# ------------------------------------------------------------------------------- gating and blocking
async def test_single_check_is_owner_only(world, fake_runner, no_spacing):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Mine")
    await start(c, d["id"])

    other = await login(world.other_instructor)
    assert (await run(other, d["id"])).status_code == 404          # resource-level, 404 not 403
    stu = await login(world.alice)
    assert (await run(stu, d["id"])).status_code == 403            # lab_manage: role gate first
    admin = await login(world.admin)
    assert (await run(admin, d["id"])).status_code == 200          # an admin may inspect an author's preview


async def test_single_check_rejects_an_unknown_task_or_index(world, fake_runner, no_spacing):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Positional")
    await start(c, d["id"])
    r = await run(c, d["id"], task="no-such-task")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = await run(c, d["id"], check=7)
    assert r.status_code == 404
    assert (await run(c, d["id"], task=TASK, check=0)).status_code == 422   # 1-based


async def test_a_check_the_platform_cannot_answer_is_reported_clearly(world, fake_runner, no_spacing):
    """An unsupported check never reaches a half-run: the run answers with the same row-level errors the
    validation panel shows, so the author knows exactly what to change. (The draft is edited *after* the
    preview started — an invalid pack can't launch a sandbox in the first place.)"""
    load_all()
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Unsupported")
    await start(c, d["id"])

    lab = d["content"]["lab"]
    lab["tasks"][0]["checks"] = [{"type": "audit.called", "action": "s3:PutObject"}]
    saved = (await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab})).json()
    assert saved["validation"]["ok"] is False                    # saved, but refused by validation
    assert any("audit.called" in e["message"] for e in saved["validation"]["errors"])

    r = await run(c, d["id"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "lab_invalid"
    assert any("audit" in e["message"] for e in r.json()["error"]["errors"])

    # and an invalid pack can't launch a sandbox either
    await c.delete(f"{B}/drafts/{d['id']}/preview-sandbox")
    assert (await c.post(f"{B}/drafts/{d['id']}/preview-sandbox")).status_code == 422


def test_capability_block_names_the_unusable_operation():
    """Defence in depth: if a check's declared operations aren't usable on the preview engine, the run
    says which one instead of letting boto3 fail. `lambda:Invoke` is genuinely unusable on moto and
    floci (only MiniStack runs Lambda code), and S3 list operations are usable everywhere."""
    from app.instructor import preview as pv

    block = pv._capability_block("moto", "lambda.invoke_returns", ("lambda:Invoke",))
    assert block is not None and block["status"] == "blocked"
    assert block["check"] == "lambda.invoke_returns"
    assert block["reason"]["code"] == "not_in_simulator"
    assert block["reason"]["operation"] == "lambda:Invoke"
    assert block["reason"]["reads"] == ["lambda:Invoke"] and block["reason"]["message"]
    assert pv._capability_block("moto", "s3.bucket_exists", ("s3:ListBuckets",)) is None


async def test_single_check_runs_are_spaced_out(world, fake_runner, monkeypatch):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c, title="Spacing")
    await start(c, d["id"])
    monkeypatch.setattr(get_settings(), "preview_check_min_interval_s", 30.0)
    assert (await run(c, d["id"])).status_code == 200
    r = await asyncio.wait_for(run(c, d["id"]), timeout=10)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1
    await nothing_graded()
