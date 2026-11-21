"""Services, their deployments, and the commits, diffs and logs attached to them."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base, UTCDateTime, new_id


class Service(Base):
    """A Vercel project or a Railway service."""

    __tablename__ = "service"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_service_provider_ext"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    integration_id: Mapped[str] = mapped_column(
        ForeignKey("integration.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    repo: Mapped[str | None] = mapped_column(String(255))
    health_url: Mapped[str | None] = mapped_column(String(1024))
    # Provider-specific lookup data the adapter needs again later (e.g. Railway project id).
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Deployment(Base):
    """A deploy, normalized across providers. Unique on (provider, external_id)."""

    __tablename__ = "deployment"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_deployment_provider_ext"),
        Index("ix_deployment_service_started", "service_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("service.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), index=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), index=True)
    commit_message: Mapped[str | None] = mapped_column(Text)
    commit_author: Mapped[str | None] = mapped_column(String(255))
    branch: Mapped[str | None] = mapped_column(String(255))
    environment: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    url: Mapped[str | None] = mapped_column(String(1024))

    service: Mapped[Service] = relationship(lazy="joined")


class Commit(Base):
    """A commit seen on GitHub (push webhook or poll)."""

    __tablename__ = "commit"
    __table_args__ = (UniqueConstraint("repo", "sha", name="uq_commit_repo_sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo: Mapped[str] = mapped_column(String(255), index=True)
    sha: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255), index=True)
    committed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    url: Mapped[str | None] = mapped_column(String(1024))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class CommitDiff(Base):
    """A stored commit diff: demo data, or a cache of what GitHub returned."""

    __tablename__ = "commit_diff"
    __table_args__ = (UniqueConstraint("repo", "sha", name="uq_commit_diff_repo_sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    repo: Mapped[str] = mapped_column(String(255))
    sha: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class LogLine(Base):
    """A stored log line. Its id is the stable evidence reference (`log_ab12cd34ef`)."""

    __tablename__ = "log_line"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("deployment.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    seq: Mapped[int] = mapped_column(Integer)
    # Indexed for retention pruning. On Postgres `message` also has a trigram index
    # (migration 0004) that backs ILIKE log search.
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
