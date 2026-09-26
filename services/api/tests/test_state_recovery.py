"""State machine exhaustiveness, append-only evidence, regrade, reconciler (PLAN §3 table), expiry
auto-submit + attempt accounting, instructor results/evidence/reopen."""

from __future__ import annotations

import io
import itertools
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.db import sessionmaker
from app.models import (
    Attempt,
    Grade,
    GradingEvidence,
    LabSession,
    SessionEvent,
    SessionState as S,
    StudentOverride,
    TaskResult,
)
from app.sessions import state as st
from app.sessions.reconciler import reconcile_once
from app.tasks import background
from app.tasks.janitor import expire_once
from tests.conftest import idem, login, wait_state
from tests.test_sessions import BUCKET, do_full_solution, ready_session

ALL = list(S)


# ------------------------------------------------------------------------------ state machine
async def _mk_session(world, state: S) -> LabSession:
    async with sessionmaker()() as db:
        s = LabSession(user_id=world.alice.id, assignment_id=world.assignment.id,
                       lab_version_id=world.lab_version.id, runner_id="runner-local-1", env="test",
                       state=state, variables={"student_short_id": "alice1", "bucket": BUCKET},
                       resources={}, ttl_minutes=45, idle_minutes=20)
        db.add(s)
        await db.commit()
        return s


@pytest.mark.parametrize("frm,to", list(itertools.product(ALL, ALL)))
async def test_every_transition_pair(world, frm, to):
    sess = await _mk_session(world, frm)
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, sess.id)
        if st.is_allowed(frm, to):
            assert await st.transition(db, sess, [frm], to, reason="t", actor="test")
            await st.commit(db)
            assert sess.state == to
        else:
            with pytest.raises(st.IllegalTransition):
                await st.transition(db, sess, [frm], to, reason="t", actor="test")


async def test_cas_fails_when_state_moved(world):
    sess = await _mk_session(world, S.READY)
    async with sessionmaker()() as a, sessionmaker()() as b:
        sa, sb = await a.get(LabSession, sess.id), await b.get(LabSession, sess.id)
        assert await st.transition(a, sa, [S.READY], S.SUBMITTING, reason="submit", actor="a")
        await st.commit(a)
        assert not await st.transition(b, sb, [S.READY], S.RESETTING, reason="reset", actor="b")
    async with sessionmaker()() as db:
        n = await db.scalar(select(func.count()).select_from(SessionEvent).where(SessionEvent.session_id == sess.id))
        assert n == 1


# --------------------------------------------------------------------------- immutable evidence
async def _submitted(world, fake_runner, full: bool = True) -> tuple[object, str, dict]:
    c = await login(world.alice)
    sid = await ready_session(c, world)
    if full:
        await do_full_solution(c, sid)
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200, r.text
    return c, sid, r.json()


@pytest.mark.parametrize("table", ["grading_evidence", "attempts", "task_results", "grades", "session_events"])
async def test_append_only_tables_reject_update_and_delete(world, fake_runner, table):
    await _submitted(world, fake_runner)
    async with sessionmaker()() as db:  # app role
        for sql in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(DBAPIError):
                await db.execute(text(sql))
            await db.rollback()


async def test_owner_is_blocked_by_trigger_too(world, fake_runner):
    await _submitted(world, fake_runner)
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import get_settings
    eng = create_async_engine(get_settings().database_owner_url)
    try:
        async with eng.connect() as conn:
            with pytest.raises(DBAPIError) as e:
                await conn.execute(text("UPDATE grading_evidence SET kind = 'final'"))
            assert "append-only" in str(e.value)
    finally:
        await eng.dispose()


async def test_regrade_adds_row_and_keeps_original(world, fake_runner):
    _, sid, body = await _submitted(world, fake_runner)
    attempt_id = body["attempt"]["id"]
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/attempts/{attempt_id}/regrade", json={"reason": "re-check"})
    assert r.status_code == 200 and r.json()["score"] == "100.00"
    async with sessionmaker()() as db:
        grades = (await db.scalars(select(Grade).where(Grade.attempt_id == attempt_id)
                                   .order_by(Grade.created_at))).all()
        assert [g.reason for g in grades] == ["initial", "re-check"]
        assert grades[0].result == grades[1].result  # same evidence -> same result
        assert grades[1].created_by == world.instructor.id


async def test_instructor_sees_per_check_evidence(world, fake_runner):
    _, sid, body = await _submitted(world, fake_runner, full=False)
    inst = await login(world.instructor)
    res = (await inst.get(f"/api/instructor/assignments/{world.assignment.id}/results")).json()
    alice = next(s for s in res["students"] if s["user"]["short_id"] == "alice1")
    assert alice["final_score"] == "0.00" and alice["attempts_used"] == 1
    d = (await inst.get(f"/api/instructor/attempts/{body['attempt']['id']}")).json()
    chk = d["tasks"][0]["checks"][0]
    assert chk["expected"] == "exists" and chk["actual"] == "missing" and chk["passed"] is False
    assert d["evidence"]["final"]["sha256"] and d["evidence"]["baselines"]
    assert [e["to"] for e in d["events"]][:3] == ["REQUESTED", "PROVISIONING", "READY"]


# -------------------------------------------------------------------------------- expiry
async def _expire_now(sid: str, field: str = "expires_at") -> None:
    async with sessionmaker()() as db:
        vals = {field: st.now() - timedelta(minutes=(1 if field == "expires_at" else 60))}
        await db.execute(update(LabSession).where(LabSession.id == sid).values(**vals))
        await db.commit()


async def test_ttl_expiry_unchanged_state_does_not_count(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    await _expire_now(sid)
    due = await expire_once()
    assert due == [(sid, "ttl")]
    async with sessionmaker()() as db:
        at = await db.scalar(select(Attempt).where(Attempt.session_id == sid))
        assert at.trigger == "ttl" and at.counts is False
    await background.drain()
    assert (await wait_state(c, sid, {"TERMINATED"}))["attempt_id"] == str(at.id)
    card = (await c.get(f"/api/assignments/{world.assignment.id}")).json()
    assert card["attempts_used"] == 0


async def test_idle_expiry_with_changes_counts(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    await c.post(f"/api/sessions/{sid}/console/s3/buckets", json={"name": BUCKET})
    await _expire_now(sid, "last_activity_at")
    assert await expire_once() == [(sid, "idle")]
    async with sessionmaker()() as db:
        at = await db.scalar(select(Attempt).where(Attempt.session_id == sid))
        assert at.trigger == "idle" and at.counts is True and str(at.score) == "25.00"


async def test_expiry_never_touches_non_ready(world, fake_runner):
    sess = await _mk_session(world, S.SUBMITTING)
    async with sessionmaker()() as db:
        await db.execute(update(LabSession).where(LabSession.id == sess.id)
                         .values(expires_at=st.now() - timedelta(hours=1)))
        await db.commit()
    assert await expire_once() == []


# ------------------------------------------------------------------------------ reconciler
async def _set(sid, **vals) -> None:
    async with sessionmaker()() as db:
        await db.execute(update(LabSession).where(LabSession.id == sid).values(**vals))
        await db.commit()


async def _state(sid) -> LabSession:
    async with sessionmaker()() as db:
        return await db.get(LabSession, sid)


async def test_reconcile_provisioning_timeout(world, fake_runner):
    sess = await _mk_session(world, S.PROVISIONING)
    await _set(sess.id, state_deadline_at=st.now() - timedelta(seconds=1))
    await reconcile_once()
    s = await _state(sess.id)
    assert s.state == S.FAILED and s.failure_reason == "provision_timeout"


async def test_reconcile_stale_requested(world, fake_runner):
    sess = await _mk_session(world, S.REQUESTED)
    await _set(sess.id, created_at=st.now() - timedelta(minutes=5))
    await reconcile_once()
    assert (await _state(sess.id)).failure_reason == "provision_timeout"


@pytest.mark.parametrize("oom", [False, True])
async def test_reconcile_ready_sandbox_lost(world, fake_runner, oom):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    fake_runner.kill(sid, oom=oom)
    await reconcile_once()
    s = await _state(sid)
    assert s.state == S.FAILED and s.failure_reason == ("sandbox_oom" if oom else "sandbox_lost")
    assert sid not in fake_runner.sandboxes
    # attempts are unaffected and the student can restart
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 201


async def test_reconcile_ready_missing_entirely(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    fake_runner.sandboxes.pop(sid)["proc"].kill()
    await reconcile_once()
    assert (await _state(sid)).failure_reason == "sandbox_lost"


async def test_reconcile_resetting_timeout(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    async with sessionmaker()() as db:
        s = await db.get(LabSession, sid)
        await st.transition(db, s, [S.READY], S.RESETTING, reason="reset", actor="test",
                            state_deadline_at=st.now() - timedelta(seconds=1))
        await st.commit(db)
    await reconcile_once()
    s = await _state(sid)
    assert s.state == S.FAILED and s.failure_reason == "reset_timeout" and sid not in fake_runner.sandboxes


async def test_reconcile_submitting_without_attempt_regrades(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    await do_full_solution(c, sid)
    async with sessionmaker()() as db:  # simulate a crash right after the claim
        s = await db.get(LabSession, sid)
        await st.transition(db, s, [S.READY], S.SUBMITTING, reason="submit", actor="test",
                            state_deadline_at=st.now() - timedelta(seconds=1))
        await st.commit(db)
    await reconcile_once()
    await background.drain()
    s = await _state(sid)
    assert s.state == S.TERMINATED
    async with sessionmaker()() as db:
        at = await db.scalar(select(Attempt).where(Attempt.session_id == sid))
        assert at.trigger == "submit" and str(at.score) == "100.00" and at.counts


async def test_reconcile_submitting_dead_sandbox_fails_without_attempt(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    async with sessionmaker()() as db:
        s = await db.get(LabSession, sid)
        await st.transition(db, s, [S.READY], S.SUBMITTING, reason="submit", actor="test",
                            state_deadline_at=st.now() - timedelta(seconds=1))
        await st.commit(db)
    fake_runner.kill(sid)
    await reconcile_once()
    s = await _state(sid)
    assert s.state == S.FAILED and s.failure_reason == "grading_failed"
    async with sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(Attempt)) == 0


async def test_reconcile_terminating_and_leftovers_and_orphans(world, fake_runner):
    c = await login(world.alice)
    sid = await ready_session(c, world)
    # stuck TERMINATING
    async with sessionmaker()() as db:
        s = await db.get(LabSession, sid)
        await st.transition(db, s, [S.READY], S.TERMINATING, reason="stop", actor="test",
                            state_deadline_at=st.now() - timedelta(seconds=1))
        await st.commit(db)
    # an orphan sandbox with no DB row and a leftover for a FAILED session
    orphan = str(uuid.uuid4())
    await fake_runner.create_sandbox({"sandbox_id": orphan, "env": "test", "terminal_credential": "x:y"})
    failed = await _mk_session(world, S.FAILED)
    await fake_runner.create_sandbox({"sandbox_id": str(failed.id), "env": "test", "terminal_credential": "x:y"})
    other_env = str(uuid.uuid4())
    await fake_runner.create_sandbox({"sandbox_id": other_env, "env": "dev", "terminal_credential": "x:y"})
    stats = await reconcile_once()
    assert (await _state(sid)).state == S.TERMINATED
    assert set(fake_runner.sandboxes) == {other_env}, "other environments must never be reaped"
    assert stats.get("orphan_removed") == 1 and stats.get("leftover_destroyed") == 1


async def test_reconcile_does_not_mistake_reset_for_loss(world, fake_runner):
    """READY row read, then a reset replaced containers: the version CAS must prevent a false FAILED."""
    c = await login(world.alice)
    sid = await ready_session(c, world)
    fake_runner.kill(sid)  # looks dead to the list call...
    orig_status = fake_runner.sandbox_status

    async def status_after_reset(sandbox_id):  # ...but a reset happens before the re-check
        await fake_runner.reset_sandbox(sandbox_id, {"terminal_credential": "student:x"})
        async with sessionmaker()() as db:
            s = await db.get(LabSession, sandbox_id)
            await st.transition(db, s, [S.READY], S.RESETTING, reason="reset", actor="t")
            await st.transition(db, s, [S.RESETTING], S.READY, reason="reset_done", actor="t")
            await st.commit(db)
        fake_runner.sandboxes[sandbox_id]["dead"] = "exited"  # force the re-check to look bad too
        return await orig_status(sandbox_id)

    fake_runner.sandbox_status = status_after_reset  # type: ignore[method-assign]
    await reconcile_once()
    assert (await _state(sid)).state == S.READY


# --------------------------------------------------------------------------- instructor reopen
async def test_reopen_grants_attempt_and_is_audited(world, fake_runner):
    async with sessionmaker()() as db:
        from app.models import Assignment
        a = await db.get(Assignment, world.assignment.id)
        a.max_attempts = 1
        await db.commit()
    c, sid, _ = await _submitted(world, fake_runner)
    await wait_state(c, sid, {"TERMINATED"})
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.json()["error"]["code"] == "attempts_exhausted"
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/assignments/{world.assignment.id}/overrides",
                        json={"user_id": str(world.alice.id), "extra_attempts": 1,
                              "reason": "sandbox crashed during class"})
    assert r.status_code == 201
    r = await c.post(f"/api/assignments/{world.assignment.id}/sessions")
    assert r.status_code == 201
    async with sessionmaker()() as db:
        o = await db.scalar(select(StudentOverride))
        assert o.created_by == world.instructor.id and o.reason == "sandbox crashed during class"
    # other instructors can't grant
    other = await login(world.other_instructor)
    r = await other.post(f"/api/instructor/assignments/{world.assignment.id}/overrides",
                         json={"user_id": str(world.alice.id), "extra_attempts": 1, "reason": "nope"})
    assert r.status_code == 404


async def test_extension_reopens_closed_assignment(world, fake_runner):
    from app.models import Assignment
    async with sessionmaker()() as db:
        a = await db.get(Assignment, world.assignment.id)
        a.due_at = st.now() - timedelta(minutes=2)
        a.close_at = st.now() - timedelta(minutes=1)
        await db.commit()
    c = await login(world.alice)
    assert (await c.post(f"/api/assignments/{world.assignment.id}/sessions")).json()["error"]["code"] == "closed"
    inst = await login(world.instructor)
    r = await inst.post(f"/api/instructor/assignments/{world.assignment.id}/overrides",
                        json={"user_id": str(world.alice.id),
                              "close_at_override": (st.now() + timedelta(hours=1)).isoformat(),
                              "reason": "medical leave"})
    assert r.status_code == 201
    sid = await ready_session(c, world)
    r = await c.post(f"/api/sessions/{sid}/submit", headers=idem())
    assert r.status_code == 200 and r.json()["attempt"]["late"] is False
