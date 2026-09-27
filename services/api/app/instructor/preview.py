"""Interactive preview sandbox for authored labs (phase 9, milestone 42).

An instructor launches the draft's **declared** starting state in a real, isolated runner sandbox — the same
sandbox a student lab gets (private network, resource limits, compiled typed break actions) — and inspects
it in the AWS-style console and the browser terminal. Reset re-runs the declared setup, so the broken state
comes back identically.

A preview is **not a session**: it never creates an assignment, attempt, grade, XP, badge or leaderboard
event, and there is no submit path. It is owner/admin only (404 to anyone else), it lives on the platform
runner under `env`, and the reconciler knows its sandbox id so it is never reaped as an orphan. An abandoned
preview is destroyed by the reconciler after `preview_ttl_s` of inactivity.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, Authz, load_draft_for
from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..db import get_db, sessionmaker
from ..errors import ApiError, not_found
from ..labs import drafts as dr
from ..labs.package import setup_job
from ..labs.render import compute_variables
from ..labs.schema import LabValidationError
from ..models import LabDraft, User
from ..obs.logging import log
from ..runtime import emulators
from ..runtime.runner_client import RunnerError, get_runner
from ..sessions import state as st
from ..sessions.service import new_terminal_credential

router = APIRouter(prefix="/api/instructor/builder/drafts/{draft_id}/preview-sandbox", tags=["lab-builder"])

# Throttled activity writes, like the session idle timer.
_touched: dict[str, float] = {}


def sandbox_id_for(draft_id: uuid.UUID) -> str:
    """Stable per draft, so a restart can find (or clean up) the sandbox it created before."""
    return str(uuid.uuid5(draft_id, "cloudlabs-preview"))


def _invalid(e: LabValidationError, lab: dict[str, Any] | None = None) -> ApiError:
    return ApiError("lab_invalid", "the lab pack is not valid", 422,
                    extra={"errors": [dr.row_error(m, lab or {}) for m in e.errors]})


def _out(d: LabDraft) -> dict[str, Any]:
    lp = d.last_preview or {}
    return {"preview": {"status": lp.get("status", "stopped"), "sandbox_id": lp.get("sandbox_id"),
                        "engine": lp.get("engine"), "started_at": lp.get("started_at"),
                        "last_active": lp.get("last_active"), "error": lp.get("error"),
                        "ws_path": "/ws/terminal",
                        "console": f"/api/sessions/{lp['sandbox_id']}/console" if lp.get("status") == "running" else None,
                        "terminal_ticket": (f"/api/sessions/{lp['sandbox_id']}/terminal-ticket"
                                            if lp.get("status") == "running" else None)}}


def _stale(lp: dict[str, Any], ttl_s: int | None = None) -> bool:
    s = get_settings()
    since = lp.get("last_active") or lp.get("started_at")
    try:
        at = datetime.fromisoformat(since) if since else None
    except ValueError:
        at = None
    return at is not None and at < st.now() - timedelta(seconds=ttl_s if ttl_s is not None else s.preview_ttl_s)


async def _running_preview_ids() -> set[str]:
    async with sessionmaker()() as db:
        rows = (await db.scalars(select(LabDraft.last_preview).where(
            LabDraft.last_preview["status"].astext == "running"))).all()
    return {str((lp or {}).get("sandbox_id")) for lp in rows if (lp or {}).get("sandbox_id")}


async def _stop(db: AsyncSession, d: LabDraft, *, reason: str) -> None:
    lp = d.last_preview or {}
    sid = lp.get("sandbox_id")
    if sid:
        try:
            await get_runner().destroy_sandbox(str(sid))
        except RunnerError as e:
            log.warning("preview.destroy.failed", draft_id=str(d.id), sandbox_id=str(sid), error=e.message)
    d.last_preview = {**lp, "status": "stopped", "stopped_at": st.now().isoformat(), "error": reason,
                      "ttyd_cred_enc": None, "emulator_endpoint": None}
    await db.commit()


async def _touch(draft_id: uuid.UUID, sandbox_id: str) -> None:
    now = time.monotonic()
    if now - _touched.get(sandbox_id, 0.0) < get_settings().heartbeat_write_min_interval_s:
        return
    _touched[sandbox_id] = now
    async with sessionmaker()() as db:
        d = await db.get(LabDraft, draft_id)
        if d is not None and (d.last_preview or {}).get("sandbox_id") == sandbox_id:
            d.last_preview = {**(d.last_preview or {}), "last_active": st.now().isoformat()}
            await db.commit()


async def _draft_for_sandbox(db: AsyncSession, sandbox_id: uuid.UUID) -> LabDraft | None:
    return await db.scalar(select(LabDraft).where(
        LabDraft.last_preview["sandbox_id"].astext == str(sandbox_id)))


async def load_preview_context(db: AsyncSession, user: User, sandbox_id: uuid.UUID):
    """Console/terminal target for a preview sandbox. 404 for anyone but the draft's owner or an admin."""
    from ..console.common import SandboxContext  # local: avoid an import cycle at module load
    d = await _draft_for_sandbox(db, sandbox_id)
    if d is None:
        raise not_found("preview sandbox")
    d = await load_draft_for(db, user, d.id)  # owner or admin, else 404
    lp = d.last_preview or {}
    if lp.get("status") != "running" or not lp.get("emulator_endpoint"):
        raise ApiError("invalid_state", "this preview sandbox is not running", 409)
    return SandboxContext(id=uuid.UUID(lp["sandbox_id"]), engine=lp["engine"],
                          emulator_endpoint=lp["emulator_endpoint"],
                          touch=lambda: _touch(d.id, lp["sandbox_id"]))


async def preview_for_terminal(db: AsyncSession, user: User, sandbox_id: uuid.UUID) -> LabDraft:
    """The draft behind a running preview sandbox, for the terminal ticket (owner or admin, else 404)."""
    d = await _draft_for_sandbox(db, sandbox_id)
    if d is None:
        raise not_found("preview sandbox")
    d = await load_draft_for(db, user, d.id)
    lp = d.last_preview or {}
    if lp.get("status") != "running" or not lp.get("terminal_endpoint") or not lp.get("ttyd_cred_enc"):
        raise ApiError("invalid_state", "this preview sandbox is not running", 409)
    return d


# ---------------------------------------------------------------------------------------- lifecycle
@router.post("", status_code=201)
async def start_preview(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    """Launch (or return) the draft's preview sandbox: a real isolated sandbox built from the declared
    starting state, for console and terminal inspection. Never a session, attempt or grade."""
    s = get_settings()
    d = await load_draft_for(db, user, draft_id)
    try:
        pkg = dr.package(d.content)
    except LabValidationError as e:
        raise _invalid(e, d.content.get("lab")) from e
    lp = d.last_preview or {}
    runner = get_runner()
    if lp.get("status") == "running":
        try:
            stt = await runner.sandbox_status(str(lp.get("sandbox_id")))
        except RunnerError:
            stt = None
        if stt is not None and stt.get("exists") and not _stale(lp):
            return _out(d)  # idempotent
        await _stop(db, d, reason="the previous preview was gone or expired")
    running = await db.scalar(select(func.count()).select_from(LabDraft).where(
        LabDraft.owner_id == d.owner_id, LabDraft.last_preview["status"].astext == "running")) or 0
    if running >= s.preview_max_per_user:
        raise ApiError("preview_capacity_full", "you already have the maximum number of previews running; "
                       "stop one before starting another", 429, headers={"Retry-After": "60"})
    engine = emulators.candidates(pkg.definition.runtime.emulator)[0]
    variables = compute_variables(pkg.definition, user.short_id)
    sid = sandbox_id_for(d.id)
    cred = new_terminal_credential()
    req = {"sandbox_id": sid, "env": s.env, "engine": engine, "terminal_credential": cred,
           "emulator": {"cpus": s.emulator_cpus, "memory_mib": s.emulator_memory_mib, "pids": s.emulator_pids},
           "terminal": {"cpus": s.terminal_cpus, "memory_mib": s.terminal_memory_mib, "pids": s.terminal_pids},
           "setup": setup_job(pkg.public_bundle, pkg.definition, variables)}
    try:
        info = await runner.create_sandbox(req)
    except RunnerError as e:
        log.warning("preview.create.failed", draft_id=str(d.id), code=e.code, error=e.message)
        raise ApiError("preview_unavailable", f"the lab runtime refused the preview sandbox: {e.message}",
                       503 if e.code in ("unavailable", "timeout") else 409) from None
    now = st.now().isoformat()
    d.last_preview = {"status": "running", "sandbox_id": sid, "engine": info.get("engine", engine),
                      "started_at": now, "started_by": str(user.id), "last_active": now,
                      "emulator_endpoint": info["emulator_endpoint"], "terminal_endpoint": info["terminal_endpoint"],
                      "ttyd_cred_enc": encrypt(cred), "error": None}
    await db.commit()
    await db.refresh(d)
    log.info("preview.started", draft_id=str(d.id), sandbox_id=sid, engine=engine)
    return _out(d)


@router.get("")
async def get_preview(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                      db: AsyncSession = Depends(get_db)):
    """Preview status, reconciled against the runner: a sandbox that disappeared or expired is reported
    stopped (and cleaned up)."""
    d = await load_draft_for(db, user, draft_id)
    lp = d.last_preview or {}
    if lp.get("status") == "running":
        if _stale(lp):
            await _stop(db, d, reason="the preview expired")
        else:
            try:
                stt = await get_runner().sandbox_status(str(lp.get("sandbox_id")))
                exists = bool(stt.get("exists"))
            except RunnerError:
                exists = True  # runner unreachable: keep the record, let the reconciler settle it
            if not exists:
                d.last_preview = {**lp, "status": "stopped", "error": "the sandbox is gone",
                                  "ttyd_cred_enc": None, "emulator_endpoint": None}
                await db.commit()
    return _out(d)


@router.post("/reset")
async def reset_preview(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                        db: AsyncSession = Depends(get_db)):
    """Reset the preview sandbox: the runner replaces the containers and re-runs the **declared** setup, so
    typed break actions reconstruct the identical starting state."""
    d = await load_draft_for(db, user, draft_id)
    lp = d.last_preview or {}
    if lp.get("status") != "running":
        raise ApiError("preview_not_running", "start a preview before resetting it", 409)
    try:
        pkg = dr.package(d.content)
    except LabValidationError as e:
        raise _invalid(e, d.content.get("lab")) from e
    variables = compute_variables(pkg.definition, user.short_id)
    req = {"emulator": {"cpus": get_settings().emulator_cpus, "memory_mib": get_settings().emulator_memory_mib,
                        "pids": get_settings().emulator_pids},
           "terminal": {"cpus": get_settings().terminal_cpus, "memory_mib": get_settings().terminal_memory_mib,
                        "pids": get_settings().terminal_pids},
           "terminal_credential": decrypt(lp.get("ttyd_cred_enc") or ""),
           "setup": setup_job(pkg.public_bundle, pkg.definition, variables)}
    try:
        info = await get_runner().reset_sandbox(str(lp["sandbox_id"]), req)
    except RunnerError as e:
        raise ApiError("preview_unavailable", f"the preview sandbox could not be reset: {e.message}",
                       503 if e.code in ("unavailable", "timeout") else 409) from None
    d.last_preview = {**lp, "last_active": st.now().isoformat(), "error": None,
                      "emulator_endpoint": info["emulator_endpoint"], "terminal_endpoint": info["terminal_endpoint"]}
    await db.commit()
    await db.refresh(d)
    log.info("preview.reset", draft_id=str(d.id), sandbox_id=str(lp["sandbox_id"]))
    return _out(d)


@router.delete("", status_code=204)
async def stop_preview(draft_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    d = await load_draft_for(db, user, draft_id)
    await _stop(db, d, reason=None)
    log.info("preview.stopped", draft_id=str(d.id))
