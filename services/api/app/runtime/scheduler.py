"""Runner scheduler (phase 7). Chooses the runner for a NEW session inside the Start transaction.

Eligible runners: healthy (fresh heartbeat), not draining, able to run the lab's engine (its emulator image and
the terminal image are present), and with a free seat (`in_use < max_sandboxes`, counting every session that may
still hold a sandbox there). Among them, the least loaded wins (in_use / max, then more free host memory, then
id), so labs spread across runners.

Concurrency: selection runs under one transaction-scoped advisory lock (`SCHEDULER_LOCK`), so concurrent Starts
are serialised for the few milliseconds between counting seats and inserting the new session (the lock is
released at commit, after the insert). No runner can be over-reserved. Runner rows are only READ, so heartbeats
that update runner statistics can never form a lock cycle with a Start (row locks `FOR UPDATE` did, found by the
phase 7 load test). Sessions never change runner after this point (no migration)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..errors import ApiError
from ..models import CAPACITY_STATES, LabSession, Runner
from ..obs import metrics
from ..obs.logging import log
from ..sessions import state as st


@dataclass(frozen=True)
class Candidate:
    runner: Runner
    in_use: int

    @property
    def load(self) -> float:
        return self.in_use / max(1, self.runner.max_sandboxes)


def healthy(r: Runner) -> bool:
    if r.status != "healthy" or r.last_heartbeat is None:
        return False
    return (st.now() - r.last_heartbeat).total_seconds() <= get_settings().runner_unhealthy_after_s


def compatible(r: Runner, engine: str) -> bool:
    return bool((r.engines or {}).get(engine))


async def in_use_by_runner(db: AsyncSession, runner_ids: list[str]) -> dict[str, int]:
    if not runner_ids:
        return {}
    rows = (await db.execute(select(LabSession.runner_id, func.count()).where(
        LabSession.runner_id.in_(runner_ids), LabSession.state.in_(CAPACITY_STATES))
        .group_by(LabSession.runner_id))).all()
    return {rid: n for rid, n in rows}


SCHEDULER_LOCK = 0x436C5363  # "ClSc": the fleet-wide scheduling lock (pg_advisory_xact_lock key)


async def pick_runner(db: AsyncSession, engine: str) -> Runner:
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK})
    runners = list((await db.scalars(select(Runner).where(Runner.drain.is_(False)).order_by(Runner.id))).all())
    usable = [r for r in runners if healthy(r) and compatible(r, engine)]
    if not usable:
        reason = "no runner registered" if not runners else \
            ("no healthy runner" if not any(healthy(r) for r in runners) else f"no runner can run the {engine} engine")
        log.warning("runner.unavailable", engine=engine, reason=reason)
        raise ApiError("runtime_unavailable", "the lab runtime is unavailable, try again shortly", 503,
                       headers={"Retry-After": "30"})
    counts = await in_use_by_runner(db, [r.id for r in usable])
    cands = [Candidate(r, counts.get(r.id, 0)) for r in usable]
    free = [c for c in cands if c.in_use < c.runner.max_sandboxes]
    if not free:
        in_use, cap = sum(c.in_use for c in cands), sum(c.runner.max_sandboxes for c in cands)
        metrics.capacity_rejections_total.inc()
        log.warning("capacity.rejected", in_use=in_use, max=cap, runners=len(cands), engine=engine)
        raise ApiError("capacity_full", "all lab seats are in use", 503, headers={"Retry-After": "60"},
                       extra={"in_use": in_use, "max": cap})
    best = min(free, key=lambda c: (c.load, -(c.runner.mem_available_mib or 0), c.runner.id))
    return best.runner
