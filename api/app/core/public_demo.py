"""Rules of the public demo (`OPSCEND_PUBLIC_DEMO=1`).

Anyone on the internet can open it, so: no real provider is ever contacted, every
visitor works in a private copy of the sample data (`demo/sandbox.py`), and the things
a visitor can do are paced.
"""

import time
import uuid

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import use_sandbox

VISITOR_COOKIE = "opscend_visitor"
SELF_HOST_HINT = (
    "This is the public demo, so that is turned off here. Run Opscend on your own machine "
    "to try it for real: git clone, cp .env.example .env, docker compose up."
)


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
NO_SANDBOX = (
    "Your private copy of the demo is not ready yet. The demo needs cookies: "
    "reload the page and try again."
)


def forbid_in_public_demo() -> None:
    """Dependency for routes that reach a real provider or take free-form input."""
    if get_settings().public_demo:
        raise HTTPException(403, SELF_HOST_HINT)


def visitor_id(request: Request) -> str | None:
    """A stable id per browser in the public demo; None everywhere else."""
    return getattr(request.state, "visitor", None)


async def tag_visitor(request: Request, call_next):  # noqa: ANN001, ANN201
    """Middleware: give each browser of the public demo an id cookie and its own data.

    A browser that already has the cookie works in its private sandbox. One without it
    (the very first requests, or a client that keeps no cookies) reads the shared sample
    data and cannot change anything, so parallel first requests never build sandboxes.
    """
    settings = get_settings()
    if not settings.public_demo:
        return await call_next(request)
    from app.demo import sandbox  # imported late: it needs the models

    known = request.cookies.get(VISITOR_COOKIE, "")
    returning = _valid(known)
    visitor = known if returning else str(uuid.uuid4())
    request.state.visitor = visitor
    # A client that sends no cookie gets a new id every time, so it is paced by address.
    request.state.visitor_is_new = not returning
    name = await sandbox.enter(visitor) if returning else None
    response: Response
    if name is None and request.method not in SAFE_METHODS:
        response = JSONResponse({"detail": NO_SANDBOX}, status_code=409)
    else:
        with use_sandbox(name):
            response = await call_next(request)
    if not returning:
        response.set_cookie(
            VISITOR_COOKIE,
            visitor,
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
        )
    return response


def _valid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


_last: dict[tuple[str, str], float] = {}
_MAX_KEYS = 20_000


def pace(request: Request, action: str, seconds: float, *, shared: bool = False) -> None:
    """In the public demo, allow `action` once per `seconds` per visitor (or for everyone).

    Kept in this process's memory: it only has to stop a script from hammering the
    demo, not be exact across restarts or replicas.
    """
    if not get_settings().public_demo:
        return
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    address = forwarded or (request.client.host if request.client else "?")
    who = [visitor_id(request) or address]
    if getattr(request.state, "visitor_is_new", True):
        who.append(address)  # no cookie yet (or a client that never keeps one)
    keys = [(action, "*")] if shared else [(action, one) for one in who]
    now = time.monotonic()
    wait = max(seconds - (now - _last.get(key, -1e9)) for key in keys)
    if wait > 0:
        raise HTTPException(429, f"Slow down a little: try again in {max(1, round(wait))}s.")
    if len(_last) > _MAX_KEYS:
        _last.clear()
    for key in keys:
        _last[key] = now


def paced(action: str, seconds: float, *, shared: bool = False):  # noqa: ANN201
    """`pace` as a route dependency."""

    def dependency(request: Request) -> None:
        pace(request, action, seconds, shared=shared)

    return dependency
