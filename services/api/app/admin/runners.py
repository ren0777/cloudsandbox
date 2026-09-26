"""Admin runner fleet API (phase 7): list, register, drain/resume, retire. All changes are audited.

Drain = maintenance mode: the scheduler places no NEW labs on the runner; running labs finish normally (they are
never moved). When `in_use` reaches 0 the runner can be upgraded or rebooted safely, then resumed. Retire removes a
drained, empty runner from scheduling and heartbeats for good (its row stays for history)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz
from ..db import get_db
from ..errors import ApiError, not_found
from ..models import Runner, User
from ..runtime import fleet
from ..runtime.scheduler import healthy
from ..sessions import state as st

router = APIRouter(prefix="/api/admin/runners", tags=["admin"])


async def runner_out(db: AsyncSession, r: Runner) -> dict:
    in_use = await fleet.seats_in_use(db, r.id)
    return {"id": r.id, "url": r.url, "status": r.status, "healthy": healthy(r), "drain": r.drain,
            "safe_to_stop": r.drain and in_use == 0, "in_use": in_use, "max_sandboxes": r.max_sandboxes,
            "sandboxes_on_host": r.active, "engines": r.engines or {}, "default_engine": r.default_engine,
            "version": r.version, "cpu_count": r.cpu_count, "mem_total_mib": r.mem_total_mib,
            "mem_available_mib": r.mem_available_mib, "last_heartbeat": r.last_heartbeat,
            "unreachable_since": r.unreachable_since, "lost": fleet.runner_lost(r), "last_error": r.last_error,
            "own_secret": r.secret_enc is not None, "registered_at": r.registered_at}


@router.get("")
async def list_runners(user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    runners = (await db.scalars(select(Runner).order_by(Runner.id))).all()
    return {"server_time": st.now(), "runners": [await runner_out(db, r) for r in runners]}


class RegisterIn(BaseModel):
    id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    url: str = Field(min_length=8, max_length=255, pattern=r"^https?://[^\s]+$")
    secret: str = Field(min_length=16, max_length=512)


@router.post("", status_code=201)
async def register_runner(body: RegisterIn, user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    """The runner must answer a signed capacity call with this id before it is saved."""
    await db.close()
    r = await fleet.register(body.id, body.url.rstrip("/"), body.secret, actor=user)
    return await runner_out(db, r)


class RunnerPatch(BaseModel):
    drain: bool
    reason: str | None = Field(None, max_length=500)


@router.patch("/{runner_id}")
async def update_runner(runner_id: str, body: RunnerPatch, user: User = Depends(Authz(Action.admin)),
                        db: AsyncSession = Depends(get_db)):
    r = await db.get(Runner, runner_id)
    if r is None:
        raise not_found("runner")
    if r.status == "retired":
        raise ApiError("runner_retired", "this runner is retired; register it again to use it", 409)
    if r.drain != body.drain:
        r.drain = body.drain
        audit.record(db, user, "runner.drained" if body.drain else "runner.resumed", runner_id=r.id,
                     reason=body.reason, in_use=await fleet.seats_in_use(db, r.id))
        await db.commit()
    return await runner_out(db, r)


@router.delete("/{runner_id}")
async def retire_runner(runner_id: str, user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    r = await db.get(Runner, runner_id)
    if r is None:
        raise not_found("runner")
    in_use = await fleet.seats_in_use(db, r.id)
    if not r.drain or in_use:
        raise ApiError("runner_busy", "drain the runner and wait until no labs are left on it before retiring it", 409,
                       extra={"in_use": in_use, "drain": r.drain})
    r.status = "retired"
    audit.record(db, user, "runner.retired", runner_id=r.id, url=r.url)
    await db.commit()
    return await runner_out(db, r)
