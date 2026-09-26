"""Live student progress and staff session controls (phase 5).

Live view: every running (or recently interrupted) session in a course with its state, timers, last activity
and the student's latest *Check progress* summary. Staff never read a sandbox directly: the summary is what
the student's own progress check stored, so monitoring adds no load on sandboxes and can't change them.

Controls (course staff; audited): terminate a session — `grade` submits it now (trigger `staff`, counted only
if the graded state changed from the baseline, like other automatic submits) or `discard` ends it without
grading (no attempt used) — and extend a running session's time limit."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz, load_course_for_staff, load_session_for_staff
from ..config import get_settings
from ..db import get_db, sessionmaker
from ..errors import ApiError
from ..labs.importer import definition_of
from ..models import ACTIVE_STATES, Assignment, LabSession, LabVersion, SessionState as S, User
from ..sessions import service
from ..sessions import state as st
from ..sessions.windows import standing

router = APIRouter(prefix="/api/instructor", tags=["instructor"])


@router.get("/courses/{course_id}/live")
async def live(course_id: uuid.UUID, user: User = Depends(Authz(Action.session_manage)), db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    now = st.now()
    rows = (await db.execute(
        select(LabSession, User, Assignment).join(User, User.id == LabSession.user_id)
        .join(Assignment, Assignment.id == LabSession.assignment_id)
        .where(Assignment.course_id == c.id,
               (LabSession.state.in_(ACTIVE_STATES)) |
               ((LabSession.state == S.FAILED) & (LabSession.ended_at >= now - timedelta(hours=1))))
        .order_by(Assignment.due_at, User.name))).all()
    titles: dict[uuid.UUID, tuple[str, int]] = {}
    out = []
    for sess, u, a in rows:
        if a.lab_version_id not in titles:
            lv = await db.get(LabVersion, a.lab_version_id)
            d = definition_of(lv) if lv else None
            titles[a.lab_version_id] = (d.title if d else "", len(d.tasks) if d else 0)
        idle_deadline = sess.last_activity_at + timedelta(minutes=sess.idle_minutes) if sess.last_activity_at else None
        p = sess.last_progress
        out.append({
            "session_id": str(sess.id), "state": sess.state.value, "failure_reason": sess.failure_reason,
            "student": {"id": str(u.id), "name": u.name, "email": u.email, "short_id": u.short_id},
            "assignment": {"id": str(a.id), "title": a.title, "lab": titles[a.lab_version_id][0]},
            "started_at": sess.ready_at or sess.created_at, "expires_at": sess.expires_at,
            "last_activity_at": sess.last_activity_at, "idle_deadline_at": idle_deadline,
            "progress": p, "progress_at": sess.last_progress_at,
            "tasks_total": titles[a.lab_version_id][1],
            "tasks_passed": sum(1 for t in (p or {}).get("tasks", []) if t["passed"]) if p else None,
        })
    return {"server_time": now, "course": {"id": str(c.id), "code": c.code, "title": c.title}, "sessions": out}


class TerminateIn(BaseModel):
    mode: Literal["grade", "discard"]
    reason: str = Field(min_length=3, max_length=500)


@router.post("/sessions/{session_id}/terminate")
async def terminate(session_id: uuid.UUID, body: TerminateIn, user: User = Depends(Authz(Action.session_manage)),
                    db: AsyncSession = Depends(get_db)):
    sess = await load_session_for_staff(db, user, session_id)
    a = await db.get(Assignment, sess.assignment_id)
    assert a is not None
    student_id, course_id, assignment_id = sess.user_id, a.course_id, a.id
    await db.close()
    actor = f"staff:{user.id}"
    result: dict = {"mode": body.mode}
    if body.mode == "grade":
        attempt = await service.submit(session_id, "staff", actor)  # raises 409 if not READY
        result.update(attempt_id=str(attempt.id), score=str(attempt.score), counts=attempt.counts)
    elif not await service.stop(session_id, actor, reason="staff_terminated"):
        raise ApiError("invalid_state", "this lab isn't running, so it can't be ended", 409)
    async with sessionmaker()() as adb:
        audit.record(adb, user, "session.terminated", course_id=course_id, assignment_id=assignment_id,
                     subject_user_id=student_id, session_id=session_id, reason=body.reason, **result)
        await adb.commit()
    return result


class ExtendIn(BaseModel):
    minutes: int = Field(ge=5, le=60)
    reason: str = Field(min_length=3, max_length=500)


@router.post("/sessions/{session_id}/extend")
async def extend(session_id: uuid.UUID, body: ExtendIn, user: User = Depends(Authz(Action.session_manage)),
                 db: AsyncSession = Depends(get_db)):
    """Adds time to a running lab (the idle timer restarts too). Capped by the platform's maximum session
    lifetime and by the student's effective closing time for the assignment."""
    sess = await load_session_for_staff(db, user, session_id)
    if sess.state != S.READY or sess.expires_at is None:
        raise ApiError("invalid_state", "only a running lab can be extended", 409, extra={"state": sess.state.value})
    a = await db.get(Assignment, sess.assignment_id)
    assert a is not None
    stand = await standing(db, a, sess.user_id)
    start = sess.ready_at or sess.created_at
    limit = min(start + timedelta(minutes=get_settings().cap_extended_ttl_minutes), stand.close_at)
    old_expiry = sess.expires_at  # read before the UPDATE (which synchronises the loaded object)
    new_expiry = min(old_expiry + timedelta(minutes=body.minutes), limit)
    if new_expiry <= old_expiry:
        raise ApiError("extension_limit", "this lab can't run any longer (maximum session time or the assignment's "
                       "closing time reached)", 409)
    now = st.now()
    r = await db.execute(update(LabSession).where(LabSession.id == sess.id, LabSession.state == S.READY,
                                                  LabSession.expires_at == old_expiry)
                         .values(expires_at=new_expiry, last_activity_at=now))
    if r.rowcount != 1:
        raise ApiError("invalid_state", "the lab changed while extending it; try again", 409)
    added = int((new_expiry - old_expiry).total_seconds() // 60)
    audit.record(db, user, "session.extended", course_id=a.course_id, assignment_id=a.id, subject_user_id=sess.user_id,
                 session_id=sess.id, requested_minutes=body.minutes, added_minutes=added,
                 previous_expires_at=old_expiry, expires_at=new_expiry, reason=body.reason)
    await db.commit()
    return {"expires_at": new_expiry, "added_minutes": added}
