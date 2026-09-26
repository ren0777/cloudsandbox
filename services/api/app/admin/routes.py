"""Admin API: runtime status (PLAN §17) and session kill."""

from __future__ import annotations

import uuid
from datetime import timedelta
from statistics import quantiles

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz
from ..db import get_db, sessionmaker
from ..errors import ApiError, not_found
from ..models import ACTIVE_STATES, Assignment, LabSession, Runner, SessionEvent, SessionState as S, User
from ..sessions import service
from ..sessions import state as st

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/runtime-status")
async def runtime_status(user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    now = st.now()
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    from .runners import runner_out
    runners = [await runner_out(db, r) for r in (await db.scalars(select(Runner).order_by(Runner.id))).all()
               if r.status != "retired"]
    # Provisioning latency: REQUESTED(created) → READY over the last hour.
    since = now - timedelta(hours=1)
    rows = (await db.execute(select(LabSession.created_at, LabSession.ready_at).where(
        LabSession.ready_at.is_not(None), LabSession.ready_at >= since))).all()
    lat = sorted((r.ready_at - r.created_at).total_seconds() for r in rows)
    p50 = p95 = None
    if len(lat) == 1:
        p50 = p95 = lat[0]
    elif len(lat) > 1:
        q = quantiles(lat, n=100, method="inclusive")
        p50, p95 = q[49], q[94]
    failures = (await db.execute(select(SessionEvent.reason, func.count()).where(
        SessionEvent.to_state == S.FAILED.value, SessionEvent.created_at >= now - timedelta(hours=24))
        .group_by(SessionEvent.reason))).all()
    by_state = (await db.execute(select(LabSession.state, func.count()).where(
        LabSession.state.in_(ACTIVE_STATES)).group_by(LabSession.state))).all()
    return {"server_time": now, "database": {"ok": db_ok}, "runners": runners,
            "sessions_by_state": {s.value: n for s, n in by_state},
            "provisioning_seconds": {"samples": len(lat), "p50": p50, "p95": p95},
            "failures_24h": {reason or "unknown": n for reason, n in failures}}


@router.post("/sessions/{session_id}/kill")
async def kill_session(session_id: uuid.UUID, user: User = Depends(Authz(Action.admin)),
                       db: AsyncSession = Depends(get_db)):
    sess = await db.get(LabSession, session_id)
    if sess is None:
        raise not_found("session")
    a = await db.get(Assignment, sess.assignment_id)
    student_id, state_before = sess.user_id, sess.state.value
    await db.close()
    if not await service.stop(session_id, f"admin:{user.id}", reason="admin_kill"):
        raise ApiError("invalid_state", f"cannot kill a session in state {state_before}", 409)
    async with sessionmaker()() as adb:
        audit.record(adb, user, "session.terminated", course_id=a.course_id if a else None,
                     assignment_id=sess.assignment_id, subject_user_id=student_id, session_id=session_id,
                     mode="discard", reason="admin kill", state=state_before)
        await adb.commit()
    return {"killed": True}
