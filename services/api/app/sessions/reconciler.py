"""DB ↔ Runner reconciliation (PLAN §3). Runs at startup and every `reconciler_interval_s`.

| DB state                          | Runner has sandbox?        | Action                                    |
|-----------------------------------|----------------------------|-------------------------------------------|
| REQUESTED older than stale limit  | any                        | FAILED(provision_timeout) (+destroy)      |
| PROVISIONING past deadline        | any                        | FAILED(provision_timeout) (+destroy)      |
| READY                             | no / component dead / OOM  | FAILED(sandbox_lost | sandbox_oom)        |
| RESETTING                         | no                         | FAILED(sandbox_lost)                      |
| RESETTING past deadline           | yes                        | FAILED(reset_timeout) (+destroy)          |
| SUBMITTING past deadline          | attempt stored             | → SUBMITTED, then teardown                |
| SUBMITTING past deadline          | no attempt, sandbox alive  | retry capture+grade (≤2), else FAILED     |
| SUBMITTED past deadline           | any                        | teardown                                  |
| TERMINATING past deadline         | any                        | destroy → TERMINATED                      |
| TERMINATED / FAILED               | yes                        | destroy                                   |
| (no row), older than grace        | yes                        | orphan → destroy                          |
| (no row), younger than grace      | yes                        | keep (in-flight `labtest`)                |

Lab Builder test runs (phase 8) create sandboxes without a session row; the ids of runs still in progress
(`lab_drafts.status = testing`) count as known, so only their leftovers become orphans.

Phase 7: the table is applied per registered runner, to that runner's sessions and sandboxes only. A runner
unreachable for longer than `runner_lost_after_s` is "lost": its sessions are never moved to another runner
and never reported as alive. REQUESTED/PROVISIONING/READY/RESETTING and ungraded SUBMITTING → FAILED
(`runner_lost`, no attempt used); graded SUBMITTING → SUBMITTED; SUBMITTED/TERMINATING → TERMINATED
(`runner_lost`). Any sandbox left on it is destroyed as a leftover when the runner comes back.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from ..config import get_settings
from ..db import sessionmaker
from ..errors import ApiError
from ..grader import evidence as ev
from ..grader.grade import collectors_for, grade, probes_for
from ..labs.importer import definition_of
from ..models import Attempt, LabDraft, LabSession, LabVersion, Runner, SessionEvent, SessionState as S
from ..obs.logging import log
from ..runtime.fleet import runner_lost
from ..runtime.runner_client import RunnerError, client_for, get_runner
from . import service
from . import state as st

MAX_RECOVERY = 2
_DEAD = ("missing", "exited", "oom")


def _past(deadline) -> bool:
    return deadline is not None and deadline < st.now()


async def _act(session_id: uuid.UUID, action: str, **kw) -> None:
    log.info("reconciler.action", session_id=str(session_id), sandbox_id=str(session_id), action=action, **kw)


async def reconcile_once() -> dict[str, int]:
    stats: dict[str, int] = {}
    async with sessionmaker()() as db:
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired").order_by(Runner.id))).all())
    for r in runners:
        part = await _lost_runner(r) if runner_lost(r) else await _reconcile_runner(r)
        for k, v in part.items():
            stats[k] = stats.get(k, 0) + v
    await _sweep_previews(stats)
    return stats


async def _lost_runner(r: Runner) -> dict[str, int]:
    """The runner has been unreachable for too long: settle its sessions honestly, without contacting it."""
    stats: dict[str, int] = {}
    async with sessionmaker()() as db:
        rows = list((await db.scalars(select(LabSession).where(
            LabSession.runner_id == r.id, LabSession.state.notin_([S.TERMINATED, S.FAILED])))).all())
    for sess in rows:
        state = sess.state
        async with sessionmaker()() as db:
            graded = await db.scalar(select(Attempt.id).where(Attempt.session_id == sess.id)) is not None
        await _act(sess.id, "runner_lost", state=state.value, runner_id=r.id, graded=graded)
        if state in (S.REQUESTED, S.PROVISIONING, S.READY, S.RESETTING) or (state == S.SUBMITTING and not graded):
            if await service.fail(sess.id, [state], "runner_lost", destroy=False):
                stats["runner_lost_failed"] = stats.get("runner_lost_failed", 0) + 1
            continue
        async with sessionmaker()() as db:
            fresh = await db.get(LabSession, sess.id)
            assert fresh is not None
            if fresh.state == S.SUBMITTING:
                await st.transition(db, fresh, [S.SUBMITTING], S.SUBMITTED, reason="runner_lost", actor="system:reconciler")
            if fresh.state == S.SUBMITTED:
                await st.transition(db, fresh, [S.SUBMITTED], S.TERMINATING, reason="runner_lost", actor="system:reconciler")
            if fresh.state == S.TERMINATING:
                await st.transition(db, fresh, [S.TERMINATING], S.TERMINATED, reason="runner_lost",
                                    actor="system:reconciler", state_deadline_at=None, ended_at=st.now())
            await st.commit(db)
        stats["runner_lost_closed"] = stats.get("runner_lost_closed", 0) + 1
    return stats


async def _reconcile_runner(r: Runner) -> dict[str, int]:
    s = get_settings()
    runner = client_for(r)
    stats: dict[str, int] = {}

    def bump(k: str) -> None:
        stats[k] = stats.get(k, 0) + 1

    try:
        sandboxes = {x["sandbox_id"]: x for x in await runner.list_sandboxes(env=s.env)}
    except RunnerError as e:
        log.warning("runner.unavailable", runner_id=runner.runner_id, error=e.message)
        return {"runner_unavailable": 1}

    live_ids = []
    for sid in sandboxes:
        try:
            live_ids.append(uuid.UUID(sid))
        except ValueError:
            pass
    async with sessionmaker()() as db:
        rows = list((await db.scalars(select(LabSession).where(
            LabSession.env == s.env, LabSession.runner_id == r.id,
            or_(LabSession.state.notin_([S.TERMINATED, S.FAILED]), LabSession.id.in_(live_ids))))).all())
    known = {str(r.id) for r in rows} | await _builder_test_sandboxes() | await _preview_sandboxes()
    async with sessionmaker()() as db:  # rows for live sandboxes may be in any env-matching state
        if live_ids:
            known |= {str(i) for i in (await db.scalars(select(LabSession.id).where(
                LabSession.id.in_(live_ids)))).all()}

    for sess in rows:
        sb = sandboxes.get(str(sess.id))
        state = sess.state
        if state == S.REQUESTED and sess.created_at < st.now() - timedelta(seconds=s.requested_stale_s):
            await _act(sess.id, "fail", reason="provision_timeout", state=state.value)
            await service.fail(sess.id, [S.REQUESTED], "provision_timeout")
            bump("provision_timeout")
        elif state == S.PROVISIONING and _past(sess.state_deadline_at):
            await _act(sess.id, "fail", reason="provision_timeout", state=state.value)
            await service.fail(sess.id, [S.PROVISIONING], "provision_timeout")
            bump("provision_timeout")
        elif state == S.READY:
            bad = sb is None or sb["emulator"]["state"] in _DEAD or sb["terminal"]["state"] in _DEAD
            if bad:
                # Re-check against a fresh status and CAS on the version we read first, so a reset that
                # happened in between can't be mistaken for a lost sandbox.
                v = sess.version
                try:
                    cur = await runner.sandbox_status(str(sess.id))
                except RunnerError:
                    continue
                if cur["exists"] and cur["emulator"]["state"] not in _DEAD \
                        and cur["terminal"]["state"] not in _DEAD:
                    continue
                oom = cur["emulator"]["state"] == "oom" or cur["terminal"]["state"] == "oom"
                reason = "sandbox_oom" if oom else "sandbox_lost"
                await _act(sess.id, "fail", reason=reason, state=state.value)
                await service.fail(sess.id, [S.READY], reason, expect_version=v)
                bump(reason)
        elif state == S.RESETTING:
            if sb is None:
                await _act(sess.id, "fail", reason="sandbox_lost", state=state.value)
                await service.fail(sess.id, [S.RESETTING], "sandbox_lost")
                bump("sandbox_lost")
            elif _past(sess.state_deadline_at):
                await _act(sess.id, "fail", reason="reset_timeout", state=state.value)
                await service.fail(sess.id, [S.RESETTING], "reset_timeout")
                bump("reset_timeout")
        elif state == S.SUBMITTING and _past(sess.state_deadline_at):
            await _recover_submitting(sess, sb)
            bump("submitting_recovered")
        elif state == S.SUBMITTED and _past(sess.state_deadline_at):
            await _act(sess.id, "teardown", state=state.value)
            await service.teardown(sess.id)
            bump("teardown")
        elif state == S.TERMINATING and _past(sess.state_deadline_at):
            await _act(sess.id, "destroy", state=state.value)
            if await service.destroy_quietly(sess.id):
                async with sessionmaker()() as db:
                    fresh = await db.get(LabSession, sess.id)
                    assert fresh is not None
                    await st.transition(db, fresh, [S.TERMINATING], S.TERMINATED, reason="reconciled",
                                        actor="system:reconciler", state_deadline_at=None, ended_at=st.now())
                    await st.commit(db)
            bump("terminated")
        elif state in (S.TERMINATED, S.FAILED) and sb is not None:
            await _act(sess.id, "destroy_leftover", state=state.value)
            await service.destroy_quietly(sess.id)
            bump("leftover_destroyed")

    for sid in sandboxes:
        if sid in known:
            continue
        created = sandboxes[sid].get("created_at")
        # Only a plausible, past creation time earns the grace window. A missing time (None), a time in the
        # future or a non-finite value (clock skew, a bad label) must never look "young", or the sandbox
        # could survive forever: reap it as an orphan.
        age = None if created is None else st.now().timestamp() - created
        if age is not None and 0.0 <= age < s.orphan_grace_s:
            bump("orphan_young")
            continue
        log.info("janitor.orphan_removed", sandbox_id=sid)
        try:
            await runner.destroy_sandbox(sid)
        except RunnerError as e:
            log.warning("sandbox.destroy.failed", sandbox_id=sid, error=e.message)
        bump("orphan_removed")
    return stats


async def _builder_test_sandboxes() -> set[str]:
    async with sessionmaker()() as db:
        runs = (await db.scalars(select(LabDraft.last_test).where(LabDraft.status == "testing"))).all()
    return {sid for lt in runs for sid in (lt or {}).get("sandbox_ids", [])}


async def _preview_sandboxes() -> set[str]:
    """Preview sandboxes of running previews (M42): real sandboxes with no session row, so the orphan sweep
    must treat them as known. Abandoned previews are destroyed by `_sweep_previews`."""
    async with sessionmaker()() as db:
        rows = (await db.scalars(select(LabDraft.last_preview).where(
            LabDraft.last_preview["status"].astext == "running"))).all()
    return {str((lp or {}).get("sandbox_id")) for lp in rows if (lp or {}).get("sandbox_id")}


async def _sweep_previews(stats: dict[str, int]) -> None:
    """Destroy preview sandboxes idle past `preview_ttl_s`: unlike sessions, nothing else times them out."""
    from ..instructor import preview
    async with sessionmaker()() as db:
        rows = list((await db.scalars(select(LabDraft).where(
            LabDraft.last_preview["status"].astext == "running"))).all())
    for d in rows:
        lp = d.last_preview or {}
        if not preview._stale(lp):
            continue
        sid = str(lp.get("sandbox_id"))
        try:
            await get_runner().destroy_sandbox(sid)
        except RunnerError as e:
            log.warning("preview.destroy.failed", draft_id=str(d.id), sandbox_id=sid, error=e.message)
        async with sessionmaker()() as db:
            fresh = await db.get(LabDraft, d.id)
            if fresh is not None and (fresh.last_preview or {}).get("sandbox_id") == lp.get("sandbox_id"):
                fresh.last_preview = {**fresh.last_preview, "status": "stopped",
                                      "stopped_at": st.now().isoformat(), "error": "the preview expired",
                                      "ttyd_cred_enc": None, "emulator_endpoint": None}
                await db.commit()
        stats["preview_expired"] = stats.get("preview_expired", 0) + 1


async def _recover_submitting(sess: LabSession, sb: dict | None) -> None:
    async with sessionmaker()() as db:
        attempt = await db.scalar(select(Attempt).where(Attempt.session_id == sess.id))
        if attempt is not None:
            fresh = await db.get(LabSession, sess.id)
            assert fresh is not None
            await st.transition(db, fresh, [S.SUBMITTING], S.SUBMITTED, reason="reconciled",
                                actor="system:reconciler", state_deadline_at=st.now())
            await st.commit(db)
            await _act(sess.id, "finish_submitted")
            await service.teardown(sess.id)
            return
        trigger = await db.scalar(select(SessionEvent.reason).where(
            SessionEvent.session_id == sess.id, SessionEvent.to_state == S.SUBMITTING.value)
            .order_by(SessionEvent.id.desc()).limit(1)) or "submit"
        lv = await db.get(LabVersion, sess.lab_version_id)
        assert lv is not None
        d = definition_of(lv)
        alive = sb is not None and sb["emulator"]["state"] == "running"
        if not alive or sess.recovery_attempts >= MAX_RECOVERY:
            await _act(sess.id, "fail", reason="grading_failed")
            await service.fail(sess.id, [S.SUBMITTING], "grading_failed")
            return
        fresh = await db.get(LabSession, sess.id)
        assert fresh is not None
        fresh.recovery_attempts += 1
        fresh.state_deadline_at = st.now() + timedelta(seconds=get_settings().submit_deadline_s)
        await db.commit()
    await _act(sess.id, "retry_grading", attempt=fresh.recovery_attempts)
    try:
        payload = await ev.capture(sess.emulator_endpoint or "", collectors_for(d), sess.engine,
                                   probes_for(d, sess.variables))
        result = grade(d, sess.variables, payload)
        await service._persist_attempt(sess.id, trigger, payload, result, d)
    except ApiError:
        return
    except Exception as e:
        log.warning("grader.submit.failed", session_id=str(sess.id), error=repr(e))
        return  # next pass retries or fails it
    await service.teardown(sess.id)
