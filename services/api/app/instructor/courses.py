"""Courses, rosters and enrolments (phase 5). Staff manage their own courses; admins manage all.

Roster CSV import is two-step: `preview` validates every row and returns row-level results plus a
`preview_token` bound to (course, exact CSV text); `import` re-validates and commits all-or-nothing only
with that token. Unknown emails become student accounts with a one-time temporary password (returned once,
must be changed at first sign-in). Every change is audited (`app/audit.py`)."""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..auth.policy import Action, Authz, load_course_for_staff
from ..auth.routes import create_user, temporary_password
from ..db import get_db
from ..errors import ApiError, not_found
from ..models import ACTIVE_STATES, Assignment, Course, CourseStaff, Enrolment, LabSession, Role, User

router = APIRouter(prefix="/api/instructor", tags=["instructor"])
MAX_ROWS = 1000
MAX_CSV_BYTES = 256 * 1024
KNOWN_COLUMNS = {"email", "name"}


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$")
    title: str = Field(min_length=1, max_length=200)
    # Admins only: the course's first instructor (instructors creating a course become its staff themselves).
    instructor_email: str | None = Field(None, max_length=254)


@router.post("/courses", status_code=201)
async def create_course(body: CourseIn, user: User = Depends(Authz(Action.course_manage)),
                        db: AsyncSession = Depends(get_db)):
    code = body.code.strip().upper()
    if await db.scalar(select(Course).where(func.upper(Course.code) == code)):
        raise ApiError("course_exists", f"a course with code {code} already exists", 409)
    first = None
    if body.instructor_email and body.instructor_email.strip():
        if user.role != Role.admin:
            raise ApiError("forbidden", "only admins choose a course's instructor", 403)
        first = await db.scalar(select(User).where(User.email == body.instructor_email.strip().lower()))
        if first is None or first.role != Role.instructor:
            raise ApiError("instructor_not_found", "no instructor account with that email", 404)
    c = Course(code=code, title=body.title.strip(), is_demo=user.is_demo)  # demo reset removes demo-made courses
    db.add(c)
    await db.flush()
    audit.record(db, user, "course.created", course_id=c.id, code=code, title=c.title)
    if user.role == Role.instructor:
        db.add(CourseStaff(course_id=c.id, user_id=user.id))
    elif first is not None:
        db.add(CourseStaff(course_id=c.id, user_id=first.id))
        audit.record(db, user, "course.staff_added", course_id=c.id, subject_user_id=first.id, email=first.email)
    await db.commit()
    return {"id": str(c.id), "code": c.code, "title": c.title}


@router.get("/courses/{course_id}/roster")
async def roster(course_id: uuid.UUID, user: User = Depends(Authz(Action.course_manage)),
                 db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    students = (await db.scalars(select(User).join(Enrolment, Enrolment.user_id == User.id)
                                 .where(Enrolment.course_id == c.id).order_by(User.name))).all()
    staff = (await db.scalars(select(User).join(CourseStaff, CourseStaff.user_id == User.id)
                              .where(CourseStaff.course_id == c.id).order_by(User.name))).all()
    return {"course": {"id": str(c.id), "code": c.code, "title": c.title, "leaderboard": c.leaderboard},
            "students": [{"id": str(u.id), "name": u.name, "email": u.email, "short_id": u.short_id,
                          "active": u.is_active, "pending_first_sign_in": u.must_change_password}
                         for u in students],
            "staff": [{"id": str(u.id), "name": u.name, "email": u.email} for u in staff]}


# ---------------------------------------------------------------------------------------- roster CSV
class RosterIn(BaseModel):
    csv: str = Field(min_length=1)


class RosterImportIn(RosterIn):
    preview_token: str = Field(min_length=64, max_length=64)


@dataclass
class Row:
    row: int  # 1-based line number in the file (header is line 1)
    email: str
    name: str
    status: str = "error"  # create | enrol | already_enrolled | error
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    user_id: uuid.UUID | None = None

    def out(self) -> dict:
        return {"row": self.row, "email": self.email, "name": self.name, "status": self.status,
                "errors": self.errors, "warnings": self.warnings}


def _token(course_id: uuid.UUID, text: str) -> str:
    return hashlib.sha256(f"{course_id}\n{text}".encode()).hexdigest()


def _parse(text: str) -> tuple[list[Row], list[str]]:
    """Returns rows and file-level errors (bad header, too many rows)."""
    if len(text.encode()) > MAX_CSV_BYTES:
        return [], [f"the file is larger than {MAX_CSV_BYTES // 1024} KB"]
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    try:
        header = next(reader)
    except StopIteration:
        return [], ["the file is empty"]
    cols = [h.strip().lower() for h in header]
    if "email" not in cols:
        return [], ["the header row must include an 'email' column (and 'name' for new students)"]
    if len(set(cols)) != len(cols):
        return [], ["the header row repeats a column name"]
    file_errors = []
    unknown = [h for h in cols if h and h not in KNOWN_COLUMNS]
    ie, iname = cols.index("email"), (cols.index("name") if "name" in cols else None)
    rows: list[Row] = []
    for n, rec in enumerate(reader, start=2):
        if not any(x.strip() for x in rec):
            continue  # blank line
        if len(rows) >= MAX_ROWS:
            file_errors.append(f"too many rows (the limit is {MAX_ROWS})")
            break
        get = lambda i: rec[i].strip() if i is not None and i < len(rec) else ""  # noqa: E731
        r = Row(row=n, email=get(ie).lower(), name=get(iname))
        if len(rec) > len(cols):
            r.errors.append(f"has {len(rec)} values but the header has {len(cols)} columns")
        if unknown:
            r.warnings.append(f"ignored column(s): {', '.join(unknown)}")
        rows.append(r)
    return rows, file_errors


async def _validate(db: AsyncSession, course: Course, text: str) -> tuple[list[Row], list[str]]:
    rows, file_errors = _parse(text)
    seen: dict[str, int] = {}
    emails = [r.email for r in rows if r.email]
    users = {u.email: u for u in (await db.scalars(select(User).where(User.email.in_(emails)))).all()} if emails else {}
    enrolled = set((await db.scalars(select(Enrolment.user_id).where(Enrolment.course_id == course.id))).all())
    for r in rows:
        if not r.email:
            r.errors.append("email is missing")
        else:
            try:
                r.email = validate_email(r.email, check_deliverability=False).normalized.lower()
            except EmailNotValidError as e:
                r.errors.append(f"invalid email: {e}")
        if r.email in seen:
            r.errors.append(f"duplicate of row {seen[r.email]}")
        elif r.email:
            seen[r.email] = r.row
        if len(r.name) > 120:
            r.errors.append("name is longer than 120 characters")
        u = users.get(r.email)
        if u is None:
            if not r.name:
                r.errors.append("name is required to create a new student account")
            status = "create"
        else:
            r.user_id = u.id
            if u.role != Role.student:
                r.errors.append(f"{r.email} is a {u.role.value} account, not a student")
            if not u.is_active:
                r.errors.append("this account is deactivated; ask an administrator to reactivate it")
            if r.name and r.name != u.name:
                r.warnings.append(f"existing account keeps its name '{u.name}'")
            status = "already_enrolled" if u.id in enrolled else "enrol"
        r.status = "error" if r.errors else status
    return rows, file_errors


def _summary(rows: list[Row]) -> dict[str, int]:
    out = {"rows": len(rows), "create": 0, "enrol": 0, "already_enrolled": 0, "error": 0}
    for r in rows:
        out[r.status] += 1
    return out


@router.post("/courses/{course_id}/roster/preview")
async def roster_preview(course_id: uuid.UUID, body: RosterIn, user: User = Depends(Authz(Action.course_manage)),
                         db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    rows, file_errors = await _validate(db, c, body.csv)
    ok = not file_errors and bool(rows) and all(r.status != "error" for r in rows)
    if not rows and not file_errors:
        file_errors = ["the file has no student rows"]
    return {"ok": ok, "file_errors": file_errors, "summary": _summary(rows), "rows": [r.out() for r in rows],
            "preview_token": _token(c.id, body.csv) if ok else None}


@router.post("/courses/{course_id}/roster/import")
async def roster_import(course_id: uuid.UUID, body: RosterImportIn, user: User = Depends(Authz(Action.course_manage)),
                        db: AsyncSession = Depends(get_db)):
    c = await load_course_for_staff(db, user, course_id)
    if body.preview_token != _token(c.id, body.csv):
        raise ApiError("preview_required", "preview this exact file before importing it", 409)
    rows, file_errors = await _validate(db, c, body.csv)
    if file_errors or not rows or any(r.status == "error" for r in rows):
        raise ApiError("roster_invalid", "the roster changed since the preview and now has errors; preview it again",
                       422, extra={"file_errors": file_errors, "rows": [r.out() for r in rows if r.status == "error"]})
    credentials, created, enrolled = [], [], []
    for r in rows:
        if r.status == "create":
            pw = temporary_password()
            u = await create_user(db, r.email, r.name, Role.student, pw, must_change_password=True,
                                  is_demo=c.is_demo)
            await db.flush()
            db.add(Enrolment(course_id=c.id, user_id=u.id))
            credentials.append({"email": u.email, "name": u.name, "temporary_password": pw})
            created.append(u.email)
        elif r.status == "enrol":
            db.add(Enrolment(course_id=c.id, user_id=r.user_id))
            enrolled.append(r.email)
    audit.record(db, user, "roster.imported", course_id=c.id, rows=len(rows), created=created, enrolled=enrolled,
                 already_enrolled=sum(r.status == "already_enrolled" for r in rows),
                 csv_sha256=hashlib.sha256(body.csv.encode()).hexdigest())
    await db.commit()
    return {"summary": _summary(rows), "created": len(created), "enrolled": len(enrolled),
            "credentials": credentials}


# --------------------------------------------------------------------------------------- enrolments
class EnrolIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/courses/{course_id}/enrolments", status_code=201)
async def add_enrolment(course_id: uuid.UUID, body: EnrolIn, user: User = Depends(Authz(Action.course_manage)),
                        db: AsyncSession = Depends(get_db)):
    """Enrol one existing student account (new accounts are created through the roster import)."""
    c = await load_course_for_staff(db, user, course_id)
    stu = await db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if stu is None or stu.role != Role.student:
        raise ApiError("student_not_found", "no student account with that email; add new students with a roster CSV", 404)
    if await db.get(Enrolment, (c.id, stu.id)):
        raise ApiError("already_enrolled", f"{stu.email} is already enrolled", 409)
    db.add(Enrolment(course_id=c.id, user_id=stu.id))
    audit.record(db, user, "enrolment.added", course_id=c.id, subject_user_id=stu.id, email=stu.email)
    await db.commit()
    return {"user_id": str(stu.id)}


@router.delete("/courses/{course_id}/enrolments/{user_id}", status_code=204)
async def remove_enrolment(course_id: uuid.UUID, user_id: uuid.UUID, user: User = Depends(Authz(Action.course_manage)),
                           db: AsyncSession = Depends(get_db)):
    """Removes access to the course. Attempts and evidence are kept (append-only)."""
    c = await load_course_for_staff(db, user, course_id)
    e = await db.get(Enrolment, (c.id, user_id))
    if e is None:
        raise not_found("enrolment")
    active = await db.scalar(select(LabSession.id).join(Assignment, Assignment.id == LabSession.assignment_id).where(
        Assignment.course_id == c.id, LabSession.user_id == user_id, LabSession.state.in_(ACTIVE_STATES)).limit(1))
    if active is not None:
        raise ApiError("session_active", "this student has a lab running in this course; end it first", 409,
                       extra={"session_id": str(active)})
    stu = await db.get(User, user_id)
    await db.delete(e)
    audit.record(db, user, "enrolment.removed", course_id=c.id, subject_user_id=user_id,
                 email=stu.email if stu else None)
    await db.commit()
