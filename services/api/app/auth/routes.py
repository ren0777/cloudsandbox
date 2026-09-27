from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..errors import ApiError
from ..models import RefreshToken, Role, User
from .policy import Action, Authz, check_csrf
from .security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    burn_password_check,
    hash_password,
    login_limiter,
    needs_rehash,
    make_access_token,
    new_token,
    sha256_hex,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_ALPHABET = string.ascii_lowercase + string.digits


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    short_id: str
    must_change_password: bool = False


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, short_id=u.short_id,
                   must_change_password=u.must_change_password)


def temporary_password() -> str:
    """Readable one-time password for roster-created accounts (must be changed at first sign-in)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


async def create_user(db: AsyncSession, email: str, name: str, role: Role, password: str,
                      short_id: str | None = None, is_demo: bool = False,
                      must_change_password: bool = False) -> User:
    pw_hash = await hash_password(password)
    for _ in range(10):
        sid = short_id or "".join(secrets.choice(_ALPHABET) for _ in range(6))
        u = User(email=email.lower(), name=name, role=role, password_hash=pw_hash,
                 short_id=sid, is_demo=is_demo, must_change_password=must_change_password)
        try:
            async with db.begin_nested():
                db.add(u)
            return u
        except IntegrityError as e:
            if "short_id" not in str(e) or short_id:
                raise
    raise RuntimeError("could not allocate short_id")


def _set_auth_cookies(resp: Response, user: User, refresh: str) -> None:
    s = get_settings()
    resp.set_cookie(ACCESS_COOKIE, make_access_token(user.id, user.role.value), httponly=True,
                    secure=s.cookie_secure, samesite="lax", path="/",
                    max_age=s.access_token_minutes * 60)
    resp.set_cookie(REFRESH_COOKIE, refresh, httponly=True, secure=s.cookie_secure, samesite="lax",
                    path="/api/auth", max_age=s.refresh_token_days * 86400)
    resp.set_cookie(CSRF_COOKIE, new_token(), httponly=False, secure=s.cookie_secure, samesite="lax",
                    path="/", max_age=s.refresh_token_days * 86400)


def _clear_auth_cookies(resp: Response) -> None:
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        resp.delete_cookie(name, path=path)


async def _issue_refresh(db: AsyncSession, user: User, family: uuid.UUID | None = None) -> str:
    raw = new_token()
    db.add(RefreshToken(user_id=user.id, family_id=family or uuid.uuid4(), token_hash=sha256_hex(raw),
                        expires_at=datetime.now(timezone.utc)
                        + timedelta(days=get_settings().refresh_token_days)))
    return raw


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "?"
    if not login_limiter.allow(f"{ip}|{body.email.lower()}", get_settings().login_rate_per_minute):
        raise ApiError("rate_limited", "too many sign-in attempts, wait a minute", 429,
                       headers={"Retry-After": "60"})
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        await burn_password_check(body.password)
        raise ApiError("invalid_credentials", "email or password is incorrect", 401)
    if not await verify_password(body.password, user.password_hash) or not user.is_active:
        raise ApiError("invalid_credentials", "email or password is incorrect", 401)
    if needs_rehash(user.password_hash):  # upgrade hashes made with older argon2 parameters
        user.password_hash = await hash_password(body.password)
    if user.is_demo and not get_settings().demo_mode:
        raise ApiError("invalid_credentials", "demo accounts are disabled", 401)
    refresh = await _issue_refresh(db, user)
    await db.commit()
    _set_auth_cookies(response, user, refresh)
    return user_out(user)


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    check_csrf(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError("unauthenticated", "sign in required", 401)
    now = datetime.now(timezone.utc)
    tok = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw))
                          .with_for_update())
    if tok is None or tok.revoked_at is not None or tok.expires_at < now:
        raise ApiError("unauthenticated", "sign in required", 401)
    if tok.used_at is not None:  # reuse of a rotated token: revoke the whole family
        await db.execute(update(RefreshToken).where(RefreshToken.family_id == tok.family_id)
                         .values(revoked_at=now))
        await db.commit()
        _clear_auth_cookies(response)
        raise ApiError("unauthenticated", "sign in required", 401)
    user = await db.get(User, tok.user_id)
    if user is None or not user.is_active:
        raise ApiError("unauthenticated", "sign in required", 401)
    tok.used_at = now
    new_raw = await _issue_refresh(db, user, tok.family_id)
    await db.commit()
    _set_auth_cookies(response, user, new_raw)
    return user_out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        check_csrf(request)
        tok = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
        if tok is not None:
            await db.execute(update(RefreshToken).where(RefreshToken.family_id == tok.family_id)
                             .values(revoked_at=datetime.now(timezone.utc)))
            await db.commit()
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, response: Response, db: AsyncSession = Depends(get_db)):
    if not get_settings().allow_self_register:
        raise ApiError("registration_disabled", "self-registration is disabled", 403)
    if await db.scalar(select(User).where(User.email == body.email.lower())):
        raise ApiError("email_taken", "an account with this email already exists", 409)
    user = await create_user(db, body.email, body.name, Role.student, body.password)
    refresh = await _issue_refresh(db, user)
    await db.commit()
    _set_auth_cookies(response, user, refresh)
    return user_out(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(Authz(Action.me))):
    return user_out(user)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


@router.post("/change-password", response_model=UserOut)
async def change_password(body: ChangePasswordIn, user: User = Depends(Authz(Action.me)),
                          db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user.id)
    assert u is not None
    if not await verify_password(body.current_password, u.password_hash):
        raise ApiError("invalid_credentials", "your current password is incorrect", 400)
    if body.new_password == body.current_password:
        raise ApiError("validation_error", "choose a password different from the current one", 400)
    u.password_hash = await hash_password(body.new_password)
    u.must_change_password = False
    await db.commit()
    return user_out(u)


@router.get("/demo-accounts")
async def demo_accounts(db: AsyncSession = Depends(get_db)):
    """Demo Mode only (PLAN §16): the seeded demo accounts and their shared password, so the login page can
    offer one-click sign-in. Empty when CL_DEMO_MODE is off or the demo reset has not run, so a real
    deployment never advertises accounts and a fresh stack shows no dead buttons."""
    if not get_settings().demo_mode:
        return {"enabled": False, "password": None, "accounts": []}
    from ..demo import DEMO_DOMAIN, DEMO_PASSWORD, DEMO_USERS
    emails = [f"{short}@{DEMO_DOMAIN}" for short, _name, _role, _sid in DEMO_USERS]
    found = {u.email: u for u in (await db.scalars(select(User).where(User.email.in_(emails)))).all()}
    accounts = [{"email": e, "name": found[e].name, "role": found[e].role.value} for e in emails if e in found]
    return {"enabled": bool(accounts), "password": DEMO_PASSWORD if accounts else None, "accounts": accounts}


PUBLIC_ROUTES = {("POST", "/api/auth/login"), ("POST", "/api/auth/refresh"),
                 ("POST", "/api/auth/logout"), ("POST", "/api/auth/register"),
                 ("GET", "/api/auth/demo-accounts")}
