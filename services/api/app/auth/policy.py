"""Backend authorization (PLAN §9). Every route depends on `Authz(action)` (or is explicitly public);
tests/test_authz_coverage.py enforces that. Resource-level checks live in the `load_*_for` helpers and
answer 404 (not 403) for other people's resources so IDs can't be enumerated."""


import enum
import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import ApiError, not_found
from ..models import Assignment, Attempt, Course, CourseStaff, Enrolment, LabSession, Role, User
from ..obs.logging import log
from .deps import current_user
from .security import CSRF_COOKIE, CSRF_HEADER


class Action(str, enum.Enum):
    me = "me"
    assignment_view = "assignment.view"
    session_start = "session.start"
    session_use = "session.use"  # get/heartbeat/reset/submit/progress/stop/terminal/console
    attempt_view_own = "attempt.view_own"
    results_view = "results.view"
    grade_regrade = "grade.regrade"
    override_grant = "override.grant"
    lab_manage = "lab.manage"  # list/import lab versions, create/update/delete assignments
    course_manage = "course.manage"  # create courses, roster import, enrolments (own courses)
    session_manage = "session.manage"  # live progress, terminate/extend students' sessions (own courses)
    audit_view = "audit.view"
    admin = "admin"


S, I, A = Role.student, Role.instructor, Role.admin
MATRIX: dict[Action, frozenset[Role]] = {
    Action.me: frozenset({S, I, A}),
    Action.assignment_view: frozenset({S, I, A}),
    Action.session_start: frozenset({S}),
    Action.session_use: frozenset({S}),
    Action.attempt_view_own: frozenset({S}),
    Action.results_view: frozenset({I, A}),
    Action.grade_regrade: frozenset({I, A}),
    Action.override_grant: frozenset({I, A}),
    Action.lab_manage: frozenset({I, A}),
    Action.course_manage: frozenset({I, A}),
    Action.session_manage: frozenset({I, A}),
    Action.audit_view: frozenset({I, A}),
    Action.admin: frozenset({A}),
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def check_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or cookie != header:
        raise ApiError("csrf_failed", "missing or invalid CSRF token", 403)


class Authz:
    """Route dependency: authenticates, checks CSRF on mutations, and checks the role matrix."""

    def __init__(self, action: Action):
        self.action = action

    async def __call__(self, request: Request, user: User = Depends(current_user)) -> User:
        check_csrf(request)
        if user.must_change_password and self.action != Action.me:
            raise ApiError("password_change_required", "choose a new password before continuing", 403)
        if user.role not in MATRIX[self.action]:
            log.warning("authz.denied", user_id=str(user.id), action=self.action.value,
                        role=user.role.value)
            raise ApiError("forbidden", "you are not allowed to do this", 403)
        return user


# ---------------------------------------------------------------------------- resource-level checks
async def is_course_staff(db: AsyncSession, user: User, course_id: uuid.UUID) -> bool:
    if user.role == Role.admin:
        return True
    if user.role != Role.instructor:
        return False
    return (await db.scalar(select(CourseStaff).where(CourseStaff.course_id == course_id,
                                                      CourseStaff.user_id == user.id))) is not None


async def is_enrolled(db: AsyncSession, user: User, course_id: uuid.UUID) -> bool:
    return (await db.scalar(select(Enrolment).where(Enrolment.course_id == course_id,
                                                    Enrolment.user_id == user.id))) is not None


async def load_assignment_for(db: AsyncSession, user: User, assignment_id: uuid.UUID) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None:
        raise not_found("assignment")
    ok = (await is_enrolled(db, user, a.course_id)) if user.role == Role.student \
        else (await is_course_staff(db, user, a.course_id))
    if not ok:
        log.warning("authz.denied", user_id=str(user.id), assignment_id=str(assignment_id))
        raise not_found("assignment")
    return a


async def load_course_for_staff(db: AsyncSession, user: User, course_id: uuid.UUID) -> Course:
    c = await db.get(Course, course_id)
    if c is None or not await is_course_staff(db, user, course_id):
        if c is not None:
            log.warning("authz.denied", user_id=str(user.id), course_id=str(course_id))
        raise not_found("course")
    return c


async def load_session_for_staff(db: AsyncSession, user: User, session_id: uuid.UUID) -> LabSession:
    """A student's session, for staff of the assignment's course (404 otherwise)."""
    s = await db.get(LabSession, session_id)
    a = await db.get(Assignment, s.assignment_id) if s is not None else None
    if s is None or a is None or not await is_course_staff(db, user, a.course_id):
        if s is not None:
            log.warning("authz.denied", user_id=str(user.id), session_id=str(session_id))
        raise not_found("session")
    return s


async def load_assignment_for_staff(db: AsyncSession, user: User, assignment_id: uuid.UUID) -> Assignment:
    a = await db.get(Assignment, assignment_id)
    if a is None or not await is_course_staff(db, user, a.course_id):
        if a is not None:
            log.warning("authz.denied", user_id=str(user.id), assignment_id=str(assignment_id))
        raise not_found("assignment")
    return a


async def load_session_for(db: AsyncSession, user: User, session_id: uuid.UUID,
                           for_update: bool = False) -> LabSession:
    q = select(LabSession).where(LabSession.id == session_id)
    if for_update:
        q = q.with_for_update()
    s = await db.scalar(q)
    if s is None or s.user_id != user.id:
        if s is not None:
            log.warning("authz.denied", user_id=str(user.id), session_id=str(session_id))
        raise not_found("session")
    return s


async def load_own_attempt(db: AsyncSession, user: User, attempt_id: uuid.UUID) -> Attempt:
    a = await db.get(Attempt, attempt_id)
    if a is None or a.user_id != user.id:
        raise not_found("attempt")
    return a


async def load_attempt_for_staff(db: AsyncSession, user: User, attempt_id: uuid.UUID) -> Attempt:
    a = await db.get(Attempt, attempt_id)
    if a is None:
        raise not_found("attempt")
    asg = await db.get(Assignment, a.assignment_id)
    if asg is None or not await is_course_staff(db, user, asg.course_id):
        log.warning("authz.denied", user_id=str(user.id), attempt_id=str(attempt_id))
        raise not_found("attempt")
    return a


DB = Depends(get_db)
