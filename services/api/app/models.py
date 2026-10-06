"""Data model for slice 1 (PLAN "Data model"). Append-only tables are protected by DB triggers and
grants (see alembic migration 0001)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Role(str, enum.Enum):
    student = "student"
    instructor = "instructor"
    admin = "admin"


class SessionState(str, enum.Enum):
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    RESETTING = "RESETTING"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


ACTIVE_STATES = (SessionState.REQUESTED, SessionState.PROVISIONING, SessionState.READY,
                 SessionState.RESETTING, SessionState.SUBMITTING)
# States in which the sandbox may still hold runner capacity.
CAPACITY_STATES = ACTIVE_STATES + (SessionState.SUBMITTED, SessionState.TERMINATING)
_ACTIVE_SQL = "state IN ('REQUESTED','PROVISIONING','READY','RESETTING','SUBMITTING')"

role_enum = Enum(Role, name="role")
state_enum = Enum(SessionState, name="session_state")


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid()
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[Role] = mapped_column(role_enum, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    short_id: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[uuid.UUID] = _uuid()
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Class leaderboard: off (default) | anonymous (aliases) | named. Set by course staff (audited).
    leaderboard: Mapped[str] = mapped_column(String(12), nullable=False, server_default="off")
    created_at: Mapped[datetime] = _now()


class CourseStaff(Base):
    __tablename__ = "course_staff"
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    __table_args__ = (PrimaryKeyConstraint("course_id", "user_id"),)


class Enrolment(Base):
    __tablename__ = "enrolments"
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    __table_args__ = (PrimaryKeyConstraint("course_id", "user_id"),)


class Lab(Base):
    __tablename__ = "labs"
    id: Mapped[uuid.UUID] = _uuid()
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Lab Builder (phase 8): NULL = built-in mission, visible to all. Otherwise private to its author (and
    # admins) unless shared, in which case every instructor can assign or clone it.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()


class LabDraft(Base):
    """An instructor's editable lab (phase 8). content = {"lab": <schema-v1 dict>, "files": {path: text}}.
    Private files in it are visible only to the owner and admins, like a lab version's private bundle."""
    __tablename__ = "lab_drafts"
    id: Mapped[uuid.UUID] = _uuid()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    base_lab_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_versions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="draft")
    last_validation: Mapped[dict | None] = mapped_column(JSONB)
    last_test: Mapped[dict | None] = mapped_column(JSONB)
    last_preview: Mapped[dict | None] = mapped_column(JSONB)
    tested_sha256: Mapped[str | None] = mapped_column(String(64))
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_versions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('draft', 'testing', 'passed', 'failed', 'published')",
                                      name="ck_lab_drafts_status"),)


class LabVersion(Base):
    """Immutable once imported (trigger)."""
    __tablename__ = "lab_versions"
    id: Mapped[uuid.UUID] = _uuid()
    lab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("labs.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    yaml_text: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capabilities_required: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("lab_id", "version"),)


class LabVersionBundle(Base):
    """public = lab.yaml + public/ (may go to the runner); private = private/ (never leaves tooling)."""
    __tablename__ = "lab_version_bundles"
    id: Mapped[uuid.UUID] = _uuid()
    lab_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_versions.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (UniqueConstraint("lab_version_id", "kind"),)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[uuid.UUID] = _uuid()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), nullable=False, index=True)
    lab_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_versions.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allow_late: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    grade_policy: Mapped[str] = mapped_column(String(10), nullable=False, server_default="best")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()


class StudentOverride(Base):
    """Instructor 'reopen' grants (append-only, audited)."""
    __tablename__ = "student_overrides"
    id: Mapped[uuid.UUID] = _uuid()
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    extra_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    close_at_override: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now()


class Runner(Base):
    __tablename__ = "runners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    max_sandboxes: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="unknown")
    version: Mapped[str | None] = mapped_column(String(40))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 7: multi-runner. secret_enc NULL = the platform's CL_RUNNER_SECRET (the seeded local runner).
    secret_enc: Mapped[str | None] = mapped_column(Text)
    drain: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    engines: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    default_engine: Mapped[str | None] = mapped_column(String(20))
    cpu_count: Mapped[int | None] = mapped_column(Integer)
    mem_total_mib: Mapped[int | None] = mapped_column(Integer)
    mem_available_mib: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(String(300))
    unreachable_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LabSession(Base):
    __tablename__ = "lab_sessions"
    id: Mapped[uuid.UUID] = _uuid()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    lab_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_versions.id"), nullable=False)
    runner_id: Mapped[str] = mapped_column(ForeignKey("runners.id"), nullable=False)
    env: Mapped[str] = mapped_column(String(32), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), nullable=False, server_default="moto")
    state: Mapped[SessionState] = mapped_column(state_enum, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    state_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(64))
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)
    resources: Mapped[dict] = mapped_column(JSONB, nullable=False)
    ttl_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    emulator_endpoint: Mapped[str | None] = mapped_column(String(255))
    terminal_endpoint: Mapped[str | None] = mapped_column(String(255))
    ttyd_cred_enc: Mapped[str | None] = mapped_column(Text)
    image_digest: Mapped[str | None] = mapped_column(String(100))
    terminal_image_digest: Mapped[str | None] = mapped_column(String(100))
    recovery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = _now()
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Latest "Check progress" summary (task pass/fail + score), shown to staff as live progress. Not evidence.
    last_progress: Mapped[dict | None] = mapped_column(JSONB)
    last_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("uq_active_session_per_assignment", "user_id", "assignment_id", unique=True,
              postgresql_where=text(_ACTIVE_SQL)),
        Index("ix_sessions_state", "state"),
    )


class SessionEvent(Base):
    __tablename__ = "session_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_sessions.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(20))
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[uuid.UUID] = _uuid()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_sessions.id"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), index=True)
    lab_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_versions.id"))
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(10), nullable=False)  # submit|idle|ttl|close
    counts: Mapped[bool] = mapped_column(Boolean, nullable=False)
    late: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    grader_version: Mapped[str] = mapped_column(String(20), nullable=False)
    emulator_image_digest: Mapped[str | None] = mapped_column(String(100))
    variables: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("user_id", "assignment_id", "attempt_no"),)


class TaskResult(Base):
    __tablename__ = "task_results"
    id: Mapped[uuid.UUID] = _uuid()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    marks_awarded: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    marks_possible: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False)


class GradingEvidence(Base):
    __tablename__ = "grading_evidence"
    id: Mapped[uuid.UUID] = _uuid()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lab_sessions.id"), index=True)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("attempts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # baseline|final
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = _now()


class Grade(Base):
    """Every score for an attempt: the original (created_by NULL) and each regrade. Newest wins."""
    __tablename__ = "grades"
    id: Mapped[uuid.UUID] = _uuid()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id"), index=True)
    grader_version: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (PrimaryKeyConstraint("user_id", "key"),)


class TerminalTicket(Base):
    __tablename__ = "terminal_tickets"
    ticket_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_sessions.id"), index=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lab_drafts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserBadge(Base):
    """A badge earned from a verified (graded, counted) attempt. Append-only; one row per user and badge."""
    __tablename__ = "user_badges"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    badge_id: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attempts.id"), nullable=False)
    awarded_at: Mapped[datetime] = _now()
    __table_args__ = (PrimaryKeyConstraint("user_id", "badge_id"),)


class AuditEvent(Base):
    """Instructor/admin actions (append-only). No foreign keys: the audit trail must never block, or be
    removed by, changes to the rows it describes."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    course_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()


APPEND_ONLY_TABLES = ("attempts", "task_results", "grading_evidence", "grades", "session_events",
                      "student_overrides", "lab_versions", "lab_version_bundles", "audit_events", "user_badges")
