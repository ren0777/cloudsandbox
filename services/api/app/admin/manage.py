"""Admin management (phase 5): users (create staff accounts, role, activation, password reset), course staff,
every running session across runners, and the audit log. All mutations are audited. Instructors read the
audit log of their own courses through `/api/instructor/courses/{id}/audit`."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz, load_course_for_staff
from ..auth.routes import create_user, temporary_password
from ..auth.security import hash_password
from ..db import get_db
from ..errors import ApiError, not_found
from ..labs.importer import definition_of
from ..models import (
    ACTIVE_STATES,
    Assignment,
    AuditEvent,
    Course,
    CourseStaff,
    Enrolment,
    LabSession,
    LabVersion,
    RefreshToken,
    Role,
    User,
)
from ..sessions import state as st

router = APIRouter(prefix="/api/admin", tags=["admin"])
instructor_router = APIRouter(prefix="/api/instructor", tags=["instructor"])


def _user_out(u: User) -> dict:
    return {"id": str(u.id), "name": u.name, "email": u.email, "role": u.role.value, "short_id": u.short_id,
            "active": u.is_active, "must_change_password": u.must_change_password, "created_at": u.created_at}


async def _revoke_refresh(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
                     .values(revoked_at=st.now()))


# -------------------------------------------------------------------------------------------- users
@router.get("/users")
async def list_users(q: str = Query("", max_length=100), role: Role | None = None, limit: int = Query(200, ge=1, le=500),
                     user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    stmt = select(User).order_by(User.role, User.name).limit(limit)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.name).like(like), User.email.like(like), User.short_id.like(like)))
    if role:
        stmt = stmt.where(User.role == role)
    users = (await db.scalars(stmt)).all()
    counts = dict((await db.execute(select(User.role, func.count()).group_by(User.role))).all())
    return {"users": [_user_out(u) for u in users], "totals": {r.value: n for r, n in counts.items()}}


class NewUserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: Role


@router.post("/users", status_code=201)
async def create_account(body: NewUserIn, user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    """Creates an account with a one-time temporary password (students normally come from roster imports)."""
    if await db.scalar(select(User).where(User.email == body.email.lower())):
        raise ApiError("email_taken", "an account with this email already exists", 409)
    pw = temporary_password()
    u = await create_user(db, body.email, body.name, body.role, pw, must_change_password=True)
    await db.flush()
    audit.record(db, user, "user.created", subject_user_id=u.id, email=u.email, role=u.role.value)
    await db.commit()
    return {"user": _user_out(u), "temporary_password": pw}


class UserPatch(BaseModel):
    role: Role | None = None
    active: bool | None = None
    reason: str | None = Field(None, max_length=500)


@router.patch("/users/{user_id}")
async def update_user(user_id: uuid.UUID, body: UserPatch, user: User = Depends(Authz(Action.admin)),
                      db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user_id)
    if u is None:
        raise not_found("user")
    if u.id == user.id:
        raise ApiError("self_change", "you can't change your own role or deactivate yourself", 409)
    changed = []
    if body.role is not None and body.role != u.role:
        if u.is_demo:
            raise ApiError("demo_account", "demo accounts keep their role", 409)
        audit.record(db, user, "user.role_changed", subject_user_id=u.id, email=u.email, previous=u.role.value,
                     role=body.role.value, reason=body.reason)
        u.role = body.role
        await _revoke_refresh(db, u.id)  # the role applies immediately (users are re-read per request); also sign out
        changed.append("role")
    if body.active is not None and body.active != u.is_active:
        u.is_active = body.active
        if not body.active:
            await _revoke_refresh(db, u.id)
        audit.record(db, user, "user.reactivated" if body.active else "user.deactivated", subject_user_id=u.id,
                     email=u.email, reason=body.reason)
        changed.append("active")
    await db.commit()
    return {"user": _user_out(u), "changed": changed}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: uuid.UUID, user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user_id)
    if u is None:
        raise not_found("user")
    if u.is_demo:
        raise ApiError("demo_account", "demo accounts keep their fixed password", 409)
    pw = temporary_password()
    u.password_hash = await hash_password(pw)
    u.must_change_password = True
    await _revoke_refresh(db, u.id)
    audit.record(db, user, "user.password_reset", subject_user_id=u.id, email=u.email)
    await db.commit()
    return {"temporary_password": pw}


# ------------------------------------------------------------------------------------- course staff
@router.get("/courses")
async def all_courses(user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    courses = (await db.scalars(select(Course).order_by(Course.code))).all()
    out = []
    for c in courses:
        staff = (await db.scalars(select(User).join(CourseStaff, CourseStaff.user_id == User.id)
                                  .where(CourseStaff.course_id == c.id).order_by(User.name))).all()
        n = await db.scalar(select(func.count()).select_from(Enrolment).where(Enrolment.course_id == c.id))
        out.append({"id": str(c.id), "code": c.code, "title": c.title, "students": n,
                    "staff": [{"id": str(s.id), "name": s.name, "email": s.email} for s in staff]})
    return {"courses": out}


class StaffIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/courses/{course_id}/staff", status_code=201)
async def add_staff(course_id: uuid.UUID, body: StaffIn, user: User = Depends(Authz(Action.admin)),
                    db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    inst = await db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if inst is None or inst.role != Role.instructor:
        raise ApiError("instructor_not_found", "no instructor account with that email", 404)
    if await db.get(CourseStaff, (c.id, inst.id)):
        raise ApiError("already_staff", f"{inst.email} already teaches this course", 409)
    db.add(CourseStaff(course_id=c.id, user_id=inst.id))
    audit.record(db, user, "course.staff_added", course_id=c.id, subject_user_id=inst.id, email=inst.email)
    await db.commit()
    return {"user_id": str(inst.id)}


@router.delete("/courses/{course_id}/staff/{user_id}", status_code=204)
async def remove_staff(course_id: uuid.UUID, user_id: uuid.UUID, user: User = Depends(Authz(Action.admin)),
                       db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    row = await db.get(CourseStaff, (c.id, user_id))
    if row is None:
        raise not_found("staff member")
    inst = await db.get(User, user_id)
    await db.delete(row)
    audit.record(db, user, "course.staff_removed", course_id=c.id, subject_user_id=user_id,
                 email=inst.email if inst else None)
    await db.commit()


# ----------------------------------------------------------------------------------------- sessions
@router.get("/sessions")
async def active_sessions(user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(LabSession, User, Assignment, Course).join(User, User.id == LabSession.user_id)
        .join(Assignment, Assignment.id == LabSession.assignment_id).join(Course, Course.id == Assignment.course_id)
        .where(LabSession.state.in_(ACTIVE_STATES)).order_by(LabSession.created_at))).all()
    labs: dict[uuid.UUID, str] = {}
    out = []
    for s, u, a, c in rows:
        if a.lab_version_id not in labs:
            lv = await db.get(LabVersion, a.lab_version_id)
            labs[a.lab_version_id] = definition_of(lv).title if lv else ""
        out.append({"session_id": str(s.id), "state": s.state.value, "runner_id": s.runner_id, "engine": s.engine,
                    "student": {"id": str(u.id), "name": u.name, "email": u.email},
                    "course": {"id": str(c.id), "code": c.code}, "assignment": {"id": str(a.id), "title": a.title},
                    "lab": labs[a.lab_version_id], "created_at": s.created_at, "ready_at": s.ready_at,
                    "expires_at": s.expires_at, "last_activity_at": s.last_activity_at})
    return {"server_time": st.now(), "sessions": out}


# -------------------------------------------------------------------------------------------- audit
async def _audit_page(db: AsyncSession, *, course_id: uuid.UUID | None, action: str | None, before: int | None,
                      limit: int) -> dict:
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if course_id:
        q = q.where(AuditEvent.course_id == course_id)
    if action:
        q = q.where(AuditEvent.action == action)
    if before:
        q = q.where(AuditEvent.id < before)
    events = (await db.scalars(q)).all()
    ids = {i for e in events for i in (e.actor_id, e.subject_user_id) if i}
    names = {u.id: u.name for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()} if ids else {}
    course_ids = {e.course_id for e in events if e.course_id}
    codes = {c.id: c.code for c in (await db.scalars(select(Course).where(Course.id.in_(course_ids)))).all()} if course_ids else {}
    items = []
    for e in events:
        o = audit.out(e, names)
        o["course"] = codes.get(e.course_id) if e.course_id else None
        items.append(o)
    return {"events": items, "next_before": events[-1].id if len(events) == limit else None,
            "actions": sorted(audit.ACTIONS)}


@router.get("/audit")
async def audit_log(action: str | None = Query(None, max_length=48), course_id: uuid.UUID | None = None,
                    before: int | None = None, limit: int = Query(100, ge=1, le=500),
                    user: User = Depends(Authz(Action.admin)), db: AsyncSession = Depends(get_db)):
    return await _audit_page(db, course_id=course_id, action=action, before=before, limit=limit)


@instructor_router.get("/courses/{course_id}/audit")
async def course_audit_log(course_id: uuid.UUID, action: str | None = Query(None, max_length=48), before: int | None = None,
                           limit: int = Query(100, ge=1, le=500), user: User = Depends(Authz(Action.audit_view)),
                           db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    return await _audit_page(db, course_id=c.id, action=action, before=before, limit=limit)
