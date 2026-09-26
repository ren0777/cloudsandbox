"""Runner fleet (phase 7): registration, heartbeats, drain/retire, and the "runner lost" rule.

Registration: a runner is added by an admin (API or `python -m app.runtime.fleet register`) with its URL and its
own HMAC secret. The control plane calls the runner's signed `/v1/capacity` first and refuses to register it
unless the runner answers with the same id. Secrets are stored encrypted (Fernet, `CL_SECRET_KEY`). The
platform's own runner (CL_RUNNER_ID/URL/SECRET) is seeded at startup, which keeps one-server installs zero-config.

Heartbeats (pull): every `heartbeat_interval_s` the control plane polls every non-retired runner concurrently and
stores health, engines (emulator + terminal images present), load and host memory. Status is one of healthy,
unhealthy (Docker down), unreachable, misconfigured (answers with another id) and retired.

Runner lost: when a runner has been unreachable for `runner_lost_after_s`, its sessions are NOT moved elsewhere
and are not reported as alive. The reconciler fails them (`runner_lost`, no attempt used) or, for already graded
sessions, finishes them. Their sandboxes are destroyed as leftovers if the runner comes back (see reconciler)."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .. import audit
from ..config import get_settings
from ..crypto import encrypt
from ..db import sessionmaker
from ..errors import ApiError
from ..models import ACTIVE_STATES, CAPACITY_STATES, LabSession, Runner
from ..obs import metrics
from ..obs.logging import log
from ..sessions import state as st
from .runner_client import HttpRunnerClient, RunnerError, client_for

HEARTBEAT_TIMEOUT_S = 15.0


async def seed_runner() -> None:
    s = get_settings()
    async with sessionmaker()() as db:
        await db.execute(insert(Runner).values(id=s.runner_id, url=s.runner_url, max_sandboxes=4, status="unknown")
                         .on_conflict_do_update(index_elements=[Runner.id], set_={"url": s.runner_url}))
        await db.commit()


def apply_capacity(r: Runner, cap: dict[str, Any]) -> None:
    """Store a heartbeat answer on the runner row."""
    now = st.now()
    if cap.get("runner_id") != r.id:
        r.status = "misconfigured"
        r.last_error = f"runner answered as {cap.get('runner_id')!r}"[:300]
        return
    r.status = "healthy" if cap.get("docker_ok") else "unhealthy"
    r.active = cap.get("active", 0)
    r.max_sandboxes = cap.get("max_sandboxes", r.max_sandboxes)
    r.version = cap.get("version")
    r.engines = dict(cap.get("engines") or {})
    r.default_engine = cap.get("default_engine")
    r.cpu_count = cap.get("cpu_count")
    r.mem_total_mib = cap.get("mem_total_mib")
    r.mem_available_mib = cap.get("mem_available_mib")
    r.last_heartbeat = now
    r.unreachable_since = None
    r.last_error = None if cap.get("docker_ok") else "Docker is not responding on the runner host"
    if cap.get("leaked_networks"):
        r.last_error = (f"{cap['leaked_networks']} empty sandbox network(s) Docker could not remove; restart Docker "
                        "on this runner during maintenance (drain first)")


async def _poll(r: Runner) -> tuple[str, dict | None, str | None]:
    try:
        return r.id, await asyncio.wait_for(client_for(r).capacity(), timeout=HEARTBEAT_TIMEOUT_S), None
    except (RunnerError, asyncio.TimeoutError) as e:
        return r.id, None, getattr(e, "message", "timed out")


async def heartbeat_once() -> None:
    async with sessionmaker()() as db:
        runners = list((await db.scalars(select(Runner).where(Runner.status != "retired").order_by(Runner.id))).all())
    results = await asyncio.gather(*(_poll(r) for r in runners))
    async with sessionmaker()() as db:
        for rid, cap, err in sorted(results, key=lambda x: x[0]):  # fixed order: no lock cycles between beats
            r = await db.get(Runner, rid)
            if r is None or r.status == "retired":
                continue
            if cap is not None:
                apply_capacity(r, cap)
            else:
                # One slow or missed beat (e.g. a runner busy creating many sandboxes) must not take the runner out
                # of service: it stays schedulable while its last good heartbeat is fresh (runner_unhealthy_after_s).
                # The outage start is recorded at the first miss, so "lost" still means N minutes without contact.
                r.unreachable_since = r.unreachable_since or st.now()
                r.last_error = (err or "unreachable")[:300]
                limit = get_settings().runner_unhealthy_after_s
                stale = r.last_heartbeat is None or (st.now() - r.last_heartbeat).total_seconds() > limit
                if stale and r.status != "unreachable":
                    log.warning("runner.unavailable", runner_id=rid, error=err)
                    r.status = "unreachable"
        active = await db.scalar(select(func.count()).select_from(LabSession).where(LabSession.state.in_(ACTIVE_STATES)))
        metrics.sessions_active.set(active or 0)
        await db.commit()


def runner_lost(r: Runner) -> bool:
    if r.status != "unreachable" or r.unreachable_since is None:
        return False
    return (st.now() - r.unreachable_since).total_seconds() >= get_settings().runner_lost_after_s


async def register(runner_id: str, url: str, secret: str, actor: Any = None) -> Runner:
    """Verify, then create or update a runner (re-registering un-retires it)."""
    probe = HttpRunnerClient(runner_id, url, secret, 15.0)
    try:
        cap = await probe.capacity()
    except RunnerError as e:
        raise ApiError("runner_unreachable", f"could not reach the runner with these settings: {e.message}", 400) from None
    finally:
        await probe.aclose()
    if cap.get("runner_id") != runner_id:
        raise ApiError("runner_mismatch", f"the runner at {url} identifies itself as {cap.get('runner_id')!r}", 400)
    async with sessionmaker()() as db:
        r = await db.get(Runner, runner_id)
        if r is None:
            r = Runner(id=runner_id, url=url, max_sandboxes=cap.get("max_sandboxes", 4), status="unknown")
            db.add(r)
        r.url = url
        r.secret_enc = encrypt(secret) if secret != get_settings().runner_secret else None
        r.drain = False if r.status == "retired" else r.drain
        apply_capacity(r, cap)
        audit.record(db, actor, "runner.registered", runner_id=runner_id, url=url, engines=r.engines,
                     max_sandboxes=r.max_sandboxes, via="api" if actor else "cli")
        await db.commit()
        await db.refresh(r)
        return r


async def seats_in_use(db, runner_id: str) -> int:
    return await db.scalar(select(func.count()).select_from(LabSession).where(
        LabSession.runner_id == runner_id, LabSession.state.in_(CAPACITY_STATES))) or 0


# ----------------------------------------------------------------------------------------------- CLI
USAGE = """usage: python -m app.runtime.fleet <command>
  list
  register <id> <url>        (reads the runner's secret from the RUNNER_SECRET environment variable)
  drain <id> | resume <id>"""


async def _cli(argv: list[str]) -> int:
    from ..models import User  # noqa: F401  (models loaded)
    if argv[:1] == ["list"]:
        async with sessionmaker()() as db:
            for r in (await db.scalars(select(Runner).order_by(Runner.id))).all():
                print(f"{r.id:24} {r.status:13} drain={str(r.drain).lower():5} {await seats_in_use(db, r.id)}/{r.max_sandboxes} "
                      f"engines={','.join(k for k, v in (r.engines or {}).items() if v) or '-'} {r.url}")
        return 0
    if len(argv) == 3 and argv[0] == "register":
        import os
        secret = os.environ.get("RUNNER_SECRET")
        if not secret:
            print("set RUNNER_SECRET to the runner's HMAC secret")
            return 2
        r = await register(argv[1], argv[2], secret)
        print(f"registered {r.id} ({r.status}) at {r.url}")
        return 0
    if len(argv) == 2 and argv[0] in ("drain", "resume"):
        async with sessionmaker()() as db:
            r = await db.get(Runner, argv[1])
            if r is None:
                print(f"no runner {argv[1]}")
                return 2
            if r.drain != (argv[0] == "drain"):
                r.drain = argv[0] == "drain"
                audit.record(db, None, "runner.drained" if r.drain else "runner.resumed", runner_id=r.id, via="cli")
            n = await seats_in_use(db, r.id)
            await db.commit()
        print(f"{argv[1]}: {'draining' if argv[0] == 'drain' else 'accepting new labs'}; {n} session(s) still on it")
        return 0
    print(USAGE)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
