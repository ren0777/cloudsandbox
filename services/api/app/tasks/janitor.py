"""Periodic housekeeping (fleet heartbeats come from runtime/fleet.py): session expiry (auto-submit), purge of expired tickets and
idempotency keys. Expiry only ever acts through CAS from READY, so it can never interrupt grading or a
reset (PLAN §2)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select

from ..config import get_settings
from ..db import sessionmaker
from ..errors import ApiError
from ..idempotency import purge_expired
from ..models import ACTIVE_STATES, Assignment, LabSession, SessionState as S, TerminalTicket
from ..obs.logging import log
from ..runtime.fleet import heartbeat_once, seed_runner  # noqa: F401  (re-exported for the app's loops)
from ..sessions import service
from ..sessions import state as st
from ..sessions.windows import standing


async def expire_once() -> list[tuple[str, str]]:
    """Auto-submit READY sessions past TTL, idle timeout or the assignment close."""
    s = get_settings()
    now = st.now()
    due: list[tuple[str, str]] = []
    async with sessionmaker()() as db:
        rows = (await db.scalars(select(LabSession).where(LabSession.state == S.READY,
                                                           LabSession.env == s.env))).all()
        for sess in rows:
            trigger = None
            if sess.expires_at and sess.expires_at <= now:
                trigger = "ttl"
            elif sess.last_activity_at and sess.last_activity_at <= now - timedelta(minutes=sess.idle_minutes):
                trigger = "idle"
            else:
                a = await db.get(Assignment, sess.assignment_id)
                if a is not None and now >= (await standing(db, a, sess.user_id)).close_at:
                    trigger = "close"
            if trigger:
                due.append((str(sess.id), trigger))
    for sid, trigger in due:
        try:
            import uuid
            await service.submit(uuid.UUID(sid), trigger, "system:janitor")
        except ApiError as e:
            log.info("grader.submit.failed", session_id=sid, trigger=trigger, code=e.code)
    async with sessionmaker()() as db:
        await purge_expired(db)
        await db.execute(delete(TerminalTicket).where(TerminalTicket.expires_at < now - timedelta(hours=1)))
        await db.commit()
    return due
