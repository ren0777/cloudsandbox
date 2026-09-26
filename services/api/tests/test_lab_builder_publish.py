"""Phase 8 — Lab Builder test run and publish gate (docs/NEXT.md milestone 37). The FakeRunner (real Moto per
sandbox) stands in for the runtime; its job hook applies a script's effect with boto3. The docker-marked test
at the end runs a cloned Mission 1 in real sandboxes."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from datetime import timedelta

import boto3
import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.db import sessionmaker
from app.labs import drafts as dr
from app.models import AuditEvent, Lab, LabDraft, LabVersion
from app.sessions import state as st
from app.sessions.reconciler import reconcile_once
from app.tasks import background
from tests.conftest import login, seed_runner_row

B = "/api/instructor/builder"
Action = Callable[[object, dict[str, str]], tuple[int, str]]


def create_bucket(s3, env: dict[str, str]) -> tuple[int, str]:
    s3.create_bucket(Bucket=env["BUCKET"])
    return 0, "make_bucket ok"


def s3_jobs(actions: dict[str, Action]) -> Callable[[str, dict[str, bytes]], tuple[int, str]]:
    """A FakeRunner job handler: reads the variables and script name from labtest's generated wrapper and
    applies the matching action to the sandbox's Moto with boto3."""
    def handler(endpoint: str, files: dict[str, bytes]) -> tuple[int, str]:
        run = files["_labtest_run.sh"].decode()
        env = {k: shlex.split(v)[0] for k, v in re.findall(r"^export (\w+)=(.+)$", run, re.M)}
        script = re.search(r"^bash (\S+)$", run, re.M)[1]  # type: ignore[index]
        s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
        return actions.get(script, lambda *_: (127, f"{script}: no fake action"))(s3, env)
    return handler


async def new_draft(c, **body) -> dict:
    r = await c.post(f"{B}/drafts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def run_test(c, draft_id: str) -> dict:
    r = await c.post(f"{B}/drafts/{draft_id}/test")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "testing" and r.json()["last_test"]["status"] == "running"
    await background.drain(60)
    return (await c.get(f"{B}/drafts/{draft_id}")).json()


async def audits(action: str) -> list[AuditEvent]:
    async with sessionmaker()() as db:
        return list((await db.scalars(select(AuditEvent).where(AuditEvent.action == action))).all())


# ------------------------------------------------------------------------------------ test run
async def test_test_run_passes_then_publish_creates_an_owned_private_version(world, fake_runner):
    fake_runner.job_handler = s3_jobs({"solution.sh": create_bucket})
    c = await login(world.instructor)
    d = await new_draft(c, title="Bucket basics")
    url = f"{B}/drafts/{d['id']}"

    r = await c.post(f"{url}/publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "test_required"

    d = await run_test(c, d["id"])
    lt = d["last_test"]
    assert d["status"] == "passed" and lt["status"] == "passed" and lt["error"] is None
    assert d["tested_sha256"] == lt["content_sha256"] == d["validation"]["content_sha256"]
    # every primary engine (the lab runs on 'default'), empty and solution, with per-check results
    assert [s["name"] for s in lt["scenarios"]] == ["moto/empty", "moto/solution", "floci/empty", "floci/solution"]
    by = {s["name"]: s for s in lt["scenarios"]}
    assert by["moto/empty"]["actual"] == "0.00" and by["moto/solution"]["actual"] == "100.00"
    check = by["moto/solution"]["tasks"][0]["checks"][0]
    assert check["check"] == "s3.bucket_exists" and check["passed"] is True
    assert not by["moto/empty"]["tasks"][0]["checks"][0]["passed"]
    assert len(lt["sandbox_ids"]) == 4 and not fake_runner.sandboxes  # every sandbox destroyed

    r = await c.post(f"{url}/publish")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["draft"]["status"] == "published" and out["lab_version"]["version"] == "1.0.0"
    assert out["draft"]["published_version_id"] == out["lab_version"]["id"]
    async with sessionmaker()() as db:
        lab = await db.scalar(select(Lab).where(Lab.slug == d["slug"]))
        assert lab.owner_id == world.instructor.id and lab.shared is False and lab.title == "Bucket basics"
        lv = await db.get(LabVersion, out["lab_version"]["id"])
        assert lv.content_sha256 == d["tested_sha256"]
    [ev] = await audits("lab.published")
    assert ev.actor_id == world.instructor.id and ev.details["version"] == "1.0.0"

    # published drafts are read-only; the lab is the author's (private until shared)
    assert (await c.post(f"{url}/publish")).json()["error"]["code"] == "draft_published"
    assert (await c.post(f"{url}/test")).json()["error"]["code"] == "draft_published"
    mine = (await c.get("/api/instructor/lab-versions")).json()["lab_versions"]
    assert any(v["id"] == out["lab_version"]["id"] for v in mine)
    other = await login(world.other_instructor)
    theirs = (await other.get("/api/instructor/lab-versions")).json()["lab_versions"]
    assert not any(v["id"] == out["lab_version"]["id"] for v in theirs)


async def test_publish_needs_a_passing_test_of_the_current_content(world, fake_runner):
    fake_runner.job_handler = s3_jobs({"solution.sh": create_bucket})
    c = await login(world.instructor)
    d = await new_draft(c)
    url = f"{B}/drafts/{d['id']}"
    d = await run_test(c, d["id"])
    assert d["status"] == "passed"

    # any edit (here only the private notes) invalidates the test
    r = await c.put(url, json={"files": {"private/notes.md": "Teaching notes"}})
    assert r.json()["status"] == "draft" and r.json()["validation"]["content_sha256"] != d["tested_sha256"]
    r = await c.post(f"{url}/publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "test_required"

    # even a passed status can't publish content other than what was tested
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(status="passed"))
        await db.commit()
    r = await c.post(f"{url}/publish")
    assert r.status_code == 409 and r.json()["error"]["code"] == "test_required"

    # an invalid draft can be neither tested nor published
    lab = d["content"]["lab"] | {"tasks": []}
    await c.put(url, json={"lab": lab})
    for op in ("test", "publish"):
        r = await c.post(f"{url}/{op}")
        assert r.status_code == 422 and r.json()["error"]["code"] == "lab_invalid" and r.json()["error"]["errors"]
    assert not await audits("lab.published")


async def test_a_wrong_solution_fails_the_test_and_blocks_publish(world, fake_runner):
    fake_runner.job_handler = s3_jobs({"solution.sh": lambda s3, env: (0, "did nothing")})
    c = await login(world.instructor)
    d = await new_draft(c)
    d = await run_test(c, d["id"])
    lt = d["last_test"]
    assert d["status"] == "failed" and lt["status"] == "failed"
    sol = next(s for s in lt["scenarios"] if s["name"] == "moto/solution")
    assert sol["ok"] is False and sol["expected"] == "100.00" and sol["actual"] == "0.00"
    assert "create-bucket" in sol["detail"]
    assert (await c.post(f"{B}/drafts/{d['id']}/publish")).json()["error"]["code"] == "test_required"

    # a script that exits non-zero is reported with its output
    fake_runner.job_handler = s3_jobs({"solution.sh": lambda s3, env: (1, "An error occurred (AccessDenied)")})
    d = await run_test(c, d["id"])
    sol = next(s for s in d["last_test"]["scenarios"] if s["name"] == "moto/solution")
    assert d["status"] == "failed" and sol["actual"] is None and "AccessDenied" in sol["detail"]


async def test_partial_scenario_is_run_when_the_draft_has_one(world, fake_runner):
    c = await login(world.instructor)
    d = await new_draft(c)
    lab = d["content"]["lab"]
    lab["tasks"].append({"id": "tag-it", "title": "Tag the bucket", "marks": 50, "hints": [],
                         "checks": [{"type": "s3.bucket_tag", "bucket": "{{ bucket }}", "key": "team", "value": "x"}]})
    lab["tasks"][0]["marks"] = 50
    lab["requires"] = ["s3:CreateBucket", "s3:PutBucketTagging"]

    def solution(s3, env):
        s3.create_bucket(Bucket=env["BUCKET"])
        s3.put_bucket_tagging(Bucket=env["BUCKET"], Tagging={"TagSet": [{"Key": "team", "Value": "x"}]})
        return 0, ""
    fake_runner.job_handler = s3_jobs({"solution.sh": solution, "partial.sh": create_bucket})
    r = await c.put(f"{B}/drafts/{d['id']}", json={"lab": lab, "files": {
        "private/partial.sh": "#!/bin/bash\naws s3 mb \"s3://$BUCKET\"\n",
        "private/expected.yaml": "empty: 0\npartial: 50\nsolution: 100\n"}})
    assert r.json()["validation"]["ok"], r.json()["validation"]
    d = await run_test(c, d["id"])
    assert d["status"] == "passed", d["last_test"]
    by = {s["name"]: s["actual"] for s in d["last_test"]["scenarios"]}
    assert by == {"moto/empty": "0.00", "moto/partial": "50.00", "moto/solution": "100.00",
                  "floci/empty": "0.00", "floci/partial": "50.00", "floci/solution": "100.00"}


async def test_runtime_failure_unlocks_the_draft_and_is_reported(world, fake_runner):
    fake_runner.fail_create = "runtime_unavailable"
    c = await login(world.instructor)
    d = await run_test(c, (await new_draft(c))["id"])
    assert d["status"] == "failed" and d["last_test"]["status"] == "error"
    assert "runtime" in d["last_test"]["error"]
    # the draft is editable again
    assert (await c.put(f"{B}/drafts/{d['id']}", json={"files": {"private/notes.md": "x"}})).status_code == 200


async def test_interrupted_run_is_reported_and_test_capacity_is_capped(world, fake_runner, monkeypatch):
    c = await login(world.instructor)
    d = await new_draft(c)
    old = (st.now() - timedelta(hours=2)).isoformat()
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(
            status="testing", last_test={"id": "x", "status": "running", "started_at": old, "sandbox_ids": []}))
        await db.commit()
    got = (await c.get(f"{B}/drafts/{d['id']}")).json()
    assert got["status"] == "failed" and got["last_test"]["status"] == "error"
    assert "interrupted" in got["last_test"]["error"]

    monkeypatch.setattr(get_settings(), "builder_max_concurrent_tests", 1)
    other = await new_draft(c)
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == other["id"]).values(
            status="testing", last_test={"id": "y", "status": "running", "started_at": st.now().isoformat(),
                                         "sandbox_ids": []}))
        await db.commit()
    r = await c.post(f"{B}/drafts/{d['id']}/test")
    assert r.status_code == 429 and r.json()["error"]["code"] == "test_capacity_full"


async def test_reconciler_keeps_sandboxes_of_running_tests(world, fake_runner):
    await seed_runner_row()
    c = await login(world.instructor)
    d = await new_draft(c)
    sid = "2b0f3f4e-1c55-5d2c-9a57-3f0d1f1a2b3c"
    await fake_runner.create_sandbox({"sandbox_id": sid, "env": get_settings().env,
                                      "terminal_credential": "labtest:x"})
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(
            status="testing", last_test={"id": "x", "status": "running", "started_at": st.now().isoformat(),
                                         "sandbox_ids": [sid]}))
        await db.commit()
    await reconcile_once()
    assert sid in fake_runner.sandboxes
    async with sessionmaker()() as db:
        await db.execute(update(LabDraft).where(LabDraft.id == d["id"]).values(status="failed"))
        await db.commit()
    await reconcile_once()
    assert sid not in fake_runner.sandboxes  # a leftover once the run is over


async def test_published_versions_are_immutable(world, fake_runner):
    fake_runner.job_handler = s3_jobs({"solution.sh": create_bucket})
    c = await login(world.instructor)
    d = await new_draft(c)
    await run_test(c, d["id"])
    pub = (await c.post(f"{B}/drafts/{d['id']}/publish")).json()["lab_version"]

    # a second draft with the same id and version can't be tested or published
    twin = await new_draft(c)
    r = await c.put(f"{B}/drafts/{twin['id']}", json={"lab": d["content"]["lab"] | {"title": "Twin"}})
    msgs = [e["message"] for e in r.json()["validation"]["errors"]]
    assert any("already published" in m for m in msgs), msgs
    assert (await c.post(f"{B}/drafts/{twin['id']}/test")).status_code == 422

    # cloning the published lab prepares 1.1.0, which tests and publishes as a new version
    nxt = await new_draft(c, source="clone", lab_version_id=pub["id"])
    assert nxt["content"]["lab"]["version"] == "1.1.0" and nxt["slug"] == pub["slug"]
    await run_test(c, nxt["id"])
    r = await c.post(f"{B}/drafts/{nxt['id']}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["lab_version"]["lab_id"] == pub["lab_id"] and r.json()["lab_version"]["version"] == "1.1.0"
    async with sessionmaker()() as db:
        versions = (await db.scalars(select(LabVersion.version).where(LabVersion.lab_id == pub["lab_id"]))).all()
    assert sorted(versions) == ["1.0.0", "1.1.0"]


async def test_other_instructors_cannot_test_or_publish(world, fake_runner):
    c = await login(world.instructor)
    d = await new_draft(c)
    other = await login(world.other_instructor)
    for op in ("test", "publish"):
        assert (await other.post(f"{B}/drafts/{d['id']}/{op}")).status_code == 404
    stu = await login(world.alice)
    assert (await stu.post(f"{B}/drafts/{d['id']}/test")).status_code == 403


def test_expectations_default_scenarios():
    d = dr.package(dr.blank_content("x-lab", "X")).definition
    expected, errors = dr.expectations(dr.draft_files(dr.blank_content("x-lab", "X")), d)
    assert not errors and {k: str(v) for k, v in expected.items()} == {"empty": "0.00", "solution": "100.00"}


# ------------------------------------------------------------------------ real sandboxes (docker)
@pytest.mark.docker
async def test_cloned_mission_1_tests_and_publishes_in_real_sandboxes(world, real_runner):
    """A clone of Mission 1 (s3-basics) scores 0 / 50 / 100 on every primary engine, then publishes."""
    c = await login(world.instructor)
    d = await new_draft(c, source="clone", lab_version_id=str(world.lab_version.id))
    assert d["validation"]["ok"], d["validation"]
    r = await c.post(f"{B}/drafts/{d['id']}/test")
    assert r.status_code == 202, r.text
    await background.drain(get_settings().builder_test_timeout_s)
    d = (await c.get(f"{B}/drafts/{d['id']}")).json()
    by = {s["name"]: s["actual"] for s in d["last_test"]["scenarios"]}
    assert d["status"] == "passed", d["last_test"]
    for eng in ("moto", "floci"):
        assert by[f"{eng}/empty"] == "0.00" and by[f"{eng}/partial"] == "50.00" and by[f"{eng}/solution"] == "100.00"
    r = await c.post(f"{B}/drafts/{d['id']}/publish")
    assert r.status_code == 200, r.text
