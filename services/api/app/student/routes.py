"""Student API: assignments, lab sessions, attempts (PLAN §2, §5, §9)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import Action, Authz, load_assignment_for, load_own_attempt, load_session_for
from ..console.common import sandbox_engine
from ..db import get_db, sessionmaker
from ..errors import ApiError
from ..grader.grade import student_view
from ..idempotency import run_idempotent
from ..labs.importer import definition_of
from ..labs.render import compute_variables, student_lab_view
from ..models import (
    GradingEvidence,
    UserBadge,
    ACTIVE_STATES,
    Assignment,
    Attempt,
    Course,
    Enrolment,
    Grade,
    LabSession,
    LabVersion,
    SessionState as S,
    User,
)
from ..gamification import BY_ID
from ..insights import insights
from ..obs.logging import bind
from ..runtime import emulators
from ..sessions import service
from ..sessions import state as st
from ..sessions.views import session_out
from ..sessions.windows import standing

router = APIRouter(prefix="/api", tags=["student"])


async def _latest_grade(db: AsyncSession, attempt_id: uuid.UUID) -> Grade | None:
    return await db.scalar(select(Grade).where(Grade.attempt_id == attempt_id)
                           .order_by(Grade.created_at.desc()).limit(1))


async def _attempts_summary(db: AsyncSession, a: Assignment, user_id: uuid.UUID) -> list[dict]:
    rows = (await db.scalars(select(Attempt).where(Attempt.assignment_id == a.id, Attempt.user_id == user_id)
                             .order_by(Attempt.attempt_no))).all()
    out = []
    for at in rows:
        g = await _latest_grade(db, at.id)
        out.append({"id": str(at.id), "attempt_no": at.attempt_no, "trigger": at.trigger, "counts": at.counts,
                    "late": at.late, "score": str(g.score if g else at.score),
                    "max_score": str(at.max_score), "created_at": at.created_at})
    return out


def final_score(attempts: list[dict], policy: str) -> str | None:
    counted = [x for x in attempts if x["counts"]]
    if not counted:
        return None
    if policy == "latest":
        return counted[-1]["score"]
    return max(counted, key=lambda x: float(x["score"]))["score"]


async def _assignment_card(db: AsyncSession, a: Assignment, user: User) -> dict:
    stand = await standing(db, a, user.id)
    lv = await db.get(LabVersion, a.lab_version_id)
    assert lv is not None
    d = definition_of(lv)
    attempts = await _attempts_summary(db, a, user.id)
    active = await db.scalar(select(LabSession).where(LabSession.user_id == user.id,
                                                      LabSession.assignment_id == a.id,
                                                      LabSession.state.in_(ACTIVE_STATES)))
    now = st.now()
    return {"id": str(a.id), "title": a.title, "lab_title": d.title, "summary": d.summary,
            "services": list(d.services), "duration_minutes": d.duration_minutes, "kind": d.kind,
            "open_at": a.open_at, "due_at": a.due_at, "close_at": stand.close_at,
            "is_open": stand.is_open(now), "is_late": stand.is_late(now),
            "attempts_used": stand.attempts_used, "attempts_allowed": stand.attempts_allowed,
            "attempts_left": stand.attempts_left, "grade_policy": a.grade_policy,
            "final_score": final_score(attempts, a.grade_policy), "max_score": str(d.max_score),
            "active_session": {"id": str(active.id), "state": active.state.value} if active else None,
            "attempts": attempts}


@router.get("/me/assignments")
async def my_assignments(user: User = Depends(Authz(Action.assignment_view)),
                         db: AsyncSession = Depends(get_db)):
    if user.role.value != "student":
        return {"assignments": []}
    rows = (await db.execute(select(Assignment, Course).join(Course, Course.id == Assignment.course_id)
                             .join(Enrolment, Enrolment.course_id == Course.id)
                             .where(Enrolment.user_id == user.id).order_by(Assignment.due_at))).all()
    out = []
    for a, c in rows:
        card = await _assignment_card(db, a, user)
        card["course"] = {"id": str(c.id), "code": c.code, "title": c.title, "leaderboard": c.leaderboard}
        out.append(card)
    return {"assignments": out}


@router.get("/assignments/{assignment_id}")
async def get_assignment(assignment_id: uuid.UUID, user: User = Depends(Authz(Action.assignment_view)),
                         db: AsyncSession = Depends(get_db)):
    a = await load_assignment_for(db, user, assignment_id)
    lv = await db.get(LabVersion, a.lab_version_id)
    assert lv is not None
    d = definition_of(lv)
    card = await _assignment_card(db, a, user) if user.role.value == "student" else {"id": str(a.id)}
    variables = compute_variables(d, user.short_id) if user.role.value == "student" else None
    card["lab"] = student_lab_view(d, variables)
    return card


@router.post("/assignments/{assignment_id}/sessions")
async def start(assignment_id: uuid.UUID, user: User = Depends(Authz(Action.session_start)),
                db: AsyncSession = Depends(get_db)):
    a = await load_assignment_for(db, user, assignment_id)
    sess, created = await service.start_session(db, user, a)
    async with sessionmaker()() as db2:
        fresh = await db2.get(LabSession, sess.id)
        assert fresh is not None
        body = await session_out(db2, fresh)
    return JSONResponse(jsonable_encoder(body), 201 if created else 200)


@router.get("/sessions/{session_id}")
async def get_session(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                      db: AsyncSession = Depends(get_db)):
    sess = await load_session_for(db, user, session_id)
    bind(session_id=sess.id)
    return await session_out(db, sess, with_lab=True)


@router.post("/sessions/{session_id}/heartbeat", status_code=204)
async def heartbeat(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                    db: AsyncSession = Depends(get_db)):
    sess = await load_session_for(db, user, session_id)
    if sess.state == S.READY:
        await service.touch(sess.id, force=True)


@router.post("/sessions/{session_id}/progress")
async def check_progress(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                         db: AsyncSession = Depends(get_db)):
    sess = await load_session_for(db, user, session_id)
    bind(session_id=sess.id)
    result = await service.progress(sess)
    await service.touch(sess.id)
    return student_view(result)


@router.get("/sessions/{session_id}/architecture")
async def architecture(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                       db: AsyncSession = Depends(get_db)):
    """Live architecture diagram of the student's own sandbox (read-only snapshot, see service.inventory)."""
    sess = await load_session_for(db, user, session_id)
    await db.close()
    payload = await service.inventory(sess)
    return {"captured_at": payload.get("captured_at"), **insights(payload)}


@router.post("/sessions/{session_id}/reset")
async def reset(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                idempotency_key: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    await load_session_for(db, user, session_id)
    await db.close()

    async def handler():
        sess = await service.reset(user, session_id)
        async with sessionmaker()() as db2:
            fresh = await db2.get(LabSession, sess.id)
            assert fresh is not None
            return 200, await session_out(db2, fresh)
    return await run_idempotent(user.id, idempotency_key, f"reset:{session_id}", {}, handler)


@router.post("/sessions/{session_id}/submit")
async def submit(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
                 idempotency_key: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    await load_session_for(db, user, session_id)
    await db.close()

    async def handler():
        attempt = await service.submit(session_id, "submit", f"user:{user.id}")
        return 200, await _attempt_result(attempt.id)
    return await run_idempotent(user.id, idempotency_key, f"submit:{session_id}", {}, handler)


@router.post("/sessions/{session_id}/stop")
async def stop(session_id: uuid.UUID, user: User = Depends(Authz(Action.session_use)),
               db: AsyncSession = Depends(get_db)):
    sess = await load_session_for(db, user, session_id)
    await db.close()
    if not await service.stop(sess.id, f"user:{user.id}"):
        raise ApiError("invalid_state", "this lab can't be stopped right now", 409)
    return {"stopped": True}


async def _attempt_result(attempt_id: uuid.UUID) -> dict:
    async with sessionmaker()() as db:
        at = await db.get(Attempt, attempt_id)
        assert at is not None
        g = await _latest_grade(db, at.id)
        assert g is not None
        final = await db.scalar(select(GradingEvidence).where(GradingEvidence.attempt_id == at.id,
                                                              GradingEvidence.kind == "final"))
        return {"attempt": {"id": str(at.id), "attempt_no": at.attempt_no, "trigger": at.trigger,
                            "counts": at.counts, "late": at.late, "assignment_id": str(at.assignment_id),
                            "created_at": at.created_at, "regraded": g.created_by is not None},
                "result": student_view(g.result),
                # what the student had built when it was graded (their own resources; from stored evidence)
                "insights": insights(final.payload) if final else None,
                "badges": [{"id": b.badge_id, "title": BY_ID[b.badge_id].title, "icon": BY_ID[b.badge_id].icon,
                            "description": BY_ID[b.badge_id].description, "xp": BY_ID[b.badge_id].xp}
                           for b in (await db.scalars(select(UserBadge).where(UserBadge.attempt_id == at.id))).all()
                           if b.badge_id in BY_ID]}


@router.get("/attempts/{attempt_id}")
async def get_attempt(attempt_id: uuid.UUID, user: User = Depends(Authz(Action.attempt_view_own)),
                      db: AsyncSession = Depends(get_db)):
    at = await load_own_attempt(db, user, attempt_id)
    return await _attempt_result(at.id)


@router.get("/console/services")
async def console_services(session_id: uuid.UUID | None = None, user: User = Depends(Authz(Action.me)),
                           db: AsyncSession = Depends(get_db)):
    """Capability-filtered service catalogue for the console: of the session's engine when a session is
    given (ownership checked), else of the platform default engine. Engine names are never exposed."""
    engine = await sandbox_engine(db, user, session_id) if session_id else emulators.default_engine()
    caps = emulators.get(engine).capabilities
    return {"services": caps.service_status(), "limitations": caps.limitations,
            "features": {svc: caps.features(svc) for svc in caps.services}}
