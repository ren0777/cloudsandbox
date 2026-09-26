"""Audit trail for instructor/admin actions (phase 5). `record()` adds an append-only `audit_events` row
to the caller's transaction, so the action and its audit row commit (or roll back) together, and logs
`audit.recorded`. Action names come only from ACTIONS (like the log event set, PLAN §14)."""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent, User
from .obs.logging import log

ACTIONS: frozenset[str] = frozenset({
    "course.created", "course.staff_added", "course.staff_removed", "course.settings_changed",
    "roster.imported", "enrolment.added", "enrolment.removed",
    "assignment.created", "assignment.updated", "assignment.deleted",
    "deadline.extended", "attempts.granted",
    "grade.regraded",
    "session.terminated", "session.extended",
    "runner.registered", "runner.drained", "runner.resumed", "runner.retired",
    "user.created", "user.role_changed", "user.deactivated", "user.reactivated", "user.password_reset",
})


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def record(db: AsyncSession, actor: User | None, action: str, *, course_id: uuid.UUID | None = None,
           assignment_id: uuid.UUID | None = None, subject_user_id: uuid.UUID | None = None,
           session_id: uuid.UUID | None = None, **details: Any) -> AuditEvent:
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")
    rid = structlog.contextvars.get_contextvars().get("request_id")
    # actor None = an operator using a server-side command (e.g. `python -m app.runtime.fleet drain`)
    ev = AuditEvent(actor_id=actor.id if actor else None, actor_role=actor.role.value if actor else "operator",
                    action=action, course_id=course_id,
                    assignment_id=assignment_id, subject_user_id=subject_user_id, session_id=session_id,
                    details=_jsonable(details), request_id=rid)
    db.add(ev)
    log.info("audit.recorded", action=action, actor_id=str(actor.id) if actor else "operator",
             course_id=str(course_id) if course_id else None,
             assignment_id=str(assignment_id) if assignment_id else None,
             subject_user_id=str(subject_user_id) if subject_user_id else None)
    return ev


def out(e: AuditEvent, names: dict[uuid.UUID, str] | None = None) -> dict[str, Any]:
    names = names or {}
    return {"id": e.id, "at": e.created_at, "action": e.action, "actor_id": str(e.actor_id) if e.actor_id else None,
            "actor": names.get(e.actor_id) if e.actor_id else None, "actor_role": e.actor_role,
            "course_id": str(e.course_id) if e.course_id else None,
            "assignment_id": str(e.assignment_id) if e.assignment_id else None,
            "subject_user_id": str(e.subject_user_id) if e.subject_user_id else None,
            "subject": names.get(e.subject_user_id) if e.subject_user_id else None,
            "session_id": str(e.session_id) if e.session_id else None,
            "details": e.details, "request_id": e.request_id}
