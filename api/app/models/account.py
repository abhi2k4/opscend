"""The single user and the provider accounts they connect."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base, UTCDateTime, new_id


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Integration(Base):
    """One connected provider account. Secrets are stored Fernet-encrypted only."""

    __tablename__ = "integration"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    account_name: Mapped[str | None] = mapped_column(String(255))
    token_encrypted: Mapped[str] = mapped_column(Text)
    token_hint: Mapped[str] = mapped_column(String(8))
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    status_detail: Mapped[str | None] = mapped_column(Text)
    # Consecutive failed syncs. One blip is not worth an alert; a streak is.
    sync_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
