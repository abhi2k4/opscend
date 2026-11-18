"""Create notifications. Callers add them inside their own transaction."""

from typing import get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Incident, Integration, Investigation, Notification
from app.schemas import NotificationKind

KINDS: tuple[str, ...] = get_args(NotificationKind)


def notify(
    session: AsyncSession,
    kind: str,
    title: str,
    *,
    severity: str = "info",
    body: str | None = None,
    link: str | None = None,
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
    )
    session.add(notification)
    return notification


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


def integration_error(session: AsyncSession, integration: Integration, detail: str) -> None:
    notify(
        session,
        "integration_error",
        f"{integration.provider.capitalize()} integration stopped syncing",
        severity="warning",
        body=detail,
        link="/console/integrations",
    )
