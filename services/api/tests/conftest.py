from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import timedelta

os.environ.setdefault("CL_ENV", "test")
os.environ.setdefault("CL_COOKIE_SECURE", "false")
os.environ.setdefault("CL_BACKGROUND_LOOPS", "false")
os.environ.setdefault("CL_ALLOWED_ORIGINS", '["http://testserver", "http://localhost:3000"]')

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.auth.routes import create_user  # noqa: E402
from app.auth.security import CSRF_COOKIE, CSRF_HEADER, login_limiter  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import sessionmaker  # noqa: E402
from app.labs.importer import import_package  # noqa: E402
from app.labs.package import load_pack  # noqa: E402
from app.main import app  # noqa: E402
from app.maintenance import wipe_all  # noqa: E402
from app.models import Assignment, Course, CourseStaff, Enrolment, LabVersion, Role, Runner, User  # noqa: E402
from app.obs import logging as obslog  # noqa: E402
from app.runtime import emulators  # noqa: E402
from app.runtime.runner_client import HttpRunnerClient, set_runner  # noqa: E402
from app.sessions import service  # noqa: E402
from app.sessions import state as st  # noqa: E402
from app.tasks import background  # noqa: E402
from tests.fakes import FakeRunner  # noqa: E402

LABS = get_settings().labs_dir
PASSWORD = "correct-horse-battery"

obslog.configure(strict=True)  # any log event outside the fixed set (PLAN §14) fails the test


@dataclass
class World:
    admin: User
    instructor: User
    other_instructor: User
    alice: User
    bob: User
    course: Course
    other_course: Course
    lab_version: LabVersion
    assignment: Assignment


async def seed_runner_row(healthy: bool = True, max_sandboxes: int = 4) -> None:
    async with sessionmaker()() as db:
        r = await db.get(Runner, get_settings().runner_id)
        if r is None:
            r = Runner(id=get_settings().runner_id, url="http://runner:7070", max_sandboxes=max_sandboxes)
            db.add(r)
        r.status = "healthy" if healthy else "unhealthy"
        r.max_sandboxes = max_sandboxes
        r.last_heartbeat = st.now()
        r.engines = {e: True for e in emulators.ALL_ENGINES}  # the scheduler needs engine-compatible runners
        await db.commit()


@pytest.fixture
async def fake_runner():
    fr = FakeRunner()
    set_runner(fr)
    yield fr
    await background.drain(30)
    fr.shutdown()
    set_runner(None)


@pytest.fixture
async def real_runner():
    s = get_settings()
    rc = HttpRunnerClient(s.runner_id, s.runner_url, s.runner_secret, s.runner_timeout_s)
    set_runner(rc)
    yield rc
    await background.drain(60)
    for sb in await rc.list_sandboxes(env=s.env):
        await rc.destroy_sandbox(sb["sandbox_id"])
    await rc.aclose()
    set_runner(None)


@pytest.fixture(autouse=True)
async def clean_db():
    await wipe_all()
    login_limiter.reset()
    service._last_progress.clear()
    service._inventory.clear()
    service._last_touch.clear()
    await seed_runner_row()
    yield
    await background.drain(30)


async def make_world(lab_path: str = f"{LABS}/s3-basics", max_attempts: int = 3) -> World:
    async with sessionmaker()() as db:
        admin = await create_user(db, "admin@x.edu", "Ada Admin", Role.admin, PASSWORD)
        inst = await create_user(db, "inst@x.edu", "Ian Instructor", Role.instructor, PASSWORD)
        inst2 = await create_user(db, "inst2@x.edu", "Olga Other", Role.instructor, PASSWORD)
        alice = await create_user(db, "alice@x.edu", "Alice", Role.student, PASSWORD, short_id="alice1")
        bob = await create_user(db, "bob@x.edu", "Bob", Role.student, PASSWORD, short_id="bob222")
        course = Course(code="CS101", title="Cloud 101")
        other = Course(code="CS999", title="Other course")
        db.add_all([course, other])
        await db.flush()
        db.add_all([CourseStaff(course_id=course.id, user_id=inst.id),
                    CourseStaff(course_id=other.id, user_id=inst2.id),
                    Enrolment(course_id=course.id, user_id=alice.id),
                    Enrolment(course_id=course.id, user_id=bob.id)])
        lv, _ = await import_package(db, load_pack(lab_path))
        now = st.now()
        a = Assignment(course_id=course.id, lab_version_id=lv.id, title="S3 basics",
                       open_at=now - timedelta(hours=1), due_at=now + timedelta(days=1),
                       close_at=now + timedelta(days=2), max_attempts=max_attempts)
        db.add(a)
        await db.commit()
        return World(admin, inst, inst2, alice, bob, course, other, lv, a)


@pytest.fixture
async def world() -> World:
    return await make_world()


class Client(httpx.AsyncClient):
    """Logged-in test client that sends the CSRF header automatically."""

    async def request(self, method, url, **kw):  # type: ignore[override]
        csrf = self.cookies.get(CSRF_COOKIE)
        if csrf and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            headers = dict(kw.pop("headers", None) or {})
            headers.setdefault(CSRF_HEADER, csrf)
            kw["headers"] = headers
        return await super().request(method, url, **kw)


def client() -> Client:
    return Client(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def login(user: User | str, password: str = PASSWORD) -> Client:
    c = client()
    email = user if isinstance(user, str) else user.email
    r = await c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


async def wait_state(c: httpx.AsyncClient, session_id: str, states: set[str], timeout: float = 60) -> dict:
    import asyncio
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = await c.get(f"/api/sessions/{session_id}")
        assert r.status_code == 200, r.text
        if r.json()["state"] in states:
            return r.json()
        await asyncio.sleep(0.2)
    raise AssertionError(f"session {session_id} did not reach {states}; last={r.json()['state']}")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def all_sessions():
    from app.models import LabSession
    async with sessionmaker()() as db:
        return (await db.scalars(select(LabSession))).all()
