"""Instructor API (PLAN §6, §9): results, per-check evidence, regrade (new grade row, original kept),
reopen interrupted sessions (extra attempt / deadline extension, audited), create assignments."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import (
    Action,
    Authz,
    is_course_staff,
    load_assignment_for_staff,
    load_attempt_for_staff,
)
from ..config import get_settings
from ..db import get_db
from ..errors import ApiError, not_found
from ..grader.grade import grade, to_json
from ..insights import insights
from ..labs.importer import definition_of
from ..models import (
    ACTIVE_STATES,
    Assignment,
    Attempt,
    Course,
    CourseStaff,
    Enrolment,
    Grade,
    GradingEvidence,
    Lab,
    LabSession,
    LabVersion,
    Role,
    SessionEvent,
    SessionState as S,
    StudentOverride,
    TaskResult,
    User,
)
from ..obs.logging import bind, log
from ..sessions.windows import standing
from ..student.routes import final_score

router = APIRouter(prefix="/api/instructor", tags=["instructor"])


@router.get("/courses")
async def my_courses(user: User = Depends(Authz(Action.results_view)), db: AsyncSession = Depends(get_db)):
    q = select(Course).order_by(Course.code)
    if user.role != Role.admin:
        q = q.join(CourseStaff, CourseStaff.course_id == Course.id).where(CourseStaff.user_id == user.id)
    out = []
    for c in (await db.scalars(q)).all():
        asgs = (await db.scalars(select(Assignment).where(Assignment.course_id == c.id)
                                 .order_by(Assignment.due_at))).all()
        n = len((await db.scalars(select(Enrolment.user_id).where(Enrolment.course_id == c.id))).all())
        out.append({"id": str(c.id), "code": c.code, "title": c.title, "students": n,
                    "assignments": [{"id": str(a.id), "title": a.title, "due_at": a.due_at,
                                     "close_at": a.close_at} for a in asgs]})
    return {"courses": out}


@router.get("/assignments/{assignment_id}/results")
async def results(assignment_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)),
                  db: AsyncSession = Depends(get_db)):
    a = await load_assignment_for_staff(db, user, assignment_id)
    bind(assignment_id=a.id)
    lv = await db.get(LabVersion, a.lab_version_id)
    assert lv is not None
    students = (await db.scalars(select(User).join(Enrolment, Enrolment.user_id == User.id)
                                 .where(Enrolment.course_id == a.course_id).order_by(User.name))).all()
    rows = []
    for stu in students:
        attempts = []
        for at in (await db.scalars(select(Attempt).where(Attempt.assignment_id == a.id,
                                                          Attempt.user_id == stu.id)
                                    .order_by(Attempt.attempt_no))).all():
            g = await db.scalar(select(Grade).where(Grade.attempt_id == at.id)
                                .order_by(Grade.created_at.desc()).limit(1))
            attempts.append({"id": str(at.id), "attempt_no": at.attempt_no, "trigger": at.trigger,
                             "counts": at.counts, "late": at.late, "score": str(g.score if g else at.score),
                             "max_score": str(at.max_score), "regraded": bool(g and g.created_by),
                             "created_at": at.created_at})
        sessions = (await db.scalars(select(LabSession).where(LabSession.assignment_id == a.id,
                                                              LabSession.user_id == stu.id)
                                     .order_by(LabSession.created_at))).all()
        stand = await standing(db, a, stu.id)
        rows.append({
            "user": {"id": str(stu.id), "name": stu.name, "email": stu.email, "short_id": stu.short_id},
            "attempts": attempts, "final_score": final_score(attempts, a.grade_policy),
            "attempts_used": stand.attempts_used, "attempts_allowed": stand.attempts_allowed,
            "close_at": stand.close_at,
            "active_session": next(({"id": str(x.id), "state": x.state.value} for x in sessions
                                    if x.state in ACTIVE_STATES), None),
            "interrupted": [{"session_id": str(x.id), "reason": x.failure_reason, "at": x.ended_at}
                            for x in sessions if x.state == S.FAILED],
        })
    d = definition_of(lv)
    return {"assignment": {"id": str(a.id), "title": a.title, "lab": d.title, "lab_version": d.version,
                           "lab_version_id": str(a.lab_version_id), "course_id": str(a.course_id),
                           "allow_late": a.allow_late,
                           "open_at": a.open_at, "due_at": a.due_at, "close_at": a.close_at,
                           "max_attempts": a.max_attempts, "grade_policy": a.grade_policy,
                           "max_score": str(d.max_score)},
            "students": rows}


@router.get("/attempts/{attempt_id}")
async def attempt_detail(attempt_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)),
                         db: AsyncSession = Depends(get_db)):
    at = await load_attempt_for_staff(db, user, attempt_id)
    bind(attempt_id=at.id, session_id=at.session_id)
    stu = await db.get(User, at.user_id)
    assert stu is not None
    tasks = list((await db.scalars(select(TaskResult).where(TaskResult.attempt_id == at.id))).all())
    lv = await db.get(LabVersion, at.lab_version_id)
    order = {t.id: i for i, t in enumerate(definition_of(lv).tasks)} if lv else {}
    tasks.sort(key=lambda t: (order.get(t.task_id, len(order)), t.task_id))  # the lab's task order
    grades = (await db.scalars(select(Grade).where(Grade.attempt_id == at.id).order_by(Grade.created_at))).all()
    final = await db.scalar(select(GradingEvidence).where(GradingEvidence.attempt_id == at.id,
                                                          GradingEvidence.kind == "final"))
    baselines = (await db.scalars(select(GradingEvidence).where(
        GradingEvidence.session_id == at.session_id, GradingEvidence.kind == "baseline")
        .order_by(GradingEvidence.captured_at))).all()
    events = (await db.scalars(select(SessionEvent).where(SessionEvent.session_id == at.session_id)
                               .order_by(SessionEvent.id))).all()
    return {
        "attempt": {"id": str(at.id), "attempt_no": at.attempt_no, "trigger": at.trigger, "counts": at.counts,
                    "late": at.late, "score": str(at.score), "max_score": str(at.max_score),
                    "grader_version": at.grader_version, "emulator_image_digest": at.emulator_image_digest,
                    "variables": at.variables, "assignment_id": str(at.assignment_id),
                    "session_id": str(at.session_id), "created_at": at.created_at},
        "student": {"id": str(stu.id), "name": stu.name, "email": stu.email},
        "tasks": [{"task_id": t.task_id, "title": t.title, "passed": t.passed,
                   "marks_awarded": str(t.marks_awarded), "marks_possible": str(t.marks_possible),
                   "checks": t.checks} for t in tasks],
        "grades": [{"id": str(g.id), "score": str(g.score), "max_score": str(g.max_score),
                    "grader_version": g.grader_version, "reason": g.reason,
                    "created_by": str(g.created_by) if g.created_by else None, "created_at": g.created_at}
                   for g in grades],
        "insights": insights(final.payload) if final else None,
        "evidence": {"final": {"sha256": final.sha256, "normalized_sha256": final.normalized_sha256,
                               "captured_at": final.captured_at, "payload": final.payload} if final else None,
                     "baselines": [{"sha256": b.sha256, "normalized_sha256": b.normalized_sha256,
                                    "captured_at": b.captured_at} for b in baselines]},
        "events": [{"from": e.from_state, "to": e.to_state, "reason": e.reason, "actor": e.actor,
                    "request_id": e.request_id, "at": e.created_at} for e in events],
    }


class RegradeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/attempts/{attempt_id}/regrade")
async def regrade(attempt_id: uuid.UUID, body: RegradeIn, user: User = Depends(Authz(Action.grade_regrade)),
                  db: AsyncSession = Depends(get_db)):
    """Re-run the pure grader on the STORED evidence; inserts a new grade row, never edits the old one."""
    at = await load_attempt_for_staff(db, user, attempt_id)
    ev = await db.scalar(select(GradingEvidence).where(GradingEvidence.attempt_id == at.id,
                                                       GradingEvidence.kind == "final"))
    lv = await db.get(LabVersion, at.lab_version_id)
    if ev is None or lv is None:
        raise ApiError("no_evidence", "no stored evidence for this attempt", 409)
    result = grade(definition_of(lv), at.variables, ev.payload)
    g = Grade(attempt_id=at.id, grader_version=get_settings().grader_version, score=result["score"],
              max_score=result["max_score"], result=to_json(result), created_by=user.id, reason=body.reason)
    db.add(g)
    asg = await db.get(Assignment, at.assignment_id)
    audit.record(db, user, "grade.regraded", course_id=asg.course_id if asg else None, assignment_id=at.assignment_id,
                 subject_user_id=at.user_id, session_id=at.session_id, attempt_id=at.id, reason=body.reason,
                 previous_score=str(at.score), score=str(result["score"]), grader_version=g.grader_version)
    await db.commit()
    log.info("grade.regraded", attempt_id=str(at.id), user_id=str(user.id), score=str(result["score"]),
             previous=str(at.score))
    from ..sessions.service import award_badges
    await award_badges(at.id)  # a regrade can earn badges (never removes them)
    return {"grade_id": str(g.id), "score": str(result["score"]), "max_score": str(result["max_score"])}


class OverrideIn(BaseModel):
    user_id: uuid.UUID
    extra_attempts: int = Field(0, ge=0, le=10)
    close_at_override: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _something(self) -> "OverrideIn":
        if self.extra_attempts == 0 and self.close_at_override is None:
            raise ValueError("grant at least one extra attempt or a new close time")
        return self


@router.post("/assignments/{assignment_id}/overrides", status_code=201)
async def grant_override(assignment_id: uuid.UUID, body: OverrideIn,
                         user: User = Depends(Authz(Action.override_grant)), db: AsyncSession = Depends(get_db)):
    a = await load_assignment_for_staff(db, user, assignment_id)
    enrolled = await db.scalar(select(Enrolment).where(Enrolment.course_id == a.course_id,
                                                       Enrolment.user_id == body.user_id))
    if enrolled is None:
        raise not_found("student")
    o = StudentOverride(assignment_id=a.id, user_id=body.user_id, extra_attempts=body.extra_attempts,
                        close_at_override=body.close_at_override, reason=body.reason, created_by=user.id)
    db.add(o)
    if body.extra_attempts:
        audit.record(db, user, "attempts.granted", course_id=a.course_id, assignment_id=a.id,
                     subject_user_id=body.user_id, extra_attempts=body.extra_attempts, reason=body.reason)
    if body.close_at_override is not None:
        audit.record(db, user, "deadline.extended", course_id=a.course_id, assignment_id=a.id,
                     subject_user_id=body.user_id, close_at=body.close_at_override, previous_close_at=a.close_at,
                     reason=body.reason)
    await db.commit()
    log.info("assignment.override.granted", assignment_id=str(a.id), user_id=str(body.user_id),
             granted_by=str(user.id), extra_attempts=body.extra_attempts,
             close_at_override=str(body.close_at_override), reason=body.reason)
    return {"id": str(o.id)}


@router.get("/lab-versions")
async def lab_versions(user: User = Depends(Authz(Action.lab_manage)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(LabVersion, Lab).join(Lab, Lab.id == LabVersion.lab_id)
                             .order_by(Lab.slug, LabVersion.created_at))).all()
    return {"lab_versions": [{"id": str(v.id), "lab": lab.slug, "title": lab.title, "version": v.version,
                              "content_sha256": v.content_sha256, "created_at": v.created_at}
                             for v, lab in rows]}


class AssignmentIn(BaseModel):
    course_id: uuid.UUID
    lab_version_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    open_at: datetime
    due_at: datetime
    close_at: datetime
    allow_late: bool = False
    max_attempts: int | None = Field(None, ge=1, le=20)
    grade_policy: str = Field("best", pattern=r"^(best|latest)$")

    @model_validator(mode="after")
    def _order(self) -> "AssignmentIn":
        if not (self.open_at < self.due_at <= self.close_at):
            raise ValueError("require open_at < due_at <= close_at")
        return self


@router.post("/assignments", status_code=201)
async def create_assignment(body: AssignmentIn, user: User = Depends(Authz(Action.lab_manage)),
                            db: AsyncSession = Depends(get_db)):
    if await db.get(Course, body.course_id) is None or not await is_course_staff(db, user, body.course_id):
        raise not_found("course")
    lv = await db.get(LabVersion, body.lab_version_id)
    if lv is None:
        raise not_found("lab version")
    a = Assignment(course_id=body.course_id, lab_version_id=lv.id, title=body.title, open_at=body.open_at,
                   due_at=body.due_at, close_at=body.close_at, allow_late=body.allow_late,
                   max_attempts=body.max_attempts or definition_of(lv).max_attempts,
                   grade_policy=body.grade_policy, created_by=user.id)
    db.add(a)
    await db.flush()
    audit.record(db, user, "assignment.created", course_id=a.course_id, assignment_id=a.id, title=a.title,
                 lab_version_id=lv.id, open_at=a.open_at, due_at=a.due_at, close_at=a.close_at,
                 max_attempts=a.max_attempts, grade_policy=a.grade_policy, allow_late=a.allow_late)
    await db.commit()
    return {"id": str(a.id)}


class AssignmentPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    lab_version_id: uuid.UUID | None = None
    open_at: datetime | None = None
    due_at: datetime | None = None
    close_at: datetime | None = None
    allow_late: bool | None = None
    max_attempts: int | None = Field(None, ge=1, le=20)
    grade_policy: str | None = Field(None, pattern=r"^(best|latest)$")
    reason: str | None = Field(None, max_length=500)


@router.patch("/assignments/{assignment_id}")
async def update_assignment(assignment_id: uuid.UUID, body: AssignmentPatch, user: User = Depends(Authz(Action.lab_manage)),
                            db: AsyncSession = Depends(get_db)):
    """Edit an assignment. The pinned lab version can change only before any student has started it
    (attempts must stay reproducible against the version they ran). Changes are audited field by field."""
    a = await load_assignment_for_staff(db, user, assignment_id)
    fields = body.model_dump(exclude_unset=True, exclude={"reason"})
    changes: dict[str, list] = {}
    if "lab_version_id" in fields and fields["lab_version_id"] != a.lab_version_id:
        if fields["lab_version_id"] is None or await db.get(LabVersion, fields["lab_version_id"]) is None:
            raise not_found("lab version")
        started = await db.scalar(select(LabSession.id).where(LabSession.assignment_id == a.id).limit(1))
        if started is not None:
            raise ApiError("assignment_started", "students have already started this assignment, so its lab "
                           "version is fixed; create a new assignment instead", 409)
    for k, v in fields.items():
        if v is None:
            raise ApiError("validation_error", f"{k} cannot be empty", 400)
        if getattr(a, k) != v:
            changes[k] = [getattr(a, k), v]
            setattr(a, k, v)
    if not (a.open_at < a.due_at <= a.close_at):
        raise ApiError("validation_error", "require open_at < due_at <= close_at", 400)
    if changes:
        audit.record(db, user, "assignment.updated", course_id=a.course_id, assignment_id=a.id, changes=changes,
                     reason=body.reason)
        await db.commit()
    return {"id": str(a.id), "changed": sorted(changes)}


@router.delete("/assignments/{assignment_id}", status_code=204)
async def delete_assignment(assignment_id: uuid.UUID, user: User = Depends(Authz(Action.lab_manage)),
                            db: AsyncSession = Depends(get_db)):
    """Only assignments nobody has started can be deleted; otherwise results would be lost."""
    a = await load_assignment_for_staff(db, user, assignment_id)
    if await db.scalar(select(LabSession.id).where(LabSession.assignment_id == a.id).limit(1)) is not None:
        raise ApiError("assignment_started", "students have started this assignment, so it can't be deleted; "
                       "close it by moving its close time instead", 409)
    if await db.scalar(select(StudentOverride.id).where(StudentOverride.assignment_id == a.id).limit(1)) is not None:
        raise ApiError("assignment_started", "this assignment has student extensions recorded, so it can't be deleted", 409)
    audit.record(db, user, "assignment.deleted", course_id=a.course_id, assignment_id=a.id, title=a.title,
                 lab_version_id=a.lab_version_id)
    await db.delete(a)
    await db.commit()
