"""Course analytics for instructors (phase 10, milestone 49).

Every number comes from stored rows — `attempts`, `task_results`, `lab_sessions` and the pinned lab
definitions — so an analytics read never touches a sandbox and never re-runs the grader. The whole view
is a fixed handful of queries (enrolments, lab definitions, attempts, sessions, task results) aggregated
in memory: there is deliberately no query inside a loop, so the cost does not grow with class size.

Infrastructure trouble is reported **separately** from student performance: a `FAILED` session is the
platform losing a sandbox, not a student failing a lab, and it never lowers an average.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .labs.importer import definition_of
from .models import Assignment, Attempt, Course, Enrolment, Lab, LabSession, LabVersion, TaskResult

TOP_N = 10


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _money(value: Decimal | float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _avg_money(values: list[Decimal]) -> str | None:
    return _money(mean(values)) if values else None


def _minutes(before: datetime | None, after: datetime | None) -> float | None:
    if before is None or after is None or after < before:
        return None
    return round((after - before).total_seconds() / 60.0, 1)


def _final_for(attempts: list[Attempt], policy: str) -> Decimal:
    """The score the gradebook shows for one student: latest counted attempt, or the best (default)."""
    if policy == "latest":
        return attempts[-1].score
    return max(a.score for a in attempts)


async def course_analytics(db: AsyncSession, course: Course, *, top: int = TOP_N) -> dict[str, Any]:
    enrolled = set(await db.scalars(select(Enrolment.user_id).where(Enrolment.course_id == course.id)))
    head = {"id": str(course.id), "code": course.code, "title": course.title}

    assignments = list((await db.scalars(
        select(Assignment).where(Assignment.course_id == course.id).order_by(Assignment.open_at))).all())
    if not assignments:
        return _empty(head, students=len(enrolled))

    # Pinned lab definitions: titles and the real max score (even for an assignment nobody has started).
    versions = list((await db.scalars(select(LabVersion).join(Lab, Lab.id == LabVersion.lab_id)
                                      .where(LabVersion.id.in_([a.lab_version_id for a in assignments])))).all())
    definitions = {lv.id: definition_of(lv) for lv in versions}

    attempts = list((await db.scalars(
        select(Attempt).where(Attempt.assignment_id.in_([a.id for a in assignments]))
        .order_by(Attempt.created_at))).all())
    sessions = {s.id: s for s in (await db.scalars(
        select(LabSession).where(LabSession.assignment_id.in_([a.id for a in assignments])))).all()}
    task_rows = (await db.execute(
        select(TaskResult, Attempt.assignment_id, Attempt.counts)
        .join(Attempt, Attempt.id == TaskResult.attempt_id)
        .where(Attempt.assignment_id.in_([a.id for a in assignments])))).all()

    by_assignment: dict[Any, list[Attempt]] = defaultdict(list)
    for a in attempts:
        by_assignment[a.assignment_id].append(a)

    # Failure tallies, in memory from the one query above. An auto-submit that changed nothing
    # (`counts=False`) is not evidence that a student failed anything, so it is skipped.
    task_stats: dict[tuple, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "failed": 0})
    check_stats: dict[tuple, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "failed": 0})
    task_titles: dict[tuple, str] = {}
    for tr, assignment_id, counts in task_rows:
        task_titles[(assignment_id, tr.task_id)] = tr.title
        if not counts:
            continue
        task_stats[(assignment_id, tr.task_id)]["attempts"] += 1
        if not tr.passed:
            task_stats[(assignment_id, tr.task_id)]["failed"] += 1
        for c in tr.checks or []:
            key = (assignment_id, tr.task_id, str(c.get("check", "")))
            check_stats[key]["attempts"] += 1
            if not c.get("passed"):
                check_stats[key]["failed"] += 1

    rows_out, totals_scores = [], []
    totals = {"students": len(enrolled), "assignments": len(assignments), "submissions": 0,
              "late_submissions": 0, "interruptions": 0}
    for a in assignments:
        counted = [x for x in by_assignment.get(a.id, []) if x.counts]
        per_student: dict[Any, list[Attempt]] = defaultdict(list)
        for x in counted:
            per_student[x.user_id].append(x)
        finals = [_final_for(v, a.grade_policy) for v in per_student.values()]
        durations = [_minutes((sessions.get(x.session_id).ready_at
                               if sessions.get(x.session_id) else None), x.created_at)
                     for x in counted if x.trigger == "submit"]
        durations = [d for d in durations if d is not None]
        broken = [s for s in sessions.values()
                  if s.assignment_id == a.id and s.state.value == "FAILED"]
        reasons: dict[str, int] = defaultdict(int)
        for s in broken:
            reasons[s.failure_reason or "unknown"] += 1
        late = sum(1 for x in counted if x.late)
        definition = definitions.get(a.lab_version_id)
        rows_out.append({
            "assignment_id": str(a.id), "title": a.title,
            "lab_title": definition.title if definition else a.title,
            "max_score": (str(definition.max_score.quantize(Decimal("0.01")))
                          if definition else _max_of(counted)),
            "students": len(enrolled), "submitted": len(per_student),
            "submission_rate": _rate(len(per_student), len(enrolled)),
            "attempts": len(counted),
            "avg_attempts_used": _money(mean([len(v) for v in per_student.values()])) if per_student else None,
            "avg_score": _avg_money(finals),
            "avg_completion_minutes": round(mean(durations), 1) if durations else None,
            "late_submissions": late,
            "interruptions": len(broken),
            "interruption_reasons": dict(sorted(reasons.items())),
        })
        totals["submissions"] += len(per_student)
        totals["late_submissions"] += late
        totals["interruptions"] += len(broken)
        totals_scores += finals

    asg_titles = {a.id: a.title for a in assignments}

    def rank(stats: dict, kind: str) -> list[dict[str, Any]]:
        ordered = sorted(stats.items(),
                         key=lambda kv: (-kv[1]["failed"],
                                         -(kv[1]["failed"] / max(kv[1]["attempts"], 1)), str(kv[0])))
        out = []
        for key, v in ordered[:top]:
            if not v["failed"]:
                continue
            assignment_id = key[0]
            row = {"assignment_id": str(assignment_id),
                   "assignment_title": asg_titles.get(assignment_id, ""),
                   "task_id": key[1],
                   "task_title": task_titles.get((assignment_id, key[1]), key[1]),
                   "attempts": v["attempts"], "failed": v["failed"],
                   "failure_rate": _rate(v["failed"], v["attempts"])}
            if kind == "check":
                row["check"] = key[2]
            out.append(row)
        return out

    return {
        "course": head,
        "totals": {**totals, "submission_rate": _rate(totals["submissions"], len(enrolled)),
                   "avg_score": _avg_money(totals_scores)},
        "assignments": rows_out,
        "most_failed_tasks": rank(task_stats, "task"),
        "most_missed_checks": rank(check_stats, "check"),
    }


def _max_of(attempts: list[Attempt]) -> str:
    return str(attempts[-1].max_score) if attempts else "0.00"


def _empty(head: dict[str, Any], *, students: int) -> dict[str, Any]:
    return {"course": head,
            "totals": {"students": students, "assignments": 0, "submissions": 0, "submission_rate": 0.0,
                       "late_submissions": 0, "interruptions": 0, "avg_score": None},
            "assignments": [], "most_failed_tasks": [], "most_missed_checks": []}
