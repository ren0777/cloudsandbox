"""In-process pub/sub for session state changes (slice 1 runs one API process; Redis pub/sub later).
Used to close terminal WebSockets when a session leaves READY (PLAN §11.4)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable

from ..models import SessionState

Listener = Callable[[SessionState, str], None]
_listeners: defaultdict[uuid.UUID, set[Listener]] = defaultdict(set)


def subscribe(session_id: uuid.UUID, fn: Listener) -> Callable[[], None]:
    _listeners[session_id].add(fn)

    def unsubscribe() -> None:
        _listeners[session_id].discard(fn)
        if not _listeners[session_id]:
            _listeners.pop(session_id, None)
    return unsubscribe


def publish(session_id: uuid.UUID, state: SessionState, reason: str) -> None:
    for fn in list(_listeners.get(session_id, ())):
        try:
            fn(state, reason)
        except Exception:  # pragma: no cover - listeners must not break publishers
            pass


def listener_count(session_id: uuid.UUID) -> int:
    return len(_listeners.get(session_id, ()))
