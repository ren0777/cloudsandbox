"""Phase 7 — multi-runner readiness: registration, heartbeats, scheduler (health, drain, engine, capacity, load,
concurrency), no migration, runner-lost reconciliation. Two FakeRunners play two runners."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.auth.routes import create_user
from app.db import sessionmaker
from app.models import Attempt, Enrolment, LabSession, Role, Runner
from app.runtime import fleet
from app.runtime.runner_client import set_runners
from app.sessions import reconciler
from app.sessions import state as st
from tests.conftest import PASSWORD, idem, login, wait_state
from tests.fakes import FakeRunner
from tests.test_courses_roster import audits

A, B = "runner-local-1", "runner-b"


@pytest.fixture
async def two_runners():
    fa, fb = FakeRunner(runner_id=A), FakeRunner(runner_id=B)
    set_runners({A: fa, B: fb})
    async with sessionmaker()() as db:
        db.add(Runner(id=B, url="http://runner-b:7070", max_sandboxes=4, status="unknown"))
        await db.commit()
    await fleet.heartbeat_once()
    yield fa, fb
    from app.tasks import background
    await background.drain(30)
    fa.shutdown()
    fb.shutdown()
    set_runners({})


async def runner(rid: str) -> Runner:
    async with sessionmaker()() as db:
        return await db.get(Runner, rid)


async def set_runner_fields(rid: str, **kw) -> None:
    async with sessionmaker()() as db:
        r = await db.get(Runner, rid)
        for k, v in kw.items():
            setattr(r, k, v)
        await db.commit()


async def students(world, n: int) -> list:
    out = []
    async with sessionmaker()() as db:
        for i in range(n):
            u = await create_user(db, f"s{i}@x.edu", f"Student {i}", Role.student, PASSWORD, short_id=f"st{i:04d}")
            await db.flush()
            db.add(Enrolment(course_id=world.course.id, user_id=u.id))
            out.append(u)
        await db.commit()
    return out


async def start(user, world) -> tuple[int, dict]:
    c = await login(user)
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    return r.status_code, r.json()


async def runner_of(sid: str) -> str:
    async with sessionmaker()() as db:
        return (await db.get(LabSession, uuid.UUID(sid))).runner_id


# ------------------------------------------------------------------------------------------ heartbeat
async def test_heartbeat_records_health_engines_and_memory(world, two_runners):
    fa, fb = two_runners
    b = await runner(B)
    assert (b.status, b.engines["floci"], b.mem_available_mib, b.cpu_count) == ("healthy", True, 4096, 4)
    assert b.last_heartbeat is not None and b.unreachable_since is None
    fb.healthy = False
    await fleet.heartbeat_once()
    b = await runner(B)
    # one missed beat: still schedulable (last good heartbeat is fresh), but the outage start is recorded
    assert b.status == "healthy" and b.unreachable_since is not None and "fake runner down" in b.last_error
    first = b.unreachable_since
    await set_runner_fields(B, last_heartbeat=st.now() - timedelta(minutes=5))
    await fleet.heartbeat_once()
    b = await runner(B)
    assert b.status == "unreachable" and b.unreachable_since == first  # stale → out; the outage start is kept
    fb.healthy = True
    fb.runner_id = "someone-else"
    await fleet.heartbeat_once()
    assert (await runner(B)).status == "misconfigured"
    fb.runner_id = B
    await fleet.heartbeat_once()
    assert (await runner(B)).status == "healthy" and (await runner(B)).unreachable_since is None


# ------------------------------------------------------------------------------------------ scheduler
async def test_scheduler_spreads_load_and_respects_drain_and_health(world, two_runners):
    users = await students(world, 4)
    placed = []
    for u in users[:2]:
        code, body = await start(u, world)
        assert code in (200, 201), body
        placed.append(await runner_of(body["id"]))
    assert sorted(placed) == sorted([A, B])  # least loaded first → one each

    await set_runner_fields(B, drain=True)
    code, body = await start(users[2], world)
    assert await runner_of(body["id"]) == A  # draining runner gets no new labs

    await set_runner_fields(B, drain=False, last_heartbeat=st.now() - timedelta(minutes=10))
    code, body = await start(users[3], world)
    assert await runner_of(body["id"]) == A  # stale heartbeat = unhealthy


async def test_scheduler_requires_engine_compatibility(world, two_runners):
    fa, fb = two_runners
    fa.engines = {"moto": True, "floci": False, "ministack": False}  # A lacks the default engine image
    await fleet.heartbeat_once()
    [u1, u2] = await students(world, 2)
    _, body = await start(u1, world)
    assert await runner_of(body["id"]) == B
    await set_runner_fields(B, drain=True)
    code, body = await start(u2, world)
    assert code == 503 and body["error"]["code"] == "runtime_unavailable"


async def test_concurrent_starts_never_overfill_a_runner(world, two_runners):
    fa, fb = two_runners
    fa.max_sandboxes = fb.max_sandboxes = 2
    fa.create_delay_s = fb.create_delay_s = 0.3
    await fleet.heartbeat_once()
    users = await students(world, 12)

    async def beats() -> None:  # heartbeats update runner rows while Starts schedule (the load test's deadlock)
        for _ in range(6):
            await fleet.heartbeat_once()
            await asyncio.sleep(0.05)
    *results, _ = await asyncio.gather(*(start(u, world) for u in users), beats())
    assert all(code != 500 for code, _ in results), results
    ok = [b for code, b in results if code in (200, 201)]
    full = [b for code, b in results if code == 503]
    assert len(ok) == 4 and len(full) == 8
    assert all(b["error"]["code"] == "capacity_full" for b in full)
    by_runner: dict[str, int] = {}
    for b in ok:
        rid = await runner_of(b["id"])
        by_runner[rid] = by_runner.get(rid, 0) + 1
    assert by_runner == {A: 2, B: 2}


# --------------------------------------------------------------------------------------- no migration
async def test_sessions_stay_on_their_runner(world, two_runners):
    fa, fb = two_runners
    await set_runner_fields(B, drain=True)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    assert await runner_of(sid) == A
    # A drains too; reset and submit still happen on A
    await set_runner_fields(A, drain=True)
    await set_runner_fields(B, drain=False)
    assert (await c.post(f"/api/sessions/{sid}/reset", headers=idem())).status_code in (200, 202)
    await wait_state(c, sid, {"READY"})
    assert ("reset", sid) in fa.calls and not any(s == sid for _, s in fb.calls)
    # A becomes unreachable: reset fails honestly instead of re-creating the lab elsewhere
    fa.healthy = False
    orig = fa.reset_sandbox

    async def down(*a, **kw):
        from app.runtime.runner_client import RunnerError
        raise RunnerError("runtime_unavailable", "runner unreachable", 503)
    fa.reset_sandbox = down
    r = await c.post(f"/api/sessions/{sid}/reset", headers=idem())
    assert r.status_code == 503 and r.json()["error"]["code"] == "reset_failed"
    fa.reset_sandbox = orig
    assert not any(s == sid for _, s in fb.calls) and await runner_of(sid) == A


# ---------------------------------------------------------------------------------------- runner lost
async def test_lost_runner_fails_its_sessions_and_cleans_up_when_back(world, two_runners, monkeypatch):
    fa, fb = two_runners
    await set_runner_fields(B, drain=True)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    await set_runner_fields(B, drain=False)
    bob = await login(world.bob)
    await set_runner_fields(A, drain=True)
    sid_b = (await bob.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(bob, sid_b, {"READY"})
    assert (await runner_of(sid), await runner_of(sid_b)) == (A, B)

    # A stops answering: first unreachable (sessions untouched), later lost
    fa.healthy = False
    orig_list = fa.list_sandboxes

    async def unreachable(*a, **kw):
        from app.runtime.runner_client import RunnerError
        raise RunnerError("runtime_unavailable", "runner unreachable", 503)
    fa.list_sandboxes = unreachable
    await fleet.heartbeat_once()
    await reconciler.reconcile_once()
    assert (await wait_state(c, sid, {"READY"}))["state"] == "READY"  # not lost yet: nothing pretended
    await set_runner_fields(A, unreachable_since=st.now() - timedelta(minutes=10),
                            last_heartbeat=st.now() - timedelta(minutes=10))
    await fleet.heartbeat_once()  # still down, heartbeat now stale → unreachable
    stats = await reconciler.reconcile_once()
    assert stats.get("runner_lost_failed") == 1
    s = await wait_state(c, sid, {"FAILED"})
    assert s["failure_reason"] == "runner_lost"
    async with sessionmaker()() as db:
        assert (await db.scalar(select(Attempt).where(Attempt.session_id == uuid.UUID(sid)))) is None  # no attempt used
    assert (await wait_state(bob, sid_b, {"READY"}))["state"] == "READY"  # other runner unaffected
    assert not any(s == sid for _, s in fb.calls)  # nothing migrated

    # A comes back with the old sandbox still there → destroyed as a leftover
    fa.healthy = True
    fa.list_sandboxes = orig_list
    await fleet.heartbeat_once()
    assert sid in fa.sandboxes
    stats = await reconciler.reconcile_once()
    assert stats.get("leftover_destroyed") == 1 and sid not in fa.sandboxes


async def test_lost_runner_closes_graded_sessions(world, two_runners):
    fa, fb = two_runners
    await set_runner_fields(B, drain=True)
    c = await login(world.alice)
    sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
    await wait_state(c, sid, {"READY"})
    # graded, but teardown can't reach the runner → stays TERMINATING
    orig = fa.destroy_sandbox

    async def down(*a, **kw):
        from app.runtime.runner_client import RunnerError
        raise RunnerError("runtime_unavailable", "runner unreachable", 503)
    fa.destroy_sandbox = down
    assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).status_code == 200
    await wait_state(c, sid, {"TERMINATING", "SUBMITTED"})
    fa.healthy = False
    await set_runner_fields(A, unreachable_since=st.now() - timedelta(minutes=10),
                            last_heartbeat=st.now() - timedelta(minutes=10))
    await fleet.heartbeat_once()
    stats = await reconciler.reconcile_once()
    assert stats.get("runner_lost_closed") == 1
    assert (await wait_state(c, sid, {"TERMINATED"}))["state"] == "TERMINATED"
    fa.destroy_sandbox = orig


# -------------------------------------------------------------------------------- registration / drain
async def test_admin_register_drain_retire_audited(world, two_runners, monkeypatch):
    fa, fb = two_runners

    class Probe:
        def __init__(self, runner_id, url, secret, timeout):
            self.answer = {"runner_id": "runner-c" if "good" in url else "wrong-id", "docker_ok": True,
                           "max_sandboxes": 6, "engines": {"floci": True}, "active": 0, "version": "1"}

        async def capacity(self):
            return self.answer

        async def aclose(self):
            pass
    monkeypatch.setattr(fleet, "HttpRunnerClient", Probe)
    admin = await login(world.admin)
    r = await admin.post("/api/admin/runners", json={"id": "runner-c", "url": "http://bad:7070", "secret": "x" * 20})
    assert r.status_code == 400 and r.json()["error"]["code"] == "runner_mismatch"
    r = await admin.post("/api/admin/runners", json={"id": "runner-c", "url": "http://good:7070", "secret": "s" * 24})
    assert r.status_code == 201, r.text
    assert r.json()["own_secret"] is True and r.json()["max_sandboxes"] == 6
    stored = await runner("runner-c")
    assert stored.secret_enc and "ssssssss" not in stored.secret_enc  # encrypted at rest

    url = "/api/admin/runners/runner-c"
    assert (await admin.delete(url)).status_code == 409  # must drain first
    assert (await admin.patch(url, json={"drain": True, "reason": "kernel upgrade"})).json()["safe_to_stop"] is True
    assert (await admin.delete(url)).json()["status"] == "retired"
    listing = (await admin.get("/api/admin/runners")).json()["runners"]
    assert {x["id"] for x in listing} == {A, B, "runner-c"}
    assert [e.action for e in await audits()] == ["runner.registered", "runner.drained", "runner.retired"]
    assert (await (await login(world.instructor)).get("/api/admin/runners")).status_code == 403


async def test_cli_drain_is_audited_as_operator(world, two_runners, capsys):
    assert await fleet._cli(["drain", B]) == 0
    assert "draining" in capsys.readouterr().out
    [e] = await audits("runner.drained")
    assert (e.actor_id, e.actor_role, e.details["via"]) == (None, "operator", "cli")
    assert (await runner(B)).drain is True


# ------------------------------------------------------------------------------ real runtime (2 runners)
R2_ID = os.environ.get("CL_RUNNER2_ID", "runner-local-2")
R2_URL = os.environ.get("CL_RUNNER2_URL", "http://runner2:7070")
R2_SECRET = os.environ.get("CL_RUNNER2_SECRET", "dev-runner2-secret-change-me")


@pytest.fixture
async def real_fleet():
    """Both compose runners (`--profile multi`), talking through real signed HTTP (no test override)."""
    import httpx

    from app.config import get_settings
    from app.runtime.runner_client import HttpRunnerClient, set_runner
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.get(f"{R2_URL}/v1/capacity")  # any answer (401 unsigned) means it is up
    except httpx.HTTPError:
        pytest.skip("runner2 is not running (docker compose --profile multi up -d runner2)")
    set_runner(None)
    await fleet.heartbeat_once()
    yield
    from app.tasks import background
    await background.drain(90)
    s = get_settings()
    for rid, url, secret in ((s.runner_id, s.runner_url, s.runner_secret), (R2_ID, R2_URL, R2_SECRET)):
        client = HttpRunnerClient(rid, url, secret, 60)
        for sb in await client.list_sandboxes(env=s.env):
            await client.destroy_sandbox(sb["sandbox_id"])
        await client.aclose()


@pytest.mark.docker
async def test_two_real_runners_schedule_isolate_and_clean_up(world, real_fleet):
    from app.config import get_settings
    from app.runtime.runner_client import client_for_id
    r2 = await fleet.register(R2_ID, R2_URL, R2_SECRET)
    assert r2.status == "healthy" and r2.engines.get("floci") and r2.secret_enc  # own secret, encrypted
    with pytest.raises(Exception):
        await fleet.register(R2_ID, R2_URL, "wrong-secret-wrong-secret")  # signature rejected

    s = get_settings()
    users = await students(world, 3)
    sids = []
    for u in users[:2]:
        c = await login(u)
        sid = (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["id"]
        await wait_state(c, sid, {"READY"}, timeout=180)
        sids.append((c, sid))
    placed = {await runner_of(sid) for _, sid in sids}
    assert placed == {s.runner_id, R2_ID}  # spread over both runners

    for c, sid in sids:  # each runner sees only its own sandboxes
        rid = await runner_of(sid)
        other = R2_ID if rid == s.runner_id else s.runner_id
        mine = {x["sandbox_id"] for x in await (await client_for_id(rid)).list_sandboxes(env=s.env)}
        theirs = {x["sandbox_id"] for x in await (await client_for_id(other)).list_sandboxes(env=s.env)}
        assert sid in mine and sid not in theirs

    # runner-local-2 runs in gateway mode (like a runner on another server): console, grading and the terminal
    # all reach its sandbox through the runner, and a wrong token gets nothing
    c2 = sid2 = None
    for c, sid in sids:
        if await runner_of(sid) == R2_ID:
            c2, sid2 = c, sid
    async with sessionmaker()() as db:
        sess2 = await db.get(LabSession, uuid.UUID(sid2))
    assert "/gw/" in sess2.emulator_endpoint and "/gw/" in sess2.terminal_endpoint
    bucket = f"cafe-{users[[s for _, s in sids].index(sid2)].short_id}-site"
    r = await c2.post(f"/api/sessions/{sid2}/console/s3/buckets", json={"name": bucket})
    assert r.status_code in (200, 201), r.text
    assert bucket in [b["name"] for b in (await c2.get(f"/api/sessions/{sid2}/console/s3/buckets")).json()["buckets"]]
    assert float((await c2.post(f"/api/sessions/{sid2}/progress")).json()["score"]) > 0
    import httpx
    wrong = sess2.emulator_endpoint.replace(sess2.emulator_endpoint.split("/")[-2], "not-the-token")
    async with httpx.AsyncClient() as h:
        assert (await h.get(f"{wrong}/")).status_code == 404
    import base64
    import json as _json

    import websockets

    from app.crypto import decrypt
    auth = base64.b64encode(decrypt(sess2.ttyd_cred_enc).encode()).decode()
    async with websockets.connect(sess2.terminal_endpoint, subprotocols=["tty"],
                                  additional_headers={"Authorization": f"Basic {auth}"}) as t:
        await t.send(_json.dumps({"AuthToken": auth, "columns": 100, "rows": 30}))
        await t.send(b"0" + b"echo GW_$((40+2))\r")
        seen = b""  # (the command above ends with a carriage return, like pressing Enter)
        async with asyncio.timeout(30):
            while b"GW_42" not in seen:
                frame = await t.recv()
                seen += frame if isinstance(frame, bytes) else frame.encode()

    await set_runner_fields(R2_ID, drain=True)
    c3 = await login(users[2])
    code, body = await start(users[2], world)
    assert code in (200, 201), body
    assert await runner_of(body["id"]) == s.runner_id  # drained runner took no new lab
    await wait_state(c3, body["id"], {"READY"}, timeout=180)

    for c, sid in sids + [(c3, body["id"])]:
        assert (await c.post(f"/api/sessions/{sid}/submit", headers=idem())).status_code == 200
        await wait_state(c, sid, {"TERMINATED"}, timeout=120)
    for rid in (s.runner_id, R2_ID):
        left = [x for x in await (await client_for_id(rid)).list_sandboxes(env=s.env)
                if x["sandbox_id"] in {sid for _, sid in sids} | {body["id"]}]
        assert left == [], (rid, left)
