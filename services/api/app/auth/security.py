import asyncio
import hashlib
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import get_settings

# argon2id with the OWASP-recommended profile (19 MiB, 2 passes, 1 lane). Hashes made with other parameters
# (e.g. the library defaults used before phase 7) still verify and are upgraded at the next sign-in.
_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
ACCESS_COOKIE = "cl_access"
REFRESH_COOKIE = "cl_refresh"
CSRF_COOKIE = "cl_csrf"
CSRF_HEADER = "X-CSRF-Token"


# argon2id is deliberately expensive (~64 MiB and tens of ms per call). Run it in worker threads (argon2 releases
# the GIL) so a class signing in at once never blocks the event loop, and bound the parallelism so a burst can't
# exhaust memory. Found by the phase 7 load test (32 simultaneous sign-ins stalled every other request).
PASSWORD_WORKERS = max(1, (os.cpu_count() or 2) - 2)  # leave cores for the event loop
_slots: dict[int, asyncio.Semaphore] = {}


def _slot() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    return _slots.setdefault(id(loop), asyncio.Semaphore(PASSWORD_WORKERS))


def _verify(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def hash_password(pw: str) -> str:
    async with _slot():
        return await asyncio.to_thread(_ph.hash, pw)


async def verify_password(pw: str, hashed: str) -> bool:
    async with _slot():
        return await asyncio.to_thread(_verify, pw, hashed)


def needs_rehash(hashed: str) -> bool:
    try:
        return _ph.check_needs_rehash(hashed)
    except InvalidHashError:
        return False


_DUMMY_HASH = _ph.hash("timing-equaliser")


async def burn_password_check(pw: str) -> None:
    """Spend the same time as a real verify when the user doesn't exist."""
    await verify_password(pw, _DUMMY_HASH)


def sha256_hex(s: str | bytes) -> str:
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def make_access_token(user_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "role": role, "typ": "access", "iat": now,
                       "exp": now + timedelta(minutes=s.access_token_minutes)},
                      s.secret_key, algorithm="HS256")


class TokenExpired(Exception):
    pass


class TokenInvalid(Exception):
    pass


def decode_access_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"],
                            options={"require": ["exp", "sub", "typ"]})
    except jwt.ExpiredSignatureError as e:
        raise TokenExpired() from e
    except jwt.PyJWTError as e:
        raise TokenInvalid() from e
    if claims.get("typ") != "access":
        raise TokenInvalid()
    return claims


class RateLimiter:
    """In-process sliding window. Slice 1 runs one API process; Redis replaces this later."""

    def __init__(self) -> None:
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


login_limiter = RateLimiter()
