"""Raw inbound events, uptime checks and incidents."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base, UTCDateTime, new_id
from app.models.catalog import Service


class RawEvent(Base):
    """Every webhook delivery and poll result, stored before it is normalized.

    `claim` carries the dedup key under a unique constraint for the first delivery
    and is NULL for later ones, so a duplicate can never be inserted as a second
    original, even by two racing requests. Duplicates are still kept (flagged) so
    the webhook inspector can show them.
    """

    __tablename__ = "raw_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(128))
    dedup_key: Mapped[str] = mapped_column(String(255), index=True)
    claim: Mapped[str | None] = mapped_column(String(255), unique=True)
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[Any] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class HealthCheck(Base):
    __tablename__ = "health_check"
    __table_args__ = (Index("ix_health_check_service_checked", "service_id", "checked_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("service.id", ondelete="CASCADE"), index=True
    )
    status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Notification(Base):
    """Something the operator should know about, shown in the console bell.

    The row is also the email outbox: `email_status` starts as "pending" when the
    event is one that gets emailed, and the delivery job moves it to "sent" or
    "failed". Writing the row in the caller's transaction and sending afterwards
    means a rolled-back event never emails, and a crash never loses one.
    """

    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    title: Mapped[str] = mapped_column(String(512))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    email_status: Mapped[str] = mapped_column(String(16), default="skipped", index=True)
    email_error: Mapped[str | None] = mapped_column(Text)
    email_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Same key = same ongoing problem; see notify_once in notifications/service.py.
    dedup_key: Mapped[str | None] = mapped_column(String(255), index=True)


class Incident(Base):
    """An open or resolved problem on one service.

    `open_slot` holds the service id while the incident is open and NULL once it is
    resolved; its unique constraint is what guarantees one open incident per service.
    `dedup_key` stops the same failed deploy from opening a second incident later.
    """

    __tablename__ = "incident"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("service.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    title: Mapped[str] = mapped_column(String(512))
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    open_slot: Mapped[str | None] = mapped_column(String(36), unique=True)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deployment.id", ondelete="SET NULL")
    )
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Memory (incidents/memory.py). The fingerprint of the failure: "" once looked at
    # and nothing usable was found, NULL while not looked at yet.
    signature: Mapped[str | None] = mapped_column(String(16), index=True)
    family: Mapped[str | None] = mapped_column(String(16), index=True)
    error_text: Mapped[str | None] = mapped_column(Text)
    # The ready deploy that resolved a deploy incident, and how it differs from the
    # failed one: "redeploy" (same commit), "rollback" (an earlier good commit) or
    # "code_change". It is the next green deploy, so a correlation, not a proof.
    resolved_by_deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deployment.id", ondelete="SET NULL")
    )
    fix_kind: Mapped[str | None] = mapped_column(String(16))

    service: Mapped[Service] = relationship(lazy="joined")


class DemoSandbox(Base):
    """One visitor's private copy of the sample data in the public demo.

    Lives in the main database only; `id` names the schema (Postgres) or file (SQLite).
    """

    __tablename__ = "demo_sandbox"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
