"""XP, levels and badges (phase 6). Everything is earned from VERIFIED results only — graded attempts that
count, their newest grade (regrades included) and their stored final evidence — never from browser actions.

* XP is derived on read: for every assignment, the best counted score as a percentage of the lab's marks (so
  retrying earns only the improvement, and a regrade is reflected automatically), plus each earned badge's bonus.
* Badges are stored (append-only, one per user and badge) by `award_for_attempt`, which is idempotent and runs
  after an attempt is stored or regraded. `python -m app.gamification backfill` re-evaluates every counted attempt.

Badge rules are pure functions of an `AttemptFacts` record, so they are unit-testable and deterministic."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .labs.importer import definition_of
from .models import Assignment, Attempt, Grade, GradingEvidence, LabVersion, UserBadge
from .obs.logging import log

ALL_SERVICES = frozenset({"s3", "dynamodb", "iam", "ec2", "lambda"})
FREE_TIER_TYPES = frozenset({"t2.micro", "t3.micro"})
LEVELS = [(0, "Trainee"), (100, "Cloud intern"), (250, "Junior cloud engineer"), (450, "Cloud engineer"),
          (700, "Solutions builder"), (1000, "Senior cloud engineer"), (1400, "Cloud architect"),
          (1900, "Principal architect")]


@dataclass(frozen=True)
class AttemptFacts:
    attempt_no: int
    score: Decimal
    max_score: Decimal
    lab_id: str
    lab_kind: str
    services: frozenset[str]
    running_instance_types: tuple[str, ...]
    # services of every lab the student has completed with full marks, including this attempt's if perfect
    perfect_services: frozenset[str] = field(default_factory=frozenset)

    @property
    def perfect(self) -> bool:
        return self.max_score > 0 and self.score >= self.max_score


@dataclass(frozen=True)
class Badge:
    id: str
    title: str
    description: str
    icon: str
    xp: int
    rule: Callable[[AttemptFacts], bool]


BADGES: tuple[Badge, ...] = (
    Badge("first-deploy", "First deployment", "Earned marks on a graded lab for the first time.", "🚀", 10,
          lambda f: f.score > 0),
    Badge("flawless", "Flawless", "Scored full marks on a lab.", "💯", 25, lambda f: f.perfect),
    Badge("first-try", "Right first time", "Full marks on your first attempt at a lab.", "🎯", 40,
          lambda f: f.perfect and f.attempt_no == 1),
    Badge("incident-responder", "Incident responder", "Repaired a break-fix lab with full marks.", "🛠️", 50,
          lambda f: f.perfect and f.lab_kind == "break_fix"),
    Badge("least-privilege", "Least privilege hero", "Full marks on a lab graded on IAM permissions.", "🔐", 30,
          lambda f: f.perfect and "iam" in f.services),
    Badge("serverless-chef", "Serverless chef", "Full marks on a Lambda lab.", "λ", 30,
          lambda f: f.perfect and "lambda" in f.services),
    Badge("right-sized", "Right-sized", "Full marks with only free-tier-sized instances running.", "🪙", 30,
          lambda f: f.perfect and bool(f.running_instance_types)
          and all(t in FREE_TIER_TYPES for t in f.running_instance_types)),
    Badge("full-stack", "Full stack", "Full marks in labs covering S3, DynamoDB, IAM, EC2 and Lambda.", "🏗️", 100,
          lambda f: ALL_SERVICES <= f.perfect_services),
)
BY_ID = {b.id: b for b in BADGES}


def level_for(xp: int) -> dict:
    idx = max(i for i, (need, _) in enumerate(LEVELS) if xp >= need)
    nxt = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else None
    return {"level": idx + 1, "title": LEVELS[idx][1], "xp_for_level": LEVELS[idx][0], "xp_for_next": nxt}


def _pct(score: Decimal, max_score: Decimal) -> int:
    if not max_score:
        return 0
    return int((score * 100 / max_score).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def _latest_score(db: AsyncSession, at: Attempt) -> Decimal:
    g = await db.scalar(select(Grade).where(Grade.attempt_id == at.id).order_by(Grade.created_at.desc()).limit(1))
    return g.score if g else at.score


async def lab_xp(db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID | None = None) -> dict[uuid.UUID, int]:
    """assignment_id → XP (best counted score, as a percentage) for one student, optionally one course."""
    q = select(Attempt).where(Attempt.user_id == user_id, Attempt.counts.is_(True))
    if course_id is not None:
        q = q.join(Assignment, Assignment.id == Attempt.assignment_id).where(Assignment.course_id == course_id)
    best: dict[uuid.UUID, int] = {}
    for at in (await db.scalars(q)).all():
        pct = _pct(await _latest_score(db, at), at.max_score)
        best[at.assignment_id] = max(best.get(at.assignment_id, 0), pct)
    return best


async def progress_of(db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID | None = None) -> dict:
    labs = await lab_xp(db, user_id, course_id)
    rows = (await db.scalars(select(UserBadge).where(UserBadge.user_id == user_id))).all()
    if course_id is not None:  # badges count toward a course when earned from one of its attempts
        ids = {r.attempt_id for r in rows}
        in_course = set((await db.scalars(select(Attempt.id).join(Assignment, Assignment.id == Attempt.assignment_id)
                                          .where(Attempt.id.in_(ids), Assignment.course_id == course_id))).all()) if ids else set()
        rows = [r for r in rows if r.attempt_id in in_course]
    earned = {r.badge_id: r for r in rows if r.badge_id in BY_ID}
    xp = sum(labs.values()) + sum(BY_ID[b].xp for b in earned)
    return {"xp": xp, "lab_xp": sum(labs.values()), "badge_xp": xp - sum(labs.values()), **level_for(xp),
            "badges": [{"id": b.id, "title": b.title, "description": b.description, "icon": b.icon, "xp": b.xp,
                        "earned": b.id in earned, "awarded_at": earned[b.id].awarded_at if b.id in earned else None,
                        "attempt_id": str(earned[b.id].attempt_id) if b.id in earned else None} for b in BADGES]}


async def facts_for(db: AsyncSession, at: Attempt) -> AttemptFacts | None:
    if not at.counts:
        return None
    lv = await db.get(LabVersion, at.lab_version_id)
    if lv is None:
        return None
    d = definition_of(lv)
    score = await _latest_score(db, at)
    final = await db.scalar(select(GradingEvidence).where(GradingEvidence.attempt_id == at.id, GradingEvidence.kind == "final"))
    instances = ((final.payload if final else {}).get("collectors", {}).get("ec2") or {}).get("instances", [])
    running = tuple(sorted(i.get("type") or "" for i in instances if i.get("state") == "running"))
    # services of every lab this student has passed perfectly (for "full stack")
    perfect_services: set[str] = set()
    for other in (await db.scalars(select(Attempt).where(Attempt.user_id == at.user_id, Attempt.counts.is_(True)))).all():
        if await _latest_score(db, other) >= other.max_score > 0:
            olv = await db.get(LabVersion, other.lab_version_id)
            if olv is not None:
                perfect_services |= set(definition_of(olv).services)
    return AttemptFacts(attempt_no=at.attempt_no, score=score, max_score=at.max_score, lab_id=d.id, lab_kind=d.kind,
                        services=frozenset(d.services), running_instance_types=running,
                        perfect_services=frozenset(perfect_services))


async def award_for_attempt(db: AsyncSession, attempt_id: uuid.UUID) -> list[str]:
    """Idempotent: inserts any badges this verified attempt earns and returns the newly awarded ids."""
    at = await db.get(Attempt, attempt_id)
    if at is None:
        return []
    facts = await facts_for(db, at)
    if facts is None:
        return []
    new: list[str] = []
    for b in BADGES:
        if b.rule(facts):
            r = await db.execute(insert(UserBadge).values(user_id=at.user_id, badge_id=b.id, attempt_id=at.id)
                                 .on_conflict_do_nothing(index_elements=["user_id", "badge_id"]))
            if r.rowcount:
                new.append(b.id)
    await db.commit()
    for bid in new:
        log.info("badge.awarded", user_id=str(at.user_id), attempt_id=str(at.id), badge=bid)
    return new


async def backfill() -> int:
    from .db import sessionmaker
    n = 0
    async with sessionmaker()() as db:
        ids = (await db.scalars(select(Attempt.id).where(Attempt.counts.is_(True)).order_by(Attempt.created_at))).all()
    for aid in ids:
        async with sessionmaker()() as db:
            n += len(await award_for_attempt(db, aid))
    return n


if __name__ == "__main__":  # python -m app.gamification backfill
    import sys
    if sys.argv[1:] != ["backfill"]:
        raise SystemExit("usage: python -m app.gamification backfill")
    print(f"awarded {asyncio.run(backfill())} badge(s)")
