"""Idempotency-Key handling for Reset and Submit (PLAN §2).

- Same key + same endpoint/body  -> the stored response is replayed.
- Same key + different body      -> 422 idempotency_key_reused.
- Same key while the first call is still running -> 409 idempotency_in_progress.
- 5xx outcomes are not stored, so the client may retry with the same key.
Keys expire after 24h (janitor)."""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .db import sessionmaker
from .errors import ApiError, error_body
from .models import IdempotencyKey

KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
TTL = timedelta(hours=24)


def request_hash(endpoint: str, body: Any) -> str:
    import json
    return hashlib.sha256(f"{endpoint}|{json.dumps(body, sort_keys=True, default=str)}".encode()).hexdigest()


async def run_idempotent(user_id: uuid.UUID, key: str | None, endpoint: str, body: Any,
                         handler: Callable[[], Awaitable[tuple[int, Any]]]) -> JSONResponse:
    if not key or not KEY_RE.match(key):
        raise ApiError("idempotency_key_required", "Idempotency-Key header (UUID) is required", 400)
    h = request_hash(endpoint, body)
    sm = sessionmaker()
    async with sm() as db:
        inserted = (await db.execute(
            insert(IdempotencyKey).values(user_id=user_id, key=key, endpoint=endpoint, request_hash=h)
            .on_conflict_do_nothing().returning(IdempotencyKey.key))).first()
        await db.commit()
        if inserted is None:
            row = await db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == user_id,
                                                               IdempotencyKey.key == key))
            if row is None:  # expired and deleted in between; treat as conflict
                raise ApiError("idempotency_in_progress", "retry shortly", 409)
            if row.endpoint != endpoint or row.request_hash != h:
                raise ApiError("idempotency_key_reused", "this Idempotency-Key was used for another request",
                               422)
            if row.status_code is None:
                raise ApiError("idempotency_in_progress", "the original request is still running", 409)
            return JSONResponse(row.response_body, row.status_code, headers={"Idempotent-Replay": "true"})
    try:
        status, payload = await handler()
        body_out = jsonable_encoder(payload)
    except ApiError as e:
        if e.status >= 500:
            await _forget(user_id, key)
            raise
        status, body_out = e.status, error_body(e.code, e.message, **e.extra)
    except Exception:
        await _forget(user_id, key)
        raise
    async with sm() as db:
        await db.execute(update(IdempotencyKey).where(IdempotencyKey.user_id == user_id,
                                                      IdempotencyKey.key == key)
                         .values(status_code=status, response_body=body_out))
        await db.commit()
    return JSONResponse(body_out, status)


async def _forget(user_id: uuid.UUID, key: str) -> None:
    async with sessionmaker()() as db:
        await db.execute(delete(IdempotencyKey).where(IdempotencyKey.user_id == user_id,
                                                      IdempotencyKey.key == key))
        await db.commit()


async def purge_expired(db: AsyncSession) -> int:
    from .sessions.state import now
    res = await db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < now() - TTL))
    return res.rowcount or 0
