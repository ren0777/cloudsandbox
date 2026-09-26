"""Student progress (XP, level, badges) and course leaderboards (phase 6).

Leaderboards are off by default. Course staff choose `off`, `anonymous` (stable per-course aliases) or `named`
(audited). Students see the top 10 and their own row; staff always see names. XP on a course leaderboard counts
only that course's assignments and the badges earned in it."""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import audit
from .auth.policy import Action, Authz, is_course_staff, is_enrolled, load_course_for_staff
from .db import get_db
from .errors import not_found
from .gamification import progress_of
from .models import Course, Enrolment, Role, User

router = APIRouter(prefix="/api", tags=["progress"])
TOP = 10
_ADJ = ["Swift", "Quiet", "Bright", "Brave", "Calm", "Clever", "Keen", "Lucky", "Nimble", "Sunny", "Bold", "Witty"]
_ANIMAL = ["Otter", "Falcon", "Panda", "Lynx", "Heron", "Koala", "Fox", "Orca", "Ibis", "Yak", "Gecko", "Puffin"]


def alias(course_id: uuid.UUID, user_id: uuid.UUID) -> str:
    h = hashlib.sha256(f"{course_id}:{user_id}".encode()).digest()
    return f"{_ADJ[h[0] % len(_ADJ)]} {_ANIMAL[h[1] % len(_ANIMAL)]} {h[2] % 90 + 10}"


@router.get("/me/progress")
async def my_progress(user: User = Depends(Authz(Action.me)), db: AsyncSession = Depends(get_db)):
    return await progress_of(db, user.id)


@router.get("/courses/{course_id}/leaderboard")
async def leaderboard(course_id: uuid.UUID, user: User = Depends(Authz(Action.me)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Course, course_id)
    staff = c is not None and await is_course_staff(db, user, course_id)
    if c is None or not (staff or (user.role == Role.student and await is_enrolled(db, user, course_id))):
        raise not_found("course")
    if c.leaderboard == "off":
        return {"mode": "off", "entries": [], "me": None}
    students = (await db.scalars(select(User).join(Enrolment, Enrolment.user_id == User.id)
                                 .where(Enrolment.course_id == c.id, User.is_active.is_(True)))).all()
    rows = []
    for s in students:
        p = await progress_of(db, s.id, c.id)
        display = s.name if (c.leaderboard == "named" or staff) else alias(c.id, s.id)
        rows.append({"user_id": s.id, "name": display, "xp": p["xp"], "level": p["level"],
                     "badges": sum(1 for b in p["badges"] if b["earned"]), "you": s.id == user.id})
    rows.sort(key=lambda r: (-r["xp"], r["name"].lower()))
    rank, prev = 0, None
    for i, r in enumerate(rows):
        if r["xp"] != prev:
            rank, prev = i + 1, r["xp"]
        r["rank"] = rank
    me = next((r for r in rows if r["you"]), None)
    shown = rows if staff else rows[:TOP]

    def out(r: dict) -> dict:
        o = {k: v for k, v in r.items() if k != "user_id"}
        if staff:
            o["user_id"] = str(r["user_id"])
        return o
    return {"mode": c.leaderboard, "course": {"id": str(c.id), "code": c.code, "title": c.title},
            "entries": [out(r) for r in shown], "me": out(me) if me else None, "students": len(rows)}


class CourseSettingsIn(BaseModel):
    leaderboard: Literal["off", "anonymous", "named"]


@router.patch("/instructor/courses/{course_id}/settings")
async def course_settings(course_id: uuid.UUID, body: CourseSettingsIn, user: User = Depends(Authz(Action.course_manage)),
                          db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    if c.leaderboard != body.leaderboard:
        audit.record(db, user, "course.settings_changed", course_id=c.id,
                     changes={"leaderboard": [c.leaderboard, body.leaderboard]})
        c.leaderboard = body.leaderboard
        await db.commit()
    return {"leaderboard": c.leaderboard}
