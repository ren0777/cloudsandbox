"""Browser terminal (PLAN §11).

1. POST /api/sessions/{id}/terminal-ticket — owner, CSRF, READY → single-use 256-bit ticket, 30 s,
   stored hashed.
2. WS /ws/terminal?ticket=… — Origin allowlist, ticket consumed atomically, session must be READY and
   owned by the ticket's user, ≤ N terminals per session.
3. The API connects to ttyd over the sandbox network with the per-session credential (never sent to
   the browser) and relays frames. Browser protocol (JSON text frames):
      → {"t": "i", "d": "<input>"}   → {"t": "r", "c": cols, "r": rows}
      ← binary frames = terminal output
4. Closed with code 1000 and reason submitted|reset|expired|failed|stopped when the session leaves READY.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import uuid
from collections import defaultdict
from datetime import timedelta

import websockets
from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect, WebSocketState

from ..auth.policy import Action, AuthzAny, load_session_for
from ..auth.security import sha256_hex
from ..config import get_settings
from ..crypto import decrypt
from ..db import get_db, sessionmaker
from ..errors import ApiError
from ..models import LabDraft, LabSession, Role, SessionState as S, TerminalTicket, User
from ..obs.logging import bind, log
from ..sessions import bus, service
from ..sessions import state as st

router = APIRouter(tags=["terminal"])
_open: defaultdict[uuid.UUID, int] = defaultdict(int)

REASONS = {S.SUBMITTING: "submitted", S.SUBMITTED: "submitted", S.RESETTING: "reset",
           S.FAILED: "failed", S.TERMINATING: "stopped", S.TERMINATED: "stopped"}


@router.post("/api/sessions/{session_id}/terminal-ticket")
async def issue_ticket(session_id: uuid.UUID,
                       user: User = Depends(AuthzAny(Action.session_use, Action.lab_manage)),
                       db: AsyncSession = Depends(get_db)):
    """A single-use terminal ticket for a student's READY session, or for an instructor's preview sandbox
    (phase 9 M42; the same sandbox, but no session, attempt or grade)."""
    s = get_settings()
    raw = secrets.token_urlsafe(32)  # 256 bits
    expires = st.now() + timedelta(seconds=s.terminal_ticket_ttl_s)
    sess = await db.get(LabSession, session_id)
    if sess is not None:
        sess = await load_session_for(db, user, session_id)
        if sess.state != S.READY:
            raise ApiError("invalid_state", "the terminal is available only while the lab is running", 409,
                           extra={"state": sess.state.value})
        db.add(TerminalTicket(ticket_hash=sha256_hex(raw), session_id=sess.id, user_id=user.id, expires_at=expires))
        key = sess.id
    else:
        from ..instructor.preview import preview_for_terminal
        d = await preview_for_terminal(db, user, session_id)
        db.add(TerminalTicket(ticket_hash=sha256_hex(raw), draft_id=d.id, user_id=user.id, expires_at=expires))
        key = d.id
    await db.commit()
    log.info("terminal.ticket.issued", session_id=str(key), user_id=str(user.id))
    return {"ticket": raw, "expires_in": s.terminal_ticket_ttl_s, "ws_path": "/ws/terminal"}


async def _reject(ws: WebSocket, code: int, reason: str, **kw) -> None:
    """Accept then close with an application code, so the browser learns why (no data is ever sent)."""
    log.warning("terminal.ticket.rejected", reason=reason, **kw)
    await ws.accept()
    await ws.close(code=code, reason=reason)


@router.websocket("/ws/terminal")
async def terminal_ws(ws: WebSocket, ticket: str = ""):
    s = get_settings()
    origin = ws.headers.get("origin")
    if origin not in s.allowed_origins:
        await _reject(ws, 4403, "origin_not_allowed", origin=origin)
        return
    if not ticket:
        await _reject(ws, 4401, "invalid_ticket")
        return
    sess: LabSession | None = None
    draft: LabDraft | None = None
    async with sessionmaker()() as db:
        row = (await db.execute(
            update(TerminalTicket)
            .where(TerminalTicket.ticket_hash == sha256_hex(ticket), TerminalTicket.used_at.is_(None),
                   TerminalTicket.expires_at > st.now())
            .values(used_at=st.now())
            .returning(TerminalTicket.session_id, TerminalTicket.draft_id, TerminalTicket.user_id))).first()
        await db.commit()
        if row is None:
            await _reject(ws, 4401, "invalid_ticket")
            return
        if row.session_id is not None:
            sess = await db.get(LabSession, row.session_id)
        else:
            draft = await db.get(LabDraft, row.draft_id)
            ticket_user = await db.get(User, row.user_id)
    if sess is not None:
        if sess.user_id != row.user_id or sess.state != S.READY:
            await _reject(ws, 4409, "session_not_ready", session_id=str(row.session_id))
            return
        key, endpoint, cred_enc = sess.id, sess.terminal_endpoint, sess.ttyd_cred_enc
        bind(session_id=sess.id, sandbox_id=sess.id, user_id=sess.user_id)
    else:
        lp = (draft.last_preview if draft is not None else None) or {}
        allowed = draft is not None and ticket_user is not None and (
            ticket_user.role == Role.admin or draft.owner_id == ticket_user.id)
        if not allowed or lp.get("status") != "running" or not lp.get("terminal_endpoint"):
            await _reject(ws, 4409, "session_not_ready", sandbox_id=str(row.draft_id))
            return
        key, endpoint, cred_enc = uuid.UUID(lp["sandbox_id"]), lp["terminal_endpoint"], lp.get("ttyd_cred_enc")
        bind(sandbox_id=key, user_id=row.user_id, draft_id=str(draft.id))
    if _open[key] >= s.terminal_max_per_session:
        await _reject(ws, 4429, "too_many_terminals", sandbox_id=str(key))
        return
    cred = decrypt(cred_enc or "")
    auth = base64.b64encode(cred.encode()).decode()
    try:
        upstream = await websockets.connect(
            endpoint or "", subprotocols=["tty"],  # type: ignore[list-item]
            additional_headers={"Authorization": f"Basic {auth}"}, open_timeout=10,
            max_size=s.terminal_max_frame_bytes * 4)
    except Exception as e:
        log.warning("terminal.closed", sandbox_id=str(key), reason="upstream_unavailable", error=repr(e))
        await ws.close(code=1011, reason="terminal_unavailable")
        return
    await ws.accept()
    _open[key] += 1
    closing: dict[str, str] = {}

    def on_state(state: S, _: str) -> None:
        if state != S.READY and not closing:
            closing["reason"] = REASONS.get(state, "closed")
            asyncio.get_running_loop().create_task(upstream.close())

    # A session publishes state changes (submit/reset/stop) and its terminal follows them; a preview has no
    # session state, so its terminal simply ends when the runner replaces or destroys the sandbox.
    unsubscribe = bus.subscribe(sess.id, on_state) if sess is not None else (lambda: None)
    log.info("terminal.connected", sandbox_id=str(key), preview=sess is None)
    await upstream.send(json.dumps({"AuthToken": auth, "columns": 100, "rows": 30}))

    async def touch() -> None:
        if sess is not None:
            await service.touch(sess.id)
        else:
            from ..instructor.preview import _touch
            await _touch(draft.id, str(key))

    async def browser_to_upstream() -> None:
        while True:
            msg = await ws.receive_text()
            if len(msg) > s.terminal_max_frame_bytes:
                closing.setdefault("reason", "frame_too_large")
                return
            try:
                m = json.loads(msg)
            except ValueError:
                continue
            if m.get("t") == "i" and isinstance(m.get("d"), str):
                await upstream.send(b"0" + m["d"].encode())
                await touch()
            elif m.get("t") == "r":
                cols, rows = int(m.get("c", 100)), int(m.get("r", 30))
                if 10 <= cols <= 500 and 5 <= rows <= 200:
                    await upstream.send(b"1" + json.dumps({"columns": cols, "rows": rows}).encode())

    async def upstream_to_browser() -> None:
        async for frame in upstream:
            data = frame if isinstance(frame, bytes) else frame.encode()
            if data[:1] == b"0":
                await ws.send_bytes(data[1:])

    tasks = [asyncio.create_task(browser_to_upstream()), asyncio.create_task(upstream_to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        unsubscribe()
        _open[key] -= 1
        if _open[key] <= 0:
            _open.pop(key, None)
        await upstream.close()
        reason = closing.get("reason", "closed")
        if ws.application_state == WebSocketState.CONNECTED and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close(code=1000, reason=reason)
            except RuntimeError:
                pass
        log.info("terminal.closed", sandbox_id=str(key), reason=reason)


def open_count(session_id: uuid.UUID) -> int:
    return _open.get(session_id, 0)
