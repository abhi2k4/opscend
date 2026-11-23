"""Public endpoints: liveness, system info and login."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app import __version__, models, schemas
from app.core.config import get_settings
from app.core.public_demo import forbid_in_public_demo
from app.core.security import (
    SESSION_COOKIE,
    create_session_token,
    current_user,
    verify_password,
)

from .deps import SessionDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> schemas.Ok:
    return schemas.Ok()


@router.get("/system")
async def system() -> schemas.SystemInfo:
    settings = get_settings()
    return schemas.SystemInfo(
        version=__version__,
        demo_mode=settings.demo,
        public_demo=settings.public_demo,
        ai=schemas.AIInfo(
            provider="demo" if settings.ai_simulated else settings.ai_provider,
            model=settings.ai_model_name,
            configured=settings.ai_configured,
            simulated=settings.ai_simulated,
            self_hosted=settings.ai_self_hosted and not settings.ai_simulated,
        ),
        queue=settings.queue_kind,
        database=settings.database_kind,
    )


@router.post("/auth/login")
async def login(
    body: schemas.LoginRequest, response: Response, session: SessionDep
) -> schemas.User:
    forbid_in_public_demo()  # nobody signs in there; everyone is already a guest
    user = await session.scalar(
        select(models.User).where(models.User.email == body.email.strip().lower())
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user.id),
        max_age=settings.session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return schemas.User.model_validate(user)


@router.get("/auth/me")
async def me(user: models.User = Depends(current_user)) -> schemas.User:
    return schemas.User.model_validate(user)


@router.post("/auth/logout")
async def logout(response: Response) -> schemas.Ok:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return schemas.Ok()
