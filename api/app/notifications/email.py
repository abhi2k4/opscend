"""SMTP delivery for notifications.

Uses the standard library's smtplib in a worker thread: one short-lived connection
per message is plenty at this volume and avoids another dependency.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import session_scope
from app.models import Notification

log = logging.getLogger(__name__)

SMTP_TIMEOUT = 15
MAX_ATTEMPTS = 3
BATCH = 20


class EmailError(Exception):
    """Delivery failed. The message is safe to show: it never holds the SMTP password."""


def build_message(
    settings: Settings, title: str, body: str | None, link: str | None
) -> EmailMessage:
    url = f"{settings.public_url.rstrip('/')}{link}" if link else None
    message = EmailMessage()
    message["Subject"] = f"[Opscend] {title}"
    message["From"] = settings.email_sender
    message["To"] = settings.email_recipient
    text = "\n\n".join(part for part in (title, body, url) if part)
    message.set_content(f"{text}\n\n--\nSent by your Opscend instance.\n")
    button = (
        f'<p><a href="{escape(url)}" style="background:#111;color:#fff;padding:10px 16px;'
        'text-decoration:none;font-weight:600">Open in Opscend</a></p>'
        if url
        else ""
    )
    paragraph = f'<p style="color:#444;line-height:1.5">{escape(body)}</p>' if body else ""
    message.add_alternative(
        '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
        'max-width:560px">'
        f'<h2 style="margin:0 0 12px;font-size:18px">{escape(title)}</h2>{paragraph}{button}'
        '<p style="color:#999;font-size:12px;margin-top:28px">Sent by your Opscend instance.</p>'
        "</div>",
        subtype="html",
    )
    return message


def _send_blocking(settings: Settings, message: EmailMessage) -> None:
    host, port = (settings.smtp_host or "").strip(), settings.smtp_port
    security = settings.smtp_security.strip().lower()
    try:
        if security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=SMTP_TIMEOUT, context=ssl.create_default_context()
            )
        else:
            client = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
        with client:
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password or "")
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError("The SMTP server rejected the username or password") from exc
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP error: {type(exc).__name__}") from exc
    except (OSError, ssl.SSLError) as exc:
        raise EmailError(f"Could not reach {host}:{port} ({type(exc).__name__})") from exc


async def send_email(title: str, body: str | None = None, link: str | None = None) -> None:
    settings = get_settings()
    if not settings.email_configured:
        raise EmailError(
            "Email is not configured. "
            "Set OPSCEND_SMTP_HOST, OPSCEND_EMAIL_FROM and OPSCEND_EMAIL_TO."
        )
    message = build_message(settings, title, body, link)
    await asyncio.to_thread(_send_blocking, settings, message)


async def deliver_pending() -> int:
    """Job: email every notification still waiting in the outbox. Returns how many were sent."""
    if not get_settings().email_configured:
        return 0
    sent = 0
    async with session_scope() as session:
        pending = (
            await session.scalars(
                select(Notification)
                .where(Notification.email_status == "pending")
                .order_by(Notification.created_at)
                .limit(BATCH)
            )
        ).all()
        for notification in pending:
            notification.email_attempts += 1
            try:
                await send_email(notification.title, notification.body, notification.link)
            except EmailError as exc:
                notification.email_error = str(exc)
                if notification.email_attempts >= MAX_ATTEMPTS:
                    notification.email_status = "failed"
                log.warning("email for notification %s failed: %s", notification.id, exc)
            else:
                notification.email_status, notification.email_error = "sent", None
                sent += 1
            await session.commit()
    return sent
