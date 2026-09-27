"""Shared plumbing for the service-specific student console endpoints (PLAN emulator strategy §6):

    Next.js → service endpoint → owner + session-state (freeze) checks → EmulatorAdapter → emulator

Only READY sessions accept calls. A session being submitted answers 409 session_frozen (grading freeze)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.policy import load_session_for
from ..errors import ApiError
from ..models import LabSession, SessionState as S, User
from ..obs.logging import bind
from ..runtime import emulators
from ..sessions import service


async def console_session(session_id: uuid.UUID, user: User, db: AsyncSession) -> LabSession:
    sess = await load_session_for(db, user, session_id)
    bind(session_id=sess.id, sandbox_id=sess.id)
    if sess.state in (S.SUBMITTING, S.SUBMITTED):
        raise ApiError("session_frozen", "this lab has been submitted and is read-only", 409)
    if sess.state != S.READY or not sess.emulator_endpoint:
        raise ApiError("invalid_state", "the console is available only while the lab is running", 409,
                       extra={"state": sess.state.value})
    return sess


def operation_name(fn_name: str) -> str:
    """boto3 method name → AWS operation name (list_objects_v2 → ListObjectsV2)."""
    return "".join(part[:1].upper() + part[1:] for part in fn_name.split("_"))


def require_capability(sess: LabSession, aws_service: str, fn_name: str) -> None:
    """Capability filtering at the boundary: only operations declared supported/simulated for the
    session's engine may reach the emulator."""
    caps = emulators.get(sess.engine).capabilities
    op = f"{aws_service}:{operation_name(fn_name)}"
    if not caps.is_usable(op):
        entry = caps.services.get(aws_service, {}).get(operation_name(fn_name))
        note = entry.note if entry and entry.note else "This operation isn't available in the Stackora simulator."
        raise ApiError("not_in_simulator", note, 409, extra={"operation": op})


async def aws_call(sess: LabSession, aws_service: str, fn_name: str, **kw: Any) -> dict:
    require_capability(sess, aws_service, fn_name)

    def run() -> dict:
        client = emulators.get(sess.engine).client(aws_service, sess.emulator_endpoint or "")
        return getattr(client, fn_name)(**kw)
    try:
        out = await asyncio.to_thread(run)
    except ClientError as e:
        err = e.response.get("Error", {})
        raise ApiError("aws_error", err.get("Message") or err.get("Code", "AWS error"), 400,
                       extra={"aws_code": err.get("Code")}) from None
    except EndpointConnectionError:
        raise ApiError("sandbox_unreachable", "your sandbox is not reachable", 503) from None
    await service.touch(sess.id)
    return out
