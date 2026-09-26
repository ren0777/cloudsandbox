from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..labs.importer import definition_of
from ..labs.render import student_lab_view
from ..models import Attempt, LabSession, LabVersion
from . import state as st


async def session_out(db: AsyncSession, sess: LabSession, with_lab: bool = False) -> dict[str, Any]:
    s = get_settings()
    idle_deadline = idle_warning = None
    if sess.last_activity_at is not None:
        idle_deadline = sess.last_activity_at + timedelta(minutes=sess.idle_minutes)
        idle_warning = idle_deadline - timedelta(minutes=max(1, sess.idle_minutes - s.idle_warning_minutes))
    attempt_id = await db.scalar(select(Attempt.id).where(Attempt.session_id == sess.id))
    out: dict[str, Any] = {
        "id": str(sess.id), "assignment_id": str(sess.assignment_id), "state": sess.state.value,
        "failure_reason": sess.failure_reason, "created_at": sess.created_at, "ready_at": sess.ready_at,
        "expires_at": sess.expires_at, "idle_deadline_at": idle_deadline, "idle_warning_at": idle_warning,
        "ttl_minutes": sess.ttl_minutes, "idle_minutes": sess.idle_minutes, "server_time": st.now(),
        "attempt_id": str(attempt_id) if attempt_id else None,
    }
    if with_lab:
        lv = await db.get(LabVersion, sess.lab_version_id)
        assert lv is not None
        out["lab"] = student_lab_view(definition_of(lv), sess.variables)
    return out
