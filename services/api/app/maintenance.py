"""Owner-role maintenance helpers (test isolation and DEMO reset). Append-only protections are
bypassed ONLY here, explicitly, with the owner role — never by request handlers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from .config import get_settings
from .models import APPEND_ONLY_TABLES

ALL_TABLES = ("task_results", "grades", "grading_evidence", "attempts", "terminal_tickets",
              "session_events", "idempotency_keys", "lab_sessions", "student_overrides", "assignments",
              "lab_version_bundles", "lab_versions", "labs", "enrolments", "course_staff", "courses",
              "refresh_tokens", "runners", "users", "audit_events", "user_badges")


async def wipe_all() -> None:
    """Delete every row (tests only)."""
    eng = create_async_engine(get_settings().database_owner_url)
    try:
        async with eng.begin() as conn:
            for t in APPEND_ONLY_TABLES:
                await conn.execute(text(f"ALTER TABLE {t} DISABLE TRIGGER USER"))
            await conn.execute(text("TRUNCATE " + ", ".join(ALL_TABLES) + " CASCADE"))
            for t in APPEND_ONLY_TABLES:
                await conn.execute(text(f"ALTER TABLE {t} ENABLE TRIGGER USER"))
    finally:
        await eng.dispose()


async def wipe_demo() -> dict[str, int]:
    """Delete demo users/courses and everything hanging off them (DEMO_MODE only)."""
    if not get_settings().demo_mode:
        raise RuntimeError("demo reset refused: CL_DEMO_MODE is off")
    eng = create_async_engine(get_settings().database_owner_url)
    counts: dict[str, int] = {}
    stmts = [
        ("audit_events", "DELETE FROM audit_events WHERE course_id IN (SELECT id FROM courses WHERE is_demo) "
                         "OR actor_id IN (SELECT id FROM users WHERE is_demo) "
                         "OR subject_user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("user_badges", "DELETE FROM user_badges WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("task_results", "DELETE FROM task_results WHERE attempt_id IN (SELECT a.id FROM attempts a "
                         "JOIN users u ON u.id = a.user_id WHERE u.is_demo)"),
        ("grades", "DELETE FROM grades WHERE attempt_id IN (SELECT a.id FROM attempts a JOIN users u "
                   "ON u.id = a.user_id WHERE u.is_demo)"),
        ("grading_evidence", "DELETE FROM grading_evidence WHERE session_id IN (SELECT s.id FROM "
                             "lab_sessions s JOIN users u ON u.id = s.user_id WHERE u.is_demo)"),
        ("attempts", "DELETE FROM attempts WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("terminal_tickets", "DELETE FROM terminal_tickets WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("session_events", "DELETE FROM session_events WHERE session_id IN (SELECT s.id FROM lab_sessions s "
                           "JOIN users u ON u.id = s.user_id WHERE u.is_demo)"),
        ("idempotency_keys", "DELETE FROM idempotency_keys WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("lab_sessions", "DELETE FROM lab_sessions WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("student_overrides", "DELETE FROM student_overrides WHERE assignment_id IN (SELECT a.id FROM "
                              "assignments a JOIN courses c ON c.id = a.course_id WHERE c.is_demo) "
                              "OR user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("assignments", "DELETE FROM assignments WHERE course_id IN (SELECT id FROM courses WHERE is_demo)"),
        ("enrolments", "DELETE FROM enrolments WHERE course_id IN (SELECT id FROM courses WHERE is_demo) "
                       "OR user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("course_staff", "DELETE FROM course_staff WHERE course_id IN (SELECT id FROM courses WHERE is_demo) "
                         "OR user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("courses", "DELETE FROM courses WHERE is_demo"),
        ("refresh_tokens", "DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE is_demo)"),
        ("users", "DELETE FROM users WHERE is_demo"),
    ]
    try:
        async with eng.begin() as conn:
            for t in APPEND_ONLY_TABLES:
                await conn.execute(text(f"ALTER TABLE {t} DISABLE TRIGGER USER"))
            for name, sql in stmts:
                counts[name] = (await conn.execute(text(sql))).rowcount or 0
            for t in APPEND_ONLY_TABLES:
                await conn.execute(text(f"ALTER TABLE {t} ENABLE TRIGGER USER"))
    finally:
        await eng.dispose()
    return counts
