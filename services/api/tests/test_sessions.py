"""Session lifecycle against the FakeRunner (real Moto per sandbox, no Docker): start idempotency and
concurrency, active-session limit, capacity, console, progress, submit semantics, reset, stop."""

from __future__ import annotations

import asyncio
import io

from sqlalchemy import func, select

from app.config import get_settings
from app.db import sessionmaker
from app.models import Attempt, GradingEvidence, LabSession, SessionEvent, SessionState as S
from tests.conftest import all_sessions, idem, login, seed_runner_row, wait_state

BUCKET = "cafe-alice1-site"


async def ready_session(c, world) -> str:
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    await wait_state(c, sid, {"READY"})
    return sid


async def do_full_solution(c, sid: str) -> None:
    base = f"/api/sessions/{sid}/console/s3"
    assert (await c.post(f"{base}/buckets", json={"name": BUCKET})).status_code == 201
    assert (await c.put(f"{base}/buckets/{BUCKET}/versioning", json={"status": "Enabled"})).status_code == 200
    files = {"file": ("index.html", io.BytesIO(b"<h1>CloudCafe</h1>"), "text/html")}
    assert (await c.post(f"{base}/buckets/{BUCKET}/objects", files=files)).status_code == 201
    assert (await c.put(f"{base}/buckets/{BUCKET}/tags", json={"tags": {"project": "cloudcafe"}})).status_code == 200


# --------------------------------------------------------------------------------------- start
async def test_start_provisions_to_ready_with_baseline(world, fake_runner):
    c = await login(world.alice)
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 201 and r.json()["state"] == "REQUESTED"
    s = await wait_state(c, r.json()["id"], {"READY"})
    assert s["expires_at"] and s["idle_deadline_at"] and s["lab"]["tasks"][0]["title"].endswith(BUCKET)
    async with sessionmaker()() as db:
        events = (await db.scalars(select(SessionEvent.to_state).where(
            SessionEvent.session_id == s["id"]).order_by(SessionEvent.id))).all()
        assert events == ["REQUESTED", "PROVISIONING", "READY"]
        base = await db.scalar(select(GradingEvidence).where(GradingEvidence.session_id == s["id"],
                                                             GradingEvidence.kind == "baseline"))
        assert base is not None and base.payload["collectors"]["s3"]["buckets"] == {}
    # Secrets never leave the server.
    assert "ttyd" not in r.text and "credential" not in str(s) and "endpoint" not in str(s)


async def test_repeated_start_returns_same_session(world, fake_runner):
    c = await login(world.alice)
    r1 = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    r2 = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r1.status_code == 201 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"]


async def test_twenty_parallel_starts_create_one_session(world, fake_runner):
    clients = [await login(world.alice) for _ in range(4)]
    rs = await asyncio.gather(*[clients[i % 4].post(f"/api/assignments/{world.assignment.id}/sessions")
                                for i in range(20)])
    assert {r.status_code for r in rs} <= {200, 201}
    assert len({r.json()["id"] for r in rs}) == 1
    assert sum(r.status_code == 201 for r in rs) == 1
    assert len(await all_sessions()) == 1
    assert [c for c in fake_runner.calls if c[0] == "create"].__len__() == 1


async def test_active_session_limit_is_configurable(world, fake_runner, monkeypatch):
    # a second assignment in the same course
    from app.models import Assignment
    async with sessionmaker()() as db:
        a2 = Assignment(course_id=world.course.id, lab_version_id=world.lab_version.id, title="S3 again",
                        open_at=world.assignment.open_at, due_at=world.assignment.due_at,
                        close_at=world.assignment.close_at, max_attempts=3)
        db.add(a2)
        await db.commit()
    c = await login(world.alice)
    first = await ready_session(c, world)
    r = await c.post(f"/api/assignments/{a2.id}/sessions")
    assert r.status_code == 409 and r.json()["error"]["code"] == "other_session_active"
    assert r.json()["error"]["session_id"] == first
    monkeypatch.setattr(get_settings(), "max_active_sessions_per_student", 2)
    r = await c.post(f"/api/assignments/{a2.id}/sessions")
    assert r.status_code == 201


async def test_capacity_full_creates_nothing(world, fake_runner):
    await seed_runner_row(max_sandboxes=1)
    await ready_session(await login(world.alice), world)
    bob = await login(world.bob)
    r = await bob.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 503 and r.json()["error"]["code"] == "capacity_full"
    assert r.headers["Retry-After"] == "60"
    assert len(await all_sessions()) == 1


async def test_runtime_unavailable(world, fake_runner):
    await seed_runner_row(healthy=False)
    r = await (await login(world.alice)).post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 503 and r.json()["error"]["code"] == "runtime_unavailable"
    assert len(await all_sessions()) == 0


async def test_provision_failure_marks_failed_and_frees_the_slot(world, fake_runner):
    fake_runner.fail_create = "provision_error"
    c = await login(world.alice)
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    s = await wait_state(c, r.json()["id"], {"FAILED"})
    assert s["failure_reason"] == "provision_error"
    fake_runner.fail_create = None
    r2 = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r2.status_code == 201 and r2.json()["id"] != r.json()["id"]


# --------------------------------------------------------------------------- console + progress
async def test_console_and_progress(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    base = f"/api/sessions/{sid}/console/s3"
    assert (await c.post(f"{base}/buckets", json={"name": BUCKET})).status_code == 201
    r = await c.delete(f"{base}/buckets/no-such-bucket-here")
    assert r.status_code == 400 and r.json()["error"]["code"] == "aws_error"
    assert r.json()["error"]["aws_code"] == "NoSuchBucket"
    assert [b["name"] for b in (await c.get(f"{base}/buckets")).json()["buckets"]] == [BUCKET]
    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.status_code == 200 and p.json()["score"] == "25.00"
    p2 = await c.post(f"/api/sessions/{sid}/progress")
    assert p2.status_code == 429 and "Retry-After" in p2.headers
    details = (await c.get(f"{base}/buckets/{BUCKET}")).json()
    assert (details["name"], details["versioning"], details["tags"], details["region"]) == \
        (BUCKET, "Disabled", {}, "us-east-1")
    assert details["arn"] == f"arn:aws:s3:::{BUCKET}" and details["policy"] is None
    big = {"file": ("big.bin", io.BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "application/octet-stream")}
    assert (await c.post(f"{base}/buckets/{BUCKET}/objects", files=big)).status_code == 413


async def test_create_bucket_form_mirrors_aws_and_labels_simulator_limits(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    base = f"/api/sessions/{sid}/console/s3"
    r = await c.post(f"{base}/buckets", json={"name": "other-region", "region": "eu-west-1"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_in_simulator"
    r = await c.post(f"{base}/buckets", json={"name": "acl-bucket", "object_ownership": "ObjectWriter"})
    assert r.status_code == 400 and "ACLs are not available" in r.json()["error"]["message"]
    r = await c.post(f"{base}/buckets", json={
        "name": BUCKET, "region": "us-east-1", "object_ownership": "BucketOwnerEnforced",
        "block_public_access": True, "versioning": "Enabled", "tags": [{"key": "project", "value": "cloudcafe"}]})
    assert r.status_code == 201, r.text
    d = (await c.get(f"{base}/buckets/{BUCKET}")).json()
    assert d["versioning"] == "Enabled" and d["tags"] == {"project": "cloudcafe"}
    assert all(d["public_access_block"].values()) and d["access"] == "Bucket and objects not public"
    listing = (await c.get(f"{base}/buckets")).json()["buckets"]
    assert listing[0]["region"] == "us-east-1" and listing[0]["access"] == "Bucket and objects not public"
    # Permissions: turn Block Public Access off and attach a public-read policy → "Public"
    r = await c.put(f"{base}/buckets/{BUCKET}/public-access-block", json={
        "block_public_acls": False, "ignore_public_acls": False, "block_public_policy": False,
        "restrict_public_buckets": False})
    assert r.status_code == 200
    policy = ('{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*",'
              '"Action":"s3:GetObject","Resource":"arn:aws:s3:::' + BUCKET + '/*"}]}')
    assert (await c.put(f"{base}/buckets/{BUCKET}/policy", json={"policy": policy})).status_code == 200
    assert (await c.get(f"{base}/buckets/{BUCKET}")).json()["access"] == "Public"
    r = await c.put(f"{base}/buckets/{BUCKET}/policy", json={"policy": "not json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_policy"
    assert (await c.delete(f"{base}/buckets/{BUCKET}/policy")).status_code == 204
    # one-click creation through the form scores the relevant tasks
    await asyncio.sleep(0)
    p = await c.post(f"/api/sessions/{sid}/progress")
    assert p.json()["score"] == "75.00"  # bucket + versioning + tag, no index.html yet


async def test_other_student_cannot_touch_session(world, fake_runner):
    sid = await ready_session(await login(world.alice), world)
    bob = await login(world.bob)
    for method, url in [("GET", f"/api/sessions/{sid}"), ("POST", f"/api/sessions/{sid}/progress"),
                        ("POST", f"/api/sessions/{sid}/terminal-ticket"),
                        ("GET", f"/api/sessions/{sid}/console/s3/buckets"),
                        ("POST", f"/api/sessions/{sid}/stop")]:
        r = await bob.request(method, url)
        assert r.status_code == 404, (url, r.text)
    r = await bob.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 404


# ------------------------------------------------------------------------------------- submit
async def test_submit_full_solution_scores_100_with_evidence(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    await do_full_solution(c, sid)
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["score"] == "100.00" and body["attempt"]["counts"] is True
    assert "expected" not in str(body["result"])  # student view
    await wait_state(c, sid, {"TERMINATED"})
    assert sid not in fake_runner.sandboxes  # cleaned up
    async with sessionmaker()() as db:
        at = await db.scalar(select(Attempt).where(Attempt.session_id == sid))
        ev = await db.scalar(select(GradingEvidence).where(GradingEvidence.attempt_id == at.id))
        assert ev.kind == "final" and BUCKET in ev.payload["collectors"]["s3"]["buckets"]
        events = (await db.scalars(select(SessionEvent.to_state).where(SessionEvent.session_id == sid)
                                   .order_by(SessionEvent.id))).all()
        assert events[-5:] == ["READY", "SUBMITTING", "SUBMITTED", "TERMINATING", "TERMINATED"]
    # the lab is read-only afterwards
    r = await c.get(f"/api/sessions/{sid}/console/s3/buckets")
    assert r.status_code == 409


async def test_parallel_submits_create_one_attempt(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    await do_full_solution(c, sid)
    rs = await asyncio.gather(*[c.post(f"/api/sessions/{sid}/submit", headers=idem()) for _ in range(6)])
    codes = sorted(r.status_code for r in rs)
    assert codes.count(200) == 1 and all(x == 409 for x in codes if x != 200), [r.text for r in rs]
    async with sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(Attempt)) == 1


async def test_submit_idempotency_replay_and_reuse(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    h = idem()
    r1 = await c.post(f"/api/sessions/{sid}/submit", headers=h)
    r2 = await c.post(f"/api/sessions/{sid}/submit", headers=h)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert r2.headers.get("Idempotent-Replay") == "true"
    r3 = await c.post(f"/api/sessions/{sid}/reset", headers=h)  # same key, other request
    assert r3.status_code == 422 and r3.json()["error"]["code"] == "idempotency_key_reused"
    r4 = await c.post(f"/api/sessions/{sid}/submit")
    assert r4.status_code == 400 and r4.json()["error"]["code"] == "idempotency_key_required"


async def test_console_frozen_while_submitting(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    from app.sessions import state as st
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sid)
        assert await st.transition(db, sess, [S.READY], S.SUBMITTING, reason="submit", actor="test")
        await st.commit(db)
    r = await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})
    assert r.status_code == 409 and r.json()["error"]["code"] == "session_frozen"
    r = await c.post(f"/api/sessions/{sid}/reset", headers=idem())
    assert r.status_code == 409
    r = await c.post(f"/api/sessions/{sid}/terminal-ticket")
    assert r.status_code == 409


async def test_attempts_exhausted(world, fake_runner):
    async with sessionmaker()() as db:
        from app.models import Assignment
        a = await db.get(Assignment, world.assignment.id)
        a.max_attempts = 1
        await db.commit()
    c = await login(world.alice)
    sid = await ready_session(c, world)
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).status_code == 200
    await wait_state(c, sid, {"TERMINATED"})
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 409 and r.json()["error"]["code"] == "attempts_exhausted"


async def test_closed_assignment_refuses_start_and_submit(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    from datetime import timedelta
    from app.models import Assignment
    from app.sessions import state as st
    async with sessionmaker()() as db:
        a = await db.get(Assignment, world.assignment.id)
        a.due_at = st.now() - timedelta(minutes=2)
        a.close_at = st.now() - timedelta(minutes=1)
        await db.commit()
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 409 and r.json()["error"]["code"] == "closed"


# -------------------------------------------------------------------------------- reset / stop
async def test_reset_wipes_state_and_takes_new_baseline(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    base = f"/api/sessions/{sid}/console/s3"
    await c.post(f"{base}/buckets", json={"name": BUCKET})
    r = await c.post(f"/api/sessions/{sid}/reset", headers=idem())
    assert r.status_code == 200 and r.json()["state"] == "READY"
    assert (await c.get(f"{base}/buckets")).json()["buckets"] == []
    async with sessionmaker()() as db:
        n = await db.scalar(select(func.count()).select_from(GradingEvidence).where(
            GradingEvidence.session_id == sid, GradingEvidence.kind == "baseline"))
        assert n == 2
        assert await db.scalar(select(func.count()).select_from(Attempt)) == 0  # no attempt used


async def test_stop_ends_without_attempt(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    assert (await c.post(f"/api/sessions/{sid}/stop")).status_code == 200
    s = await wait_state(c, sid, {"TERMINATED"})
    assert s["attempt_id"] is None and sid not in fake_runner.sandboxes
