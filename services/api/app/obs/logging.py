import logging
import re
from typing import Any

import structlog

from .events import EVENTS

_SECRET_KEYS = re.compile(r"(password|secret|ticket|token|credential|cred|authorization|cookie)", re.I)
_strict = False


def _redact(_: Any, __: str, event_dict: dict) -> dict:
    for k in list(event_dict):
        if k != "event" and _SECRET_KEYS.search(k):
            event_dict[k] = "[redacted]"
    return event_dict


def _enforce_names(_: Any, __: str, event_dict: dict) -> dict:
    name = event_dict.get("event")
    if name not in EVENTS:
        if _strict:
            raise ValueError(f"log event {name!r} is not in the fixed event set (PLAN §14)")
        event_dict["unregistered_event"] = True
    return event_dict


def configure(strict: bool = False, level: int = logging.INFO) -> None:
    global _strict
    _strict = strict
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _enforce_names,
            _redact,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=False,
    )


log = structlog.get_logger("cloudlabs")


def bind(**ids: Any) -> None:
    """Bind correlation IDs (user_id, assignment_id, session_id, sandbox_id, attempt_id, runner_id)."""
    structlog.contextvars.bind_contextvars(**{k: str(v) for k, v in ids.items() if v is not None})
