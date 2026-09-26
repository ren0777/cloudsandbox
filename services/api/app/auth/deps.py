import uuid

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..errors import ApiError
from ..models import User
from ..obs.logging import bind
from .security import ACCESS_COOKIE, TokenExpired, TokenInvalid, decode_access_token


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise ApiError("unauthenticated", "sign in required", 401)
    try:
        claims = decode_access_token(token)
    except TokenExpired:
        raise ApiError("token_expired", "session expired, refresh required", 401) from None
    except TokenInvalid:
        raise ApiError("unauthenticated", "invalid credentials", 401) from None
    user = await db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise ApiError("unauthenticated", "invalid credentials", 401)
    bind(user_id=user.id)
    request.state.user = user
    return user
