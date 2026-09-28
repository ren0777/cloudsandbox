"""Comparing two attempts of the same assignment (phase 10, milestone 48).

Everything here reads **stored** rows: each attempt's newest `grades.result` (the same row the results
page and the gradebook already show, so a regrade is reflected automatically) — never a sandbox, never a
live capture, and nothing is written. The evidence and grades behind both sides are append-only, so a diff
is reproducible forever.

PLAN §7b still applies: a student's diff never carries `expected`, `actual` or check parameters. They get
the same message and pass/fail a student already sees; instructors get the full comparison.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Attempt, Grade

HIDDEN_LABEL = "Hidden requirement"
HIDDEN_PASSED = "Hidden requirement met."
HIDDEN_FAILED = "A hidden requirement for this task is not met yet."


async def latest_grade(db: AsyncSession, attempt_id: uuid.UUID) -> Grade | None:
    """The grade the student sees: newest wins (an original, or a regrade)."""
    return await db.scalar(select(Grade).where(Grade.attempt_id == attempt_id)
                           .order_by(Grade.created_at.desc()).limit(1))


async def previous_attempt(db: AsyncSession, attempt: Attempt) -> Attempt | None:
    """The attempt this one should be compared against: the previous attempt that **counted**. An
    auto-submitted attempt that changed nothing (`counts=False`) was never the student's work, so it is
    skipped rather than reported as a wall of regressions."""
    return await db.scalar(select(Attempt).where(Attempt.user_id == attempt.user_id,
                                                 Attempt.assignment_id == attempt.assignment_id,
                                                 Attempt.attempt_no < attempt.attempt_no,
                                                 Attempt.counts.is_(True))
                           .order_by(Attempt.attempt_no.desc()).limit(1))


# ------------------------------------------------------------------------------------- the comparison
def _param_key(params: Any) -> str:
    return json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _index(result: dict[str, Any] | None) -> dict[tuple[str, str, str], tuple[dict, dict]]:
    """(task_id, check type, canonical params) → (task row, check row). A lab version is pinned per
    assignment, so both sides list the same checks; the params key makes a reordered list still line up,
    and duplicates inside one task are disambiguated by an occurrence counter."""
    out: dict[tuple[str, str, str], tuple[dict, dict]] = {}
    seen: dict[tuple[str, str], int] = {}
    for t in (result or {}).get("tasks", []):
        task_id = str(t.get("task_id", ""))
        for c in t.get("checks", []):
            base = (task_id, str(c.get("check", "")))
            n = seen.get(base, 0)
            seen[base] = n + 1
            key = (task_id, base[1], f"{n}:{_param_key(c.get('params'))}")
            out[key] = (t, c)
    return out


def _label(task: dict, check: dict, index: int, public: bool) -> str:
    if check.get("hidden"):
        return f"{task.get('title', '')} · {HIDDEN_LABEL}" if public else \
            f"{task.get('title', '')} · {check.get('check', '')} (hidden)"
    name = str(check.get("check") or f"check {index + 1}")
    return f"{task.get('title', '')} · {name}"


def _side(check: dict, public: bool) -> dict[str, Any]:
    """One side of a comparison. A hidden check keeps its generic message, exactly like the results page;
    `expected`, `actual` and `params` are instructor-only (PLAN §7b)."""
    if check.get("hidden"):
        message = HIDDEN_PASSED if check.get("passed") else HIDDEN_FAILED
    else:
        message = str(check.get("message") or "")
    out: dict[str, Any] = {"passed": bool(check.get("passed")), "message": message,
                           "marks_awarded": str(check.get("marks_awarded", "0.00")),
                           "marks_possible": str(check.get("marks_possible", "0.00"))}
    if not public:
        out.update(expected=check.get("expected"), actual=check.get("actual"))
    return out


def compare(previous: dict[str, Any] | None, current: dict[str, Any], *, public: bool) -> dict[str, Any]:
    """Check-by-check comparison of two stored grade results.

    `public` is the student view: no expected/actual/params, hidden checks reduced to their generic
    message. The first attempt (`previous is None`) returns an empty `tasks` list — there is nothing to
    compare — rather than presenting every check as "added"."""
    zeros = {k: 0 for k in ("fixed", "regressed", "unchanged", "added", "removed")}
    score_after = str(current.get("score")) if current else None
    if previous is None:
        return {"first_attempt": True, "tasks": [],
                "summary": {**zeros, "score_before": None, "score_after": score_after, "delta": None}}

    before = _index(previous)
    after = _index(current)
    counts = dict(zeros)

    tasks: list[dict[str, Any]] = []
    # Walk the current result so the lab's own task order is preserved, then the previous-only leftovers.
    seen_tasks: set[str] = set()
    ordered = list((current or {}).get("tasks", []))
    ordered += [t for t in (previous or {}).get("tasks", []) if t.get("task_id") not in
                {x.get("task_id") for x in ordered}]
    for t in ordered:
        task_id = str(t.get("task_id", ""))
        if task_id in seen_tasks:
            continue
        seen_tasks.add(task_id)
        keys = [k for k in list(before) + list(after) if k[0] == task_id]
        # de-duplicate while keeping the current-result order first
        keys = list(dict.fromkeys(keys))
        rows = []
        for i, key in enumerate(keys):
            b, a = before.get(key), after.get(key)
            if b is None:
                change = "added"
                label_task = t
            elif a is None:
                change = "removed"
                label_task = b[0]
            else:
                label_task = a[0]
                change = ("unchanged" if bool(b[1].get("passed")) == bool(a[1].get("passed"))
                          else "fixed" if a[1].get("passed") else "regressed")
            counts[change] += 1
            rows.append({
                "check": key[1], "label": _label(label_task, (a or b)[1], i, public),
                "hidden": bool((a or b)[1].get("hidden")), "change": change,
                "before": _side(b[1], public) if b else None,
                "after": _side(a[1], public) if a else None,
            })
        if not rows:
            continue
        pb = next((x for x in (previous or {}).get("tasks", []) if x.get("task_id") == task_id), None)
        pa = next((x for x in (current or {}).get("tasks", []) if x.get("task_id") == task_id), None)
        tasks.append({"task_id": task_id, "title": (pa or pb or {}).get("title", task_id),
                      "passed": {"before": bool(pb["passed"]) if pb else None,
                                 "after": bool(pa["passed"]) if pa else None},
                      "marks_awarded": {"before": str(pb["marks_awarded"]) if pb else None,
                                        "after": str(pa["marks_awarded"]) if pa else None},
                      "checks": rows})

    score_before = str(previous.get("score")) if previous else None
    score_after = str(current.get("score")) if current else None
    delta = None
    if score_before is not None and score_after is not None:
        delta = f"{float(score_after) - float(score_before):+.2f}"
    return {"first_attempt": previous is None, "tasks": tasks,
            "summary": {**counts, "score_before": score_before, "score_after": score_after, "delta": delta}}


# ------------------------------------------------------------------------------- loading a real pair
async def diff_for(db: AsyncSession, attempt: Attempt, *, public: bool) -> dict[str, Any]:
    """The diff for one attempt against the previous counted attempt, or a graceful first-attempt body."""
    current_grade = await latest_grade(db, attempt.id)
    prev = await previous_attempt(db, attempt)
    prev_grade = await latest_grade(db, prev.id) if prev is not None else None

    def head(a: Attempt, g: Grade | None) -> dict[str, Any]:
        return {"attempt_id": str(a.id), "attempt_no": a.attempt_no, "trigger": a.trigger,
                "counts": a.counts, "late": a.late, "created_at": a.created_at,
                "score": str(g.score) if g else str(a.score),
                "max_score": str(g.max_score if g else a.max_score),
                "regraded": bool(g and g.created_by is not None)}

    body = compare(prev_grade.result if prev_grade else None,
                   current_grade.result if current_grade else {}, public=public)
    body["previous"] = head(prev, prev_grade) if prev is not None and prev_grade is not None else None
    body["current"] = head(attempt, current_grade)
    return body
