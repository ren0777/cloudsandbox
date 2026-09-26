"""The lab-session state machine (PLAN §1). This module is the ONLY writer of lab_sessions.state.

    REQUESTED → PROVISIONING → READY ⇄ RESETTING
                     │            ├─(submit | expiry)→ SUBMITTING → SUBMITTED → TERMINATING → TERMINATED
                     ▼            ├─(stop / admin kill)──────────────────────→ TERMINATING
                   FAILED ◀───────┴─(sandbox lost / provisioning / reset / grading infra error)

Every transition is a compare-and-set on (state, version), appends a session_events row and logs
`session.transition`. Subscribers (e.g. open terminals) are notified after commit.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LabSession, SessionEvent, SessionState as S
from ..obs import metrics
from ..obs.logging import log
from . import bus

ALLOWED: dict[S, frozenset[S]] = {
    S.REQUESTED: frozenset({S.PROVISIONING, S.FAILED, S.TERMINATING}),
    S.PROVISIONING: frozenset({S.READY, S.FAILED}),
    S.READY: frozenset({S.RESETTING, S.SUBMITTING, S.FAILED, S.TERMINATING}),
    S.RESETTING: frozenset({S.READY, S.FAILED}),
    S.SUBMITTING: frozenset({S.SUBMITTED, S.FAILED}),
    S.SUBMITTED: frozenset({S.TERMINATING}),
    S.TERMINATING: frozenset({S.TERMINATED}),
    S.TERMINATED: frozenset(),
    S.FAILED: frozenset(),
}
TRANSIENT = (S.PROVISIONING, S.RESETTING, S.SUBMITTING, S.TERMINATING)


class IllegalTransition(Exception):
    pass


def is_allowed(frm: S, to: S) -> bool:
    return to in ALLOWED[frm]


async def transition(db: AsyncSession, session: LabSession, from_states: Iterable[S], to: S, *,
                     reason: str, actor: str, expect_version: int | None = None,
                     **updates: Any) -> bool:
    """CAS transition. Returns False (and changes nothing) if the session is no longer in one of
    `from_states` (or its version moved). Does not commit — call `commit(db)`."""
    frm = tuple(from_states)
    for f in frm:
        if not is_allowed(f, to):
            raise IllegalTransition(f"{f.value} -> {to.value}")
    if "state" in updates or "version" in updates:
        raise ValueError("state/version are managed by transition()")
    # Lock the row, read the true current state, then CAS-update.
    cur = (await db.execute(select(LabSession.state, LabSession.version)
                            .where(LabSession.id == session.id).with_for_update())).first()
    if cur is None or cur.state not in frm or (expect_version is not None and cur.version != expect_version):
        return False
    prev = cur.state
    await db.execute(update(LabSession).where(LabSession.id == session.id, LabSession.version == cur.version)
                     .values(state=to, version=LabSession.version + 1, **updates))
    rid = structlog.contextvars.get_contextvars().get("request_id")
    db.add(SessionEvent(session_id=session.id, from_state=prev.value if prev else None, to_state=to.value,
                        reason=reason, actor=actor, request_id=rid))
    await db.flush()
    await db.refresh(session)
    log.info("session.transition", session_id=str(session.id), sandbox_id=str(session.id),
             user_id=str(session.user_id), assignment_id=str(session.assignment_id),
             runner_id=session.runner_id, from_state=prev.value if prev else None, to_state=to.value,
             reason=reason, actor=actor)
    if to == S.FAILED:
        metrics.session_failures_total.labels(reason=reason).inc()
    db.info.setdefault("pending_events", []).append((session.id, to, reason))
    return True


async def commit(db: AsyncSession) -> None:
    """Commit, then notify subscribers of the transitions made in this transaction."""
    await db.commit()
    events = db.info.pop("pending_events", [])
    for sid, to, reason in events:
        bus.publish(sid, to, reason)


def rollback_events(db: AsyncSession) -> None:
    db.info.pop("pending_events", None)


def now() -> datetime:
    return datetime.now(timezone.utc)


def record_created(db: AsyncSession, session_id: uuid.UUID, actor: str) -> None:
    rid = structlog.contextvars.get_contextvars().get("request_id")
    db.add(SessionEvent(session_id=session_id, from_state=None, to_state=S.REQUESTED.value,
                        reason="start", actor=actor, request_id=rid))
