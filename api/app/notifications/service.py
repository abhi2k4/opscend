"""Create notifications. Callers add them inside their own transaction."""

from datetime import timedelta
from typing import get_args

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import Incident, Integration, Investigation, Notification
from app.schemas import NotificationKind

KINDS: tuple[str, ...] = get_args(NotificationKind)
REPEAT_COOLDOWN = timedelta(hours=6)
# Failed syncs in a row before an integration error is worth interrupting someone for.
SYNC_FAILURES_TO_ALERT = 3


def notify(
    session: AsyncSession,
    kind: str,
    title: str,
    *,
    severity: str = "info",
    body: str | None = None,
    link: str | None = None,
    dedup_key: str | None = None,
) -> Notification:
    """Queue a notification on the session; it becomes real when the caller commits."""
    settings = get_settings()
    emailed = settings.email_configured and kind in settings.email_event_set
    notification = Notification(
        kind=kind,
        severity=severity,
        title=title[:512],
        body=body,
        link=link,
        email_status="pending" if emailed else "skipped",
        dedup_key=dedup_key,
    )
    session.add(notification)
    return notification


async def notify_once(
    session: AsyncSession,
    dedup_key: str,
    kind: str,
    title: str,
    *,
    cooldown: timedelta = REPEAT_COOLDOWN,
    **fields: str | None,
) -> Notification | None:
    """Like `notify`, but silent while the same problem is already on the operator's plate.

    Skipped when a notification with this key is still unread, or was raised within
    `cooldown`. A recurring problem therefore shows once, not once per occurrence.
    """
    existing = await session.scalar(
        select(Notification.id)
        .where(
            Notification.dedup_key == dedup_key,
            or_(Notification.read_at.is_(None), Notification.created_at > utcnow() - cooldown),
        )
        .limit(1)
    )
    if existing is not None:
        return None
    return notify(session, kind, title, dedup_key=dedup_key, **fields)


def _incident_link(incident: Incident) -> str:
    if incident.deployment_id:
        return f"/console/deployments/{incident.deployment_id}"
    return "/console/incidents"


def incident_opened(session: AsyncSession, incident: Incident) -> None:
    cause = "A deploy failed." if incident.trigger == "deploy_failed" else "Health checks failed."
    notify(
        session,
        "incident_opened",
        incident.title,
        severity="critical",
        body=f"{cause} An incident is open on {incident.service.name}.",
        link=_incident_link(incident),
    )


def incident_resolved(session: AsyncSession, incident: Incident) -> None:
    notify(
        session,
        "incident_resolved",
        f"Resolved: {incident.title}",
        severity="success",
        body=f"{incident.service.name} recovered.",
        link=_incident_link(incident),
    )


def investigation_finished(session: AsyncSession, investigation: Investigation) -> None:
    service = investigation.service_name or "a deploy"
    link = f"/console/investigations/{investigation.id}"
    report = investigation.report
    if investigation.status != "completed" or not report:
        notify(
            session,
            "investigation_failed",
            f"Investigation failed on {service}",
            severity="warning",
            body=investigation.error,
            link=link,
        )
        return
    if report.get("inconclusive"):
        title = f"Investigation inconclusive on {service}"
    else:
        title = f"Cause found on {service} ({report.get('confidence', 'low')} confidence)"
    notify(
        session,
        "investigation_completed",
        title,
        severity="info",
        body=report.get("likely_cause"),
        link=link,
    )


async def integration_error(session: AsyncSession, integration: Integration, detail: str) -> None:
    await notify_once(
        session,
        f"integration_error:{integration.id}",
        "integration_error",
        f"{integration.provider.capitalize()} integration stopped syncing",
        severity="warning",
        body=detail,
        link="/console/integrations",
    )
