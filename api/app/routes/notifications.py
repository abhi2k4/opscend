"""In-app notifications and email alert settings."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, update

from app import models, schemas
from app.core.config import get_settings
from app.core.time import utcnow
from app.notifications.email import EmailError, send_email
from app.notifications.service import KINDS

from .deps import SessionDep, get_or_404

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    session: SessionDep,
    limit: int = Query(30, ge=1, le=200),
    unread: bool = False,
) -> schemas.NotificationList:
    query = select(models.Notification).order_by(models.Notification.created_at.desc()).limit(limit)
    if unread:
        query = query.where(models.Notification.read_at.is_(None))
    count = await session.scalar(
        select(func.count())
        .select_from(models.Notification)
        .where(models.Notification.read_at.is_(None))
    )
    return schemas.NotificationList(unread=count or 0, items=(await session.scalars(query)).all())


@router.get("/notifications/settings")
async def notification_settings() -> schemas.NotificationSettings:
    settings = get_settings()
    return schemas.NotificationSettings(
        kinds=list(KINDS),
        email=schemas.EmailSettings(
            configured=settings.email_configured,
            host=(settings.smtp_host or "").strip() or None,
            port=settings.smtp_port,
            security=settings.smtp_security,
            from_address=settings.email_sender,
            to_address=settings.email_recipient,
            events=[kind for kind in KINDS if kind in settings.email_event_set],
        ),
    )


@router.post("/notifications/test-email")
async def test_email() -> schemas.Ok:
    try:
        await send_email(
            "Test email",
            "If you are reading this, Opscend can send you alerts.",
            "/console/notifications",
        )
    except EmailError as exc:
        raise HTTPException(400, str(exc)) from exc
    return schemas.Ok()


@router.post("/notifications/read-all")
async def mark_all_read(session: SessionDep) -> schemas.Ok:
    await session.execute(
        update(models.Notification)
        .where(models.Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    await session.commit()
    return schemas.Ok()


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, session: SessionDep) -> schemas.Notification:
    notification = await get_or_404(session, models.Notification, notification_id)
    if notification.read_at is None:
        notification.read_at = utcnow()
        await session.commit()
    return notification
