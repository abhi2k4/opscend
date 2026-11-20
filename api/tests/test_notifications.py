"""In-app notifications and the SMTP outbox."""

import smtplib

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.incidents import rules
from app.models import Notification
from app.notifications import email as email_module
from app.notifications.email import EmailError, build_message, deliver_pending, send_email
from app.notifications.service import notify

from .conftest import make_deployment, make_service

SMTP_ENV = {
    "OPSCEND_SMTP_HOST": "smtp.example.test",
    "OPSCEND_SMTP_USERNAME": "alerts@example.test",
    "OPSCEND_SMTP_PASSWORD": "s3cret-smtp-password",
    "OPSCEND_EMAIL_TO": "oncall@example.test",
}


class FakeSMTP:
    """Stands in for smtplib.SMTP and records what would have gone out."""

    sent: list = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None, **_):
        self.host, self.port, self.tls, self.auth = host, port, False, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, username, password):
        self.auth = (username, password)

    def send_message(self, message):
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        FakeSMTP.sent.append((self, message))


@pytest.fixture
def smtp(env, monkeypatch):
    for key, value in SMTP_ENV.items():
        env.setenv(key, value)
    get_settings.cache_clear()
    FakeSMTP.sent, FakeSMTP.fail_with = [], None
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


async def _notifications() -> list[Notification]:
    async with session_scope() as session:
        rows = await session.scalars(select(Notification).order_by(Notification.created_at))
        return list(rows.all())


async def test_failed_deploy_notifies_and_recovery_resolves(client):
    async with session_scope() as session:
        service = await make_service(session)
        failed = await make_deployment(session, service, status="failed", minutes_ago=10)
        failed_id = failed.id
        await rules.on_deployment(session, failed)
        await session.commit()

    body = (await client.get("/api/notifications")).json()
    assert body["unread"] == 1
    opened = body["items"][0]
    assert opened["kind"] == "incident_opened" and opened["severity"] == "critical"
    assert opened["link"] == f"/console/deployments/{failed_id}"
    # No SMTP configured: it stays in the console and nothing waits in the outbox.
    assert opened["email_status"] == "skipped"

    async with session_scope() as session:
        service = await session.get(type(service), service.id)
        ready = await make_deployment(session, service, status="ready", minutes_ago=1)
        await rules.on_deployment(session, ready)
        await session.commit()
    kinds = [n.kind for n in await _notifications()]
    assert kinds == ["incident_opened", "incident_resolved"]


async def test_read_state(client):
    async with session_scope() as session:
        first = notify(session, "incident_opened", "one")
        notify(session, "integration_error", "two")
        await session.commit()

    assert (await client.post(f"/api/notifications/{first.id}/read")).json()["read_at"]
    listing = (await client.get("/api/notifications", params={"unread": True})).json()
    assert listing["unread"] == 1 and [n["title"] for n in listing["items"]] == ["two"]

    assert (await client.post("/api/notifications/read-all")).status_code == 200
    assert (await client.get("/api/notifications")).json()["unread"] == 0
    assert (await client.post("/api/notifications/nope/read")).status_code == 404


async def test_notifications_require_login(anon_client):
    assert (await anon_client.get("/api/notifications")).status_code == 401
    assert (await anon_client.post("/api/notifications/test-email")).status_code == 401


async def test_outbox_emails_only_the_selected_events(client, smtp):
    async with session_scope() as session:
        notify(session, "incident_opened", "Deploy failed on api", body="boom", link="/console/x")
        notify(session, "incident_resolved", "Resolved")  # not in OPSCEND_EMAIL_EVENTS
        await session.commit()

    assert await deliver_pending() == 1
    client_used, message = smtp.sent[0]
    assert client_used.tls and client_used.auth == ("alerts@example.test", "s3cret-smtp-password")
    assert message["Subject"] == "[Opscend] Deploy failed on api"
    assert message["To"] == "oncall@example.test" and message["From"] == "alerts@example.test"
    assert "http://localhost:3000/console/x" in message.get_body(("plain",)).get_content()

    statuses = {n.title: n.email_status for n in await _notifications()}
    assert statuses == {"Deploy failed on api": "sent", "Resolved": "skipped"}
    assert await deliver_pending() == 0  # already sent: never emailed twice


async def test_outbox_retries_then_gives_up(client, smtp):
    async with session_scope() as session:
        notify(session, "incident_opened", "Deploy failed")
        await session.commit()
    smtp.fail_with = smtplib.SMTPServerDisconnected("gone")

    for _ in range(email_module.MAX_ATTEMPTS):
        assert await deliver_pending() == 0
    (row,) = await _notifications()
    assert row.email_status == "failed" and row.email_attempts == email_module.MAX_ATTEMPTS
    assert "SMTPServerDisconnected" in row.email_error


async def test_settings_and_test_email(client, smtp):
    settings = (await client.get("/api/notifications/settings")).json()
    assert settings["email"]["configured"] is True
    assert settings["email"]["host"] == "smtp.example.test"
    assert settings["email"]["to_address"] == "oncall@example.test"
    assert "incident_opened" in settings["email"]["events"]
    assert "s3cret-smtp-password" not in str(settings)

    assert (await client.post("/api/notifications/test-email")).status_code == 200
    assert smtp.sent[0][1]["Subject"] == "[Opscend] Test email"

    smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    response = await client.post("/api/notifications/test-email")
    assert response.status_code == 400
    assert "rejected the username or password" in response.json()["detail"]
    assert "s3cret-smtp-password" not in response.text


async def test_test_email_explains_missing_config(client):
    response = await client.post("/api/notifications/test-email")
    assert response.status_code == 400 and "OPSCEND_SMTP_HOST" in response.json()["detail"]
    assert (await client.get("/api/notifications/settings")).json()["email"]["configured"] is False


async def test_send_email_needs_config_and_escapes_html(env):
    with pytest.raises(EmailError, match="not configured"):
        await send_email("x")
    for key, value in SMTP_ENV.items():
        env.setenv(key, value)
    get_settings.cache_clear()
    message = build_message(get_settings(), "<b>deploy</b>", "log <script>", None)
    html = message.get_body(("html",)).get_content()
    assert "<script>" not in html and "&lt;b&gt;deploy&lt;/b&gt;" in html
