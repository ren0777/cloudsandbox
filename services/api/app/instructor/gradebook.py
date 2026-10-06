"""Gradebook (phase 5): one row per enrolled student, one cell per assignment, computed with bulk queries.
The score that counts follows the assignment's grade policy over *counted* attempts, using each attempt's
newest grade (regrades win), exactly like the student view (`student.routes.final_score`).

CSV export (course or single assignment) is long format: one line per student × assignment."""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import course_analytics as compute_analytics
from ..auth.policy import Action, Authz, load_assignment_for_staff, load_course_for_staff
from ..db import get_db
from ..labs.importer import definition_of
from ..models import (
    ACTIVE_STATES,
    Assignment,
    Attempt,
    Course,
    Enrolment,
    Grade,
    LabSession,
    LabVersion,
    SessionState as S,
    StudentOverride,
    User,
)
from ..sessions import state as st

router = APIRouter(prefix="/api/instructor", tags=["instructor"])

CSV_COLUMNS = ["student_name", "email", "student_id", "course", "assignment", "lab", "score", "max_score",
               "percentage", "attempts_used", "attempts_allowed", "late", "submitted_at", "status"]


@dataclass
class Cell:
    status: str  # not_open | not_started | in_progress | submitted | interrupted | missed
    score: Decimal | None
    max_score: Decimal
    attempts_used: int
    attempts_allowed: int
    late: bool | None
    submitted_at: datetime | None
    attempt_id: uuid.UUID | None
    attempts: list[dict] = field(default_factory=list)

    @property
    def percentage(self) -> Decimal | None:
        if self.score is None or not self.max_score:
            return None
        return (self.score * 100 / self.max_score).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    def out(self) -> dict[str, Any]:
        return {"status": self.status, "score": str(self.score) if self.score is not None else None,
                "max_score": str(self.max_score), "percentage": str(self.percentage) if self.percentage is not None else None,
                "attempts_used": self.attempts_used, "attempts_allowed": self.attempts_allowed, "late": self.late,
                "submitted_at": self.submitted_at, "attempt_id": str(self.attempt_id) if self.attempt_id else None,
                "attempts": self.attempts}


async def _cells(db: AsyncSession, assignments: list[Assignment], students: list[User]) -> dict[tuple, Cell]:
    now = st.now()
    aids = [a.id for a in assignments]
    uids = [u.id for u in students]
    out: dict[tuple, Cell] = {}
    if not aids or not uids:
        return out
    maxes = {}
    for a in assignments:
        lv = await db.get(LabVersion, a.lab_version_id)
        maxes[a.id] = definition_of(lv).max_score if lv else Decimal(0)
    attempts = (await db.scalars(select(Attempt).where(Attempt.assignment_id.in_(aids), Attempt.user_id.in_(uids))
                                 .order_by(Attempt.attempt_no))).all()
    latest: dict[uuid.UUID, Grade] = {}
    if attempts:
        for g in (await db.scalars(select(Grade).where(Grade.attempt_id.in_([x.id for x in attempts]))
                                   .order_by(Grade.attempt_id, Grade.created_at))).all():
            latest[g.attempt_id] = g  # ordered by created_at → the last one wins
    by_pair: dict[tuple, list[Attempt]] = defaultdict(list)
    for at in attempts:
        by_pair[(at.user_id, at.assignment_id)].append(at)
    extra: dict[tuple, int] = defaultdict(int)
    override_close: dict[tuple, datetime] = {}
    for o in (await db.scalars(select(StudentOverride).where(StudentOverride.assignment_id.in_(aids),
                                                             StudentOverride.user_id.in_(uids)))).all():
        k = (o.user_id, o.assignment_id)
        extra[k] += o.extra_attempts
        if o.close_at_override and (k not in override_close or o.close_at_override > override_close[k]):
            override_close[k] = o.close_at_override
    sessions: dict[tuple, list[LabSession]] = defaultdict(list)
    for s in (await db.scalars(select(LabSession).where(LabSession.assignment_id.in_(aids), LabSession.user_id.in_(uids))
                               .order_by(LabSession.created_at))).all():
        sessions[(s.user_id, s.assignment_id)].append(s)

    for a in assignments:
        base_close = a.close_at if a.allow_late else a.due_at
        for u in students:
            k = (u.id, a.id)
            ats = by_pair.get(k, [])
            views = []
            for at in ats:
                g = latest.get(at.id)
                views.append({"id": str(at.id), "attempt_no": at.attempt_no, "trigger": at.trigger, "counts": at.counts,
                              "late": at.late, "score": str(g.score if g else at.score), "created_at": at.created_at,
                              "regraded": bool(g and g.created_by), "_score": g.score if g else at.score, "_at": at})
            counted = [v for v in views if v["counts"]]
            chosen = None
            if counted:
                chosen = counted[-1] if a.grade_policy == "latest" else max(counted, key=lambda v: v["_score"])
            close = max(base_close, override_close[k]) if k in override_close else base_close
            ss = sessions.get(k, [])
            if chosen is not None:
                status = "submitted"
            elif any(s.state in ACTIVE_STATES for s in ss):
                status = "in_progress"
            elif now < a.open_at:
                status = "not_open"
            elif ss and ss[-1].state == S.FAILED:
                status = "interrupted"
            elif now >= close:
                status = "missed"
            else:
                status = "not_started"
            out[k] = Cell(status=status, score=chosen["_score"] if chosen else None, max_score=maxes[a.id],
                          attempts_used=len(counted), attempts_allowed=a.max_attempts + extra[k],
                          late=chosen["late"] if chosen else None,
                          submitted_at=chosen["created_at"] if chosen else None,
                          attempt_id=chosen["_at"].id if chosen else None,
                          attempts=[{k2: v for k2, v in x.items() if not k2.startswith("_")} for x in views])
    return out


async def _course_data(db: AsyncSession, course: Course, assignment: Assignment | None = None):
    assignments = [assignment] if assignment else list((await db.scalars(
        select(Assignment).where(Assignment.course_id == course.id).order_by(Assignment.due_at, Assignment.title))).all())
    students = list((await db.scalars(select(User).join(Enrolment, Enrolment.user_id == User.id)
                                      .where(Enrolment.course_id == course.id).order_by(User.name, User.email))).all())
    return assignments, students, await _cells(db, assignments, students)


@router.get("/courses/{course_id}/gradebook")
async def gradebook(course_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)), db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    assignments, students, cells = await _course_data(db, c)
    cols = []
    for a in assignments:
        lv = await db.get(LabVersion, a.lab_version_id)
        d = definition_of(lv) if lv else None
        cols.append({"id": str(a.id), "title": a.title, "lab": d.title if d else None,
                     "max_score": str(d.max_score) if d else None, "due_at": a.due_at, "close_at": a.close_at,
                     "grade_policy": a.grade_policy})
    rows = []
    for u in students:
        cs = [cells[(u.id, a.id)] for a in assignments]
        total = sum((x.score or Decimal(0)) for x in cs)
        possible = sum(x.max_score for x in cs)
        rows.append({"user": {"id": str(u.id), "name": u.name, "email": u.email, "short_id": u.short_id},
                     "cells": {str(a.id): cells[(u.id, a.id)].out() for a in assignments},
                     "total": str(total), "possible": str(possible),
                     "percentage": str((total * 100 / possible).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if possible else None})
    return {"course": {"id": str(c.id), "code": c.code, "title": c.title}, "assignments": cols, "students": rows}


def safe(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # spreadsheet formula injection


def _csv(course: Course, assignments: list[Assignment], students: list[User], cells: dict[tuple, Cell],
         labs: dict[uuid.UUID, str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for u in students:
        for a in assignments:
            x = cells[(u.id, a.id)]
            w.writerow([safe(v) for v in (
                u.name, u.email, u.short_id, course.code, a.title, labs.get(a.id), x.score, x.max_score, x.percentage,
                x.attempts_used, x.attempts_allowed, "" if x.late is None else ("yes" if x.late else "no"),
                x.submitted_at.isoformat() if x.submitted_at else "", x.status)])
    return buf.getvalue()


async def _labs(db: AsyncSession, assignments: list[Assignment]) -> dict[uuid.UUID, str]:
    out = {}
    for a in assignments:
        lv = await db.get(LabVersion, a.lab_version_id)
        out[a.id] = definition_of(lv).title if lv else ""
    return out


def _download(text: str, filename: str) -> Response:
    return Response("﻿" + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in s).strip("-").lower()[:60] or "export"


@router.get("/courses/{course_id}/gradebook.csv")
async def gradebook_csv(course_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)), db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    assignments, students, cells = await _course_data(db, c)
    text = _csv(c, assignments, students, cells, await _labs(db, assignments))
    return _download(text, f"{_slug(c.code)}-gradebook-{st.now():%Y%m%d}.csv")


@router.get("/assignments/{assignment_id}/grades.csv")
async def assignment_csv(assignment_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)),
                         db: AsyncSession = Depends(get_db)):
    a = await load_assignment_for_staff(db, user, assignment_id)
    c = await db.get(Course, a.course_id)
    assert c is not None
    assignments, students, cells = await _course_data(db, c, a)
    text = _csv(c, assignments, students, cells, await _labs(db, assignments))
    return _download(text, f"{_slug(c.code)}-{_slug(a.title)}-grades-{st.now():%Y%m%d}.csv")


@router.get("/courses/{course_id}/analytics")
async def course_analytics(course_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)),
                           db: AsyncSession = Depends(get_db)):
    """The teaching view: per-assignment averages, submission rate, attempts used, completion time, late
    submissions, most-failed tasks and most-missed checks — plus infrastructure interruptions counted
    **separately**, so a platform failure never reads as a student failing.

    Staff of that course only (404 otherwise; admins see everything). Every figure comes from stored rows,
    so this never reaches a sandbox."""
    c = await load_course_for_staff(db, user, course_id)
    return await compute_analytics(db, c)


ANALYTICS_CSV_COLUMNS = ["course_code", "assignment", "lab", "max_score", "students", "submitted",
                         "submission_rate_pct", "counted_attempts", "avg_attempts_used", "avg_score",
                         "avg_completion_minutes", "late_submissions", "interruptions", "interruption_reasons"]


def _pct(rate: float) -> float:
    return round(rate * 100, 1)


def _analytics_csv(stats: dict[str, Any]) -> str:
    """One row per assignment, then an "All labs" totals row. The ranked failure lists stay on the page
    (they are top-N views, not a table); interruptions keep their own columns, apart from the scores."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(ANALYTICS_CSV_COLUMNS)
    code = stats["course"]["code"]
    for r in stats["assignments"]:
        reasons = "; ".join(f"{k}: {v}" for k, v in r["interruption_reasons"].items())
        w.writerow([safe(v) for v in (
            code, r["title"], r["lab_title"], r["max_score"], r["students"], r["submitted"],
            _pct(r["submission_rate"]), r["attempts"], r["avg_attempts_used"], r["avg_score"],
            r["avg_completion_minutes"], r["late_submissions"], r["interruptions"], reasons)])
    t = stats["totals"]
    w.writerow([safe(v) for v in (
        code, "All labs", "", "", t["students"], t["submissions"], _pct(t["submission_rate"]), "", "",
        t["avg_score"], "", t["late_submissions"], t["interruptions"], "")])
    return buf.getvalue()


@router.get("/courses/{course_id}/analytics.csv")
async def course_analytics_csv(course_id: uuid.UUID, user: User = Depends(Authz(Action.results_view)),
                               db: AsyncSession = Depends(get_db)):
    """The per-assignment analytics table as CSV, from the same computation as the page (same access rule)."""
    c = await load_course_for_staff(db, user, course_id)
    text = _analytics_csv(await compute_analytics(db, c))
    return _download(text, f"{_slug(c.code)}-analytics-{st.now():%Y%m%d}.csv")
