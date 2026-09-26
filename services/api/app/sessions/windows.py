"""Assignment windows, attempt accounting and instructor overrides (PLAN §4, §5)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Assignment, Attempt, StudentOverride


@dataclass(frozen=True)
class Standing:
    open_at: datetime
    due_at: datetime
    close_at: datetime  # effective close for this student (late window / override applied)
    override_close_at: datetime | None
    attempts_used: int
    attempts_allowed: int

    @property
    def attempts_left(self) -> int:
        return max(0, self.attempts_allowed - self.attempts_used)

    def is_open(self, now: datetime) -> bool:
        return self.open_at <= now < self.close_at

    def is_late(self, now: datetime) -> bool:
        if self.override_close_at is not None and now < self.override_close_at:
            return False
        return now > self.due_at


async def standing(db: AsyncSession, a: Assignment, user_id: uuid.UUID) -> Standing:
    extra, override_close = (await db.execute(
        select(func.coalesce(func.sum(StudentOverride.extra_attempts), 0),
               func.max(StudentOverride.close_at_override))
        .where(StudentOverride.assignment_id == a.id, StudentOverride.user_id == user_id))).one()
    used = await db.scalar(select(func.count()).select_from(Attempt).where(
        Attempt.assignment_id == a.id, Attempt.user_id == user_id, Attempt.counts.is_(True))) or 0
    base_close = a.close_at if a.allow_late else a.due_at
    close = max(base_close, override_close) if override_close else base_close
    return Standing(a.open_at, a.due_at, close, override_close, int(used), a.max_attempts + int(extra))
