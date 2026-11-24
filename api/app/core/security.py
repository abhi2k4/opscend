"""Password hashing, session JWTs and the `current_user` dependency."""

import asyncio
from datetime import timedelta
from functools import lru_cache

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import signing_key
from app.core.db import get_session
from app.core.time import utcnow
from app.models import User

SESSION_COOKIE = "opscend_session"
_ALGORITHM = "HS256"
GUEST_ID = "guest"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password("no account has this password")


async def check_login(user: User | None, password: str) -> bool:
    """Check a sign-in attempt without blocking the server or revealing who has an account.

    bcrypt is slow on purpose (about 0.2 s), so it runs in a thread: on the event loop a
    burst of attempts would stall every other request. An unknown email is checked
    against a dummy hash, so it takes as long as a wrong password.
    """
    password_hash = user.password_hash if user is not None else _dummy_hash()
    valid = await asyncio.to_thread(verify_password, password, password_hash)
    return valid and user is not None


def create_session_token(user_id: str) -> str:
    now = utcnow()
    claims = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=get_settings().session_hours),
    }
    return jwt.encode(claims, signing_key(), algorithm=_ALGORITHM)


def read_session_token(token: str) -> str | None:
    """Return the user id for a valid token, else None."""
    try:
        return jwt.decode(token, signing_key(), algorithms=[_ALGORITHM]).get("sub")
    except jwt.PyJWTError:
        return None


async def current_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    if get_settings().public_demo:
        # The public demo has no login: every visitor is the same guest, including one
        # whose browser still holds a session cookie from before the site became a demo.
        # (A visitor's private copy of the data has no accounts in it to look up.)
        return User(id=GUEST_ID, email="demo visitor", password_hash="")
    token = request.cookies.get(SESSION_COOKIE)
    user_id = read_session_token(token) if token else None
    user = await session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
