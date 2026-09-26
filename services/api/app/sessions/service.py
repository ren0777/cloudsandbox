"""Session orchestration: start / provision / reset / submit / progress / stop / teardown / fail.

Invariants (PLAN §1–§5):
- Every state change goes through state.transition (CAS). Long runner calls happen outside DB
  transactions; the transient state is the lock and carries state_deadline_at for recovery.
- Submit claims the session (READY→SUBMITTING) BEFORE capturing evidence, so reset, expiry, cleanup,
  console mutations, terminals and a second submit are all blocked while grading runs.
"""

from __future__ import annotations

import secrets
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import encrypt
from ..db import sessionmaker
from ..errors import ApiError
from ..grader import evidence as ev
from ..grader.grade import collectors_for, grade, probes_for, to_json
from ..labs.importer import definition_of, get_bundle
from ..labs.package import setup_job
from ..labs.render import compute_variables
from ..labs.schema import LabDefinition
from ..models import (
    ACTIVE_STATES,
    Assignment,
    Attempt,
    Grade,
    GradingEvidence,
    LabSession,
    LabVersion,
    Runner,
    SessionState as S,
    TaskResult,
    User,
)
from ..obs import metrics
from ..obs.logging import bind, log
from ..runtime import emulators
from ..runtime.runner_client import RunnerError, client_for_id
from ..runtime.scheduler import pick_runner
from ..tasks.background import spawn
from . import state as st
from .windows import standing

SYSTEM = "system"


# --------------------------------------------------------------------------------------- helpers
def resolve_limits(d: LabDefinition) -> dict[str, Any]:
    """Platform defaults, lab overrides clamped to admin caps (PLAN §12)."""
    s = get_settings()

    def comp(name: str, cpus: float, mem: int, pids: int) -> dict[str, Any]:
        o = getattr(d.resources, name, None) if d.resources else None
        return {"cpus": min((o.cpus if o and o.cpus else cpus), s.cap_cpus),
                "memory_mib": min((o.memory_mib if o and o.memory_mib else mem), s.cap_memory_mib),
                "pids": min((o.pids if o and o.pids else pids), s.cap_pids)}

    return {"emulator": comp("emulator", s.emulator_cpus, s.emulator_memory_mib, s.emulator_pids),
            "terminal": comp("terminal", s.terminal_cpus, s.terminal_memory_mib, s.terminal_pids)}


def resolve_ttl_idle(d: LabDefinition) -> tuple[int, int]:
    s = get_settings()
    ttl = min(d.duration_minutes, s.cap_ttl_minutes)
    idle = d.idle_minutes or s.idle_timeout_minutes
    return ttl, max(s.cap_idle_min_minutes, min(idle, s.cap_idle_max_minutes))


def new_terminal_credential() -> str:
    return f"student:{secrets.token_urlsafe(24).replace('-', 'A').replace('_', 'B')}"


async def _definition(db: AsyncSession, lab_version_id: uuid.UUID) -> tuple[LabVersion, LabDefinition]:
    lv = await db.get(LabVersion, lab_version_id)
    assert lv is not None
    return lv, definition_of(lv)


async def _store_baseline(db: AsyncSession, session: LabSession, payload: dict) -> None:
    sha, nsha = ev.digest(payload)
    db.add(GradingEvidence(session_id=session.id, kind="baseline", sha256=sha, normalized_sha256=nsha,
                           payload=payload))
    log.info("evidence.stored", session_id=str(session.id), kind="baseline", sha256=sha)


def runner_healthy(r: Runner) -> bool:
    from ..runtime.scheduler import healthy
    return healthy(r)


# ----------------------------------------------------------------------------------------- start
async def start_session(db: AsyncSession, user: User, a: Assignment) -> tuple[LabSession, bool]:
    s = get_settings()
    now = st.now()
    bind(assignment_id=a.id)
    stand = await standing(db, a, user.id)
    if now < stand.open_at:
        raise ApiError("not_open", "this lab is not open yet", 409)
    if now >= stand.close_at:
        raise ApiError("closed", "this lab is closed", 409)

    # Serialise concurrent Starts of the same student (configurable active-session limit, PLAN §2).
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                     {"k": f"start:{user.id}"})
    existing = await db.scalar(select(LabSession).where(
        LabSession.user_id == user.id, LabSession.assignment_id == a.id, LabSession.state.in_(ACTIVE_STATES)))
    if existing is not None:
        await db.commit()
        return existing, False
    if stand.attempts_left <= 0:
        raise ApiError("attempts_exhausted", "you have used all attempts for this lab", 409)
    others = (await db.execute(select(LabSession.id, LabSession.assignment_id).where(
        LabSession.user_id == user.id, LabSession.state.in_(ACTIVE_STATES)))).all()
    if len(others) >= s.max_active_sessions_per_student:
        raise ApiError("other_session_active", "finish or stop your other active lab first", 409,
                       extra={"session_id": str(others[0].id), "assignment_id": str(others[0].assignment_id)})

    lv, d = await _definition(db, a.lab_version_id)
    engine = emulators.resolve(d.runtime.emulator)
    # Scheduler: healthy, not draining, engine-compatible runner with a free seat; least loaded wins.
    runner = await pick_runner(db, engine)
    ttl, idle = resolve_ttl_idle(d)
    sess = LabSession(id=uuid.uuid4(), user_id=user.id, assignment_id=a.id, lab_version_id=lv.id,
                      runner_id=runner.id, env=s.env, engine=engine, state=S.REQUESTED,
                      variables=compute_variables(d, user.short_id), resources=resolve_limits(d),
                      ttl_minutes=ttl, idle_minutes=idle)
    db.add(sess)
    try:
        await db.flush()
    except IntegrityError:  # lost a race on the partial unique index: return the winner
        await db.rollback()
        winner = await db.scalar(select(LabSession).where(
            LabSession.user_id == user.id, LabSession.assignment_id == a.id,
            LabSession.state.in_(ACTIVE_STATES)))
        if winner is None:
            raise
        return winner, False
    st.record_created(db, sess.id, f"user:{user.id}")
    await db.commit()
    bind(session_id=sess.id, sandbox_id=sess.id, runner_id=runner.id)
    log.info("session.created", session_id=str(sess.id), assignment_id=str(a.id), user_id=str(user.id))
    spawn(provision(sess.id), name=f"provision:{sess.id}")
    return sess, True


# ------------------------------------------------------------------------------------- provision
async def provision(session_id: uuid.UUID) -> None:
    s = get_settings()
    sm = sessionmaker()
    async with sm() as db:
        sess = await db.get(LabSession, session_id)
        if sess is None:
            return
        runner = await client_for_id(sess.runner_id)  # the runner chosen at Start; never another one
        bind(session_id=sess.id, sandbox_id=sess.id, user_id=sess.user_id,
             assignment_id=sess.assignment_id, runner_id=sess.runner_id)
        if not await st.transition(db, sess, [S.REQUESTED], S.PROVISIONING, reason="provision",
                                   actor=SYSTEM,
                                   state_deadline_at=st.now() + timedelta(seconds=s.provision_deadline_s)):
            return
        await st.commit(db)
        lv, d = await _definition(db, sess.lab_version_id)
        public = await get_bundle(db, lv.id, "public")
        cred = new_terminal_credential()
        req = {"sandbox_id": str(sess.id), "env": sess.env, "engine": sess.engine, "terminal_credential": cred,
               "emulator": sess.resources["emulator"], "terminal": sess.resources["terminal"],
               "setup": setup_job(public.data, d, sess.variables)}
    t0 = time.monotonic()
    log.info("sandbox.create.started", session_id=str(session_id))
    try:
        info = await runner.create_sandbox(req)
    except RunnerError as e:
        log.warning("sandbox.create.failed", session_id=str(session_id), code=e.code, error=e.message)
        await fail(session_id, [S.PROVISIONING], "capacity_full" if e.code == "capacity_full"
                   else "provision_error")
        return
    if info.get("engine", sess.engine) != sess.engine:  # runner must honour the requested engine
        log.warning("sandbox.create.failed", session_id=str(session_id), error="engine mismatch")
        await fail(session_id, [S.PROVISIONING], "provision_error")
        return
    metrics.provision_seconds.observe(time.monotonic() - t0)
    log.info("sandbox.create.succeeded", session_id=str(session_id),
             duration_ms=int((time.monotonic() - t0) * 1000))
    try:
        baseline = await ev.capture(info["emulator_endpoint"], collectors_for(d), sess.engine,
                                    probes_for(d, sess.variables))
    except Exception as e:
        log.warning("sandbox.create.failed", session_id=str(session_id), error=f"baseline: {e!r}")
        await fail(session_id, [S.PROVISIONING], "provision_error")
        return
    async with sm() as db:
        sess = await db.get(LabSession, session_id)
        assert sess is not None
        now = st.now()
        ok = await st.transition(
            db, sess, [S.PROVISIONING], S.READY, reason="provisioned", actor=SYSTEM,
            state_deadline_at=None, emulator_endpoint=info["emulator_endpoint"],
            terminal_endpoint=info["terminal_endpoint"], ttyd_cred_enc=encrypt(cred),
            image_digest=info["emulator_image_id"], terminal_image_digest=info["terminal_image_id"],
            ready_at=now, last_activity_at=now, expires_at=now + timedelta(minutes=sess.ttl_minutes))
        if ok:
            await _store_baseline(db, sess, baseline)
            await st.commit(db)
            return
        await db.rollback()
    # Someone (reconciler) moved the session on while we were provisioning: don't leak the sandbox.
    await destroy_quietly(session_id)


# ----------------------------------------------------------------------------------- fail/teardown
async def destroy_quietly(session_id: uuid.UUID) -> bool:
    log.info("sandbox.destroy.started", session_id=str(session_id))
    try:
        async with sessionmaker()() as db:
            runner_id = await db.scalar(select(LabSession.runner_id).where(LabSession.id == session_id))
        if runner_id is None:
            return True  # no such session: nothing to destroy
        await (await client_for_id(runner_id)).destroy_sandbox(str(session_id))
        log.info("sandbox.destroy.succeeded", session_id=str(session_id))
        return True
    except RunnerError as e:
        log.warning("sandbox.destroy.failed", session_id=str(session_id), error=e.message)
        return False


async def fail(session_id: uuid.UUID, from_states: list[S], reason: str, actor: str = SYSTEM,
               expect_version: int | None = None, destroy: bool = True) -> bool:
    """destroy=False when the runner is unreachable: its leftovers are removed when it comes back."""
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, session_id)
        if sess is None:
            return False
        ok = await st.transition(db, sess, from_states, S.FAILED, reason=reason, actor=actor,
                                 expect_version=expect_version, failure_reason=reason,
                                 state_deadline_at=None, ended_at=st.now())
        await st.commit(db)
    if ok and destroy:  # if someone else moved the session on, they own its sandbox lifecycle
        await destroy_quietly(session_id)
    return ok


async def teardown(session_id: uuid.UUID, from_states: tuple[S, ...] = (S.SUBMITTED,),
                   reason: str = "teardown", actor: str = SYSTEM) -> bool:
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, session_id)
        if sess is None:
            return False
        if not await st.transition(db, sess, from_states, S.TERMINATING, reason=reason, actor=actor,
                                   state_deadline_at=st.now() + timedelta(seconds=120)):
            return False
        await st.commit(db)
    if not await destroy_quietly(session_id):
        return False  # stays TERMINATING; the reconciler retries
    async with sessionmaker()() as db:
        sess = await db.get(LabSession, session_id)
        assert sess is not None
        await st.transition(db, sess, [S.TERMINATING], S.TERMINATED, reason="destroyed", actor=SYSTEM,
                            state_deadline_at=None, ended_at=st.now())
        await st.commit(db)
    return True


# ---------------------------------------------------------------------------------------- reset
async def reset(user: User, session_id: uuid.UUID) -> LabSession:
    s = get_settings()
    sm = sessionmaker()
    async with sm() as db:
        sess = await db.get(LabSession, session_id)
        if sess is None or sess.user_id != user.id:
            raise ApiError("not_found", "session not found", 404)
        if not await st.transition(db, sess, [S.READY], S.RESETTING, reason="reset", actor=f"user:{user.id}",
                                   state_deadline_at=st.now() + timedelta(seconds=s.reset_deadline_s)):
            raise _state_conflict(sess)
        await st.commit(db)
        lv, d = await _definition(db, sess.lab_version_id)
        public = await get_bundle(db, lv.id, "public")
        resources, engine, variables = sess.resources, sess.engine, dict(sess.variables)
        runner_id = sess.runner_id
    cred = new_terminal_credential()
    try:
        info = await (await client_for_id(runner_id)).reset_sandbox(str(session_id), {
            "terminal_credential": cred, "emulator": resources["emulator"],
            "terminal": resources["terminal"], "setup": setup_job(public.data, d, variables)})
        baseline = await ev.capture(info["emulator_endpoint"], collectors_for(d), engine, probes_for(d, variables))
    except Exception as e:
        log.warning("sandbox.create.failed", session_id=str(session_id), error=f"reset: {e!r}")
        await fail(session_id, [S.RESETTING], "reset_failed")
        raise ApiError("reset_failed", "resetting the lab failed; please restart the lab", 503) from None
    async with sm() as db:
        sess = await db.get(LabSession, session_id)
        assert sess is not None
        ok = await st.transition(db, sess, [S.RESETTING], S.READY, reason="reset_done", actor=SYSTEM,
                                 state_deadline_at=None, emulator_endpoint=info["emulator_endpoint"],
                                 terminal_endpoint=info["terminal_endpoint"], ttyd_cred_enc=encrypt(cred),
                                 last_activity_at=st.now())
        if not ok:
            raise _state_conflict(sess)
        await _store_baseline(db, sess, baseline)
        await st.commit(db)
        return sess


# --------------------------------------------------------------------------------------- submit
def _state_conflict(sess: LabSession) -> ApiError:
    if sess.state in (S.SUBMITTING,):
        return ApiError("session_frozen", "this lab is being submitted", 409, extra={"state": sess.state.value})
    return ApiError("invalid_state", f"not possible while the lab is {sess.state.value.lower()}", 409,
                    extra={"state": sess.state.value})


async def submit(session_id: uuid.UUID, trigger: str, actor: str) -> Attempt:
    """trigger: submit (explicit, always counts) | idle | ttl | close (automatic, counts only if graded
    resource state changed from the baseline)."""
    s = get_settings()
    sm = sessionmaker()
    async with sm() as db:
        sess = await db.get(LabSession, session_id)
        if sess is None:
            raise ApiError("not_found", "session not found", 404)
        bind(session_id=sess.id, sandbox_id=sess.id, user_id=sess.user_id,
             assignment_id=sess.assignment_id, runner_id=sess.runner_id)
        a = await db.get(Assignment, sess.assignment_id)
        assert a is not None
        if trigger == "submit":
            stand = await standing(db, a, sess.user_id)
            if st.now() >= stand.close_at:
                raise ApiError("closed", "this lab is closed", 409)
        # 1. Claim the session: from here on nothing else can mutate or grade it.
        if not await st.transition(db, sess, [S.READY], S.SUBMITTING, reason=trigger, actor=actor,
                                   state_deadline_at=st.now() + timedelta(seconds=s.submit_deadline_s)):
            await db.refresh(sess)
            existing = await db.scalar(select(Attempt).where(Attempt.session_id == session_id))
            if existing is not None:
                raise ApiError("already_submitted", "this lab was already submitted", 409,
                               extra={"attempt_id": str(existing.id)})
            raise _state_conflict(sess)
        await st.commit(db)  # closes terminals (bus) — mutation paths are now blocked
        lv, d = await _definition(db, sess.lab_version_id)
        endpoint, variables, engine = sess.emulator_endpoint, dict(sess.variables), sess.engine
    log.info("grader.submit.started", session_id=str(session_id), trigger=trigger)
    t0 = time.monotonic()
    try:
        # 2. Capture evidence only after mutation paths are blocked. 3. Pure grading.
        payload = await ev.capture(endpoint, collectors_for(d), engine, probes_for(d, variables))
        result = grade(d, variables, payload)
    except Exception as e:
        log.error("grader.submit.failed", session_id=str(session_id), error=repr(e))
        await fail(session_id, [S.SUBMITTING], "grading_failed")
        raise ApiError("grading_failed", "grading failed; this attempt was not counted", 503) from None
    metrics.grading_seconds.observe(time.monotonic() - t0)
    attempt = await _persist_attempt(session_id, trigger, payload, result, d)
    spawn(teardown(session_id), name=f"teardown:{session_id}")
    await award_badges(attempt.id)
    return attempt


async def award_badges(attempt_id: uuid.UUID) -> None:
    """Badges from the stored, graded attempt. Runs after the grade is committed and can never affect it:
    a failure is logged (a later backfill or regrade awards them)."""
    from ..gamification import award_for_attempt
    try:
        async with sessionmaker()() as db:
            await award_for_attempt(db, attempt_id)
    except Exception as e:  # pragma: no cover - defensive
        log.error("background.task.failed", task="award_badges", attempt_id=str(attempt_id), error=repr(e))


async def _persist_attempt(session_id: uuid.UUID, trigger: str, payload: dict, result: dict,
                           d: LabDefinition) -> Attempt:
    s = get_settings()
    async with sessionmaker()() as db:
        sess = await db.scalar(select(LabSession).where(LabSession.id == session_id).with_for_update())
        assert sess is not None
        if sess.state != S.SUBMITTING:
            raise ApiError("invalid_state", "the session changed state during grading", 409)
        a = await db.get(Assignment, sess.assignment_id)
        assert a is not None
        stand = await standing(db, a, sess.user_id)
        sha, nsha = ev.digest(payload)
        if trigger == "submit":
            counts = True
        else:
            base = await db.scalar(select(GradingEvidence).where(
                GradingEvidence.session_id == session_id, GradingEvidence.kind == "baseline")
                .order_by(GradingEvidence.captured_at.desc()).limit(1))
            counts = base is None or base.normalized_sha256 != nsha
        n = (await db.scalar(select(func.max(Attempt.attempt_no)).where(
            Attempt.user_id == sess.user_id, Attempt.assignment_id == sess.assignment_id)) or 0) + 1
        attempt = Attempt(session_id=sess.id, user_id=sess.user_id, assignment_id=sess.assignment_id,
                          lab_version_id=sess.lab_version_id, attempt_no=n, trigger=trigger, counts=counts,
                          late=stand.is_late(st.now()), score=result["score"], max_score=result["max_score"],
                          grader_version=s.grader_version, emulator_image_digest=sess.image_digest,
                          variables=sess.variables)
        db.add(attempt)
        await db.flush()
        db.add(GradingEvidence(session_id=sess.id, attempt_id=attempt.id, kind="final", sha256=sha,
                               normalized_sha256=nsha, payload=payload))
        for t in to_json(result)["tasks"]:
            db.add(TaskResult(attempt_id=attempt.id, task_id=t["task_id"], title=t["title"],
                              marks_awarded=t["marks_awarded"], marks_possible=t["marks_possible"],
                              passed=t["passed"], checks=t["checks"]))
        db.add(Grade(attempt_id=attempt.id, grader_version=s.grader_version, score=result["score"],
                     max_score=result["max_score"], result=to_json(result), created_by=None,
                     reason="initial"))
        # The deadline lets the reconciler finish teardown if this process dies before it runs.
        await st.transition(db, sess, [S.SUBMITTING], S.SUBMITTED, reason="graded", actor=SYSTEM,
                            state_deadline_at=st.now() + timedelta(seconds=60))
        await st.commit(db)
        bind(attempt_id=attempt.id)
        log.info("evidence.stored", session_id=str(session_id), attempt_id=str(attempt.id), kind="final",
                 sha256=sha)
        log.info("grader.submit.finished", session_id=str(session_id), attempt_id=str(attempt.id),
                 score=str(result["score"]), max_score=str(result["max_score"]), counts=counts,
                 trigger=trigger)
        return attempt


# ------------------------------------------------------------------------------------- progress
_last_progress: dict[uuid.UUID, float] = {}


async def progress(sess: LabSession) -> dict:
    s = get_settings()
    if sess.state != S.READY:
        raise _state_conflict(sess)
    last = _last_progress.get(sess.id, 0.0)
    wait = s.progress_min_interval_s - (time.monotonic() - last)
    if wait > 0:
        raise ApiError("rate_limited", "checking too often, wait a few seconds", 429,
                       headers={"Retry-After": str(int(wait) + 1)}, extra={"retry_after": round(wait, 1)})
    _last_progress[sess.id] = time.monotonic()
    async with sessionmaker()() as db:
        _, d = await _definition(db, sess.lab_version_id)
    try:
        payload = await ev.capture(sess.emulator_endpoint or "", collectors_for(d), sess.engine,
                                   probes_for(d, sess.variables))
    except Exception as e:
        raise ApiError("progress_unavailable", f"could not read your sandbox ({e.__class__.__name__})",
                       503) from None
    result = grade(d, sess.variables, payload)
    log.info("grader.progress", session_id=str(sess.id), score=str(result["score"]))
    await _store_progress(sess.id, result)
    return result


async def _store_progress(session_id: uuid.UUID, result: dict) -> None:
    """Keep a small summary of the latest progress check for staff live monitoring (not evidence)."""
    from sqlalchemy import update
    summary = {"score": str(result["score"]), "max_score": str(result["max_score"]),
               "tasks": [{"task_id": t["task_id"], "title": t["title"], "passed": t["passed"]} for t in result["tasks"]]}
    async with sessionmaker()() as db:
        await db.execute(update(LabSession).where(LabSession.id == session_id, LabSession.state == S.READY)
                         .values(last_progress=summary, last_progress_at=st.now()))
        await db.commit()


# -------------------------------------------------------------------------------- live inventory
_inventory: dict[uuid.UUID, tuple[float, dict]] = {}
INVENTORY_TTL_S = 5.0


async def inventory(sess: LabSession) -> dict:
    """Read-only snapshot of the sandbox for the architecture diagram and cost meter: the lab's own grading
    collectors (so only capability-validated read operations), never probes (no Lambda invocations), cached
    for a few seconds per session. It is not evidence and does not count as activity."""
    if sess.state != S.READY:
        raise _state_conflict(sess)
    hit = _inventory.get(sess.id)
    if hit and time.monotonic() - hit[0] < INVENTORY_TTL_S:
        return hit[1]
    async with sessionmaker()() as db:
        _, d = await _definition(db, sess.lab_version_id)
    try:
        payload = await ev.capture(sess.emulator_endpoint or "", collectors_for(d), sess.engine, None)
    except Exception as e:
        raise ApiError("inventory_unavailable", f"could not read your sandbox ({e.__class__.__name__})", 503) from None
    _inventory[sess.id] = (time.monotonic(), payload)
    return payload


# ----------------------------------------------------------------------------------------- stop
async def stop(session_id: uuid.UUID, actor: str, reason: str = "stopped") -> bool:
    """Abandon without grading (student 'End lab' / admin kill). Does not use an attempt."""
    return await teardown(session_id, from_states=(S.READY, S.REQUESTED), reason=reason, actor=actor)


# ------------------------------------------------------------------------------------- activity
_last_touch: dict[uuid.UUID, float] = {}


async def touch(session_id: uuid.UUID, force: bool = False) -> None:
    """Record activity for the idle timer (throttled DB writes)."""
    now_m = time.monotonic()
    if not force and now_m - _last_touch.get(session_id, 0.0) < get_settings().heartbeat_write_min_interval_s:
        return
    _last_touch[session_id] = now_m
    from sqlalchemy import update
    async with sessionmaker()() as db:
        await db.execute(update(LabSession).where(LabSession.id == session_id, LabSession.state == S.READY)
                         .values(last_activity_at=st.now()))
        await db.commit()
