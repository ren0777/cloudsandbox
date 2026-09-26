"""Tracked background tasks (provisioning, teardown, auto-submit) and periodic loops."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import structlog

_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], name: str | None = None) -> asyncio.Task:
    ctx = structlog.contextvars.get_contextvars()

    async def run() -> Any:
        structlog.contextvars.bind_contextvars(**ctx)
        return await coro

    t = asyncio.create_task(run(), name=name)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def drain(timeout: float = 30.0) -> None:
    """Wait for in-flight background work (tests and graceful shutdown)."""
    if _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)


def pending() -> int:
    return len(_tasks)


def loop(interval_s: float, fn: Callable[[], Awaitable[None]], name: str) -> asyncio.Task:
    async def run() -> None:
        while True:
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let a loop die
                structlog.get_logger("cloudlabs").error("background.task.failed", loop=name, error=repr(e))
            await asyncio.sleep(interval_s)
    t = asyncio.create_task(run(), name=name)
    return t
