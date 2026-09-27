"""Shared plumbing for the service-specific console endpoints (PLAN emulator strategy §6):

    Next.js → service endpoint → owner + state checks → EmulatorAdapter → emulator

A console call targets either a student lab session (READY only; a session being submitted answers 409
session_frozen) or an instructor's **preview sandbox** (phase 9, milestone 42), which reuses the same
runner sandbox but is not a session: it creates no assignment, attempt, grade, XP, badge or leaderboard
event. Resource-level checks decide which one a request may touch; the role matrix only gates the route."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import load_session_for
from ..errors import ApiError
from ..models import LabSession, SessionState as S, User
from ..obs.logging import bind
from ..runtime import emulators
from ..sessions import service


@dataclass
class SandboxContext:
    """The emulator a console call acts on: a READY student session, or an instructor's preview sandbox."""
    id: uuid.UUID
    engine: str
    emulator_endpoint: str
    touch: Callable[[], Awaitable[None]]


async def session_context(session_id: uuid.UUID, user: User, db: AsyncSession) -> SandboxContext:
    sess = await load_session_for(db, user, session_id)
    bind(session_id=sess.id, sandbox_id=sess.id)
    if sess.state in (S.SUBMITTING, S.SUBMITTED):
        raise ApiError("session_frozen", "this lab has been submitted and is read-only", 409)
    if sess.state != S.READY or not sess.emulator_endpoint:
        raise ApiError("invalid_state", "the console is available only while the lab is running", 409,
                       extra={"state": sess.state.value})
    return SandboxContext(id=sess.id, engine=sess.engine, emulator_endpoint=sess.emulator_endpoint,
                          touch=lambda: service.touch(sess.id))


async def console_session(session_id: uuid.UUID, user: User, db: AsyncSession) -> SandboxContext:
    """The console target behind a sandbox id: a student's session, or — when no such session exists — an
    instructor's preview sandbox (draft owner or admin only; everyone else gets 404)."""
    if await db.get(LabSession, session_id) is not None:
        return await session_context(session_id, user, db)
    from ..instructor.preview import load_preview_context
    return await load_preview_context(db, user, session_id)


async def sandbox_engine(db: AsyncSession, user: User, sandbox_id: uuid.UUID) -> str:
    """The engine behind a session or preview sandbox, without the READY gate (console service catalogue)."""
    if await db.get(LabSession, sandbox_id) is not None:
        return (await load_session_for(db, user, sandbox_id)).engine
    from ..instructor.preview import load_preview_context
    return (await load_preview_context(db, user, sandbox_id)).engine


def operation_name(fn_name: str) -> str:
    """boto3 method name → AWS operation name (list_objects_v2 → ListObjectsV2)."""
    return "".join(part[:1].upper() + part[1:] for part in fn_name.split("_"))


def require_capability(ctx: SandboxContext, aws_service: str, fn_name: str) -> None:
    """Capability filtering at the boundary: only operations declared supported/simulated for the
    sandbox's engine may reach the emulator."""
    caps = emulators.get(ctx.engine).capabilities
    op = f"{aws_service}:{operation_name(fn_name)}"
    if not caps.is_usable(op):
        entry = caps.services.get(aws_service, {}).get(operation_name(fn_name))
        note = entry.note if entry and entry.note else "This operation isn't available in the Stackora simulator."
        raise ApiError("not_in_simulator", note, 409, extra={"operation": op})


async def aws_call(ctx: SandboxContext, aws_service: str, fn_name: str, **kw: Any) -> dict:
    require_capability(ctx, aws_service, fn_name)

    def run() -> dict:
        client = emulators.get(ctx.engine).client(aws_service, ctx.emulator_endpoint)
        return getattr(client, fn_name)(**kw)
    try:
        out = await asyncio.to_thread(run)
    except ClientError as e:
        err = e.response.get("Error", {})
        raise ApiError("aws_error", err.get("Message") or err.get("Code", "AWS error"), 400,
                       extra={"aws_code": err.get("Code")}) from None
    except EndpointConnectionError:
        raise ApiError("sandbox_unreachable", "your sandbox is not reachable", 503) from None
    await ctx.touch()
    return out
