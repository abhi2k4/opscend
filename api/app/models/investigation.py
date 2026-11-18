"""AI investigations and the per-step trace the UI renders as spans."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base, UTCDateTime, new_id


class Investigation(Base):
    __tablename__ = "investigation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deployment.id", ondelete="CASCADE"), index=True
    )
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incident.id", ondelete="CASCADE"), index=True
    )
    service_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(128))
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    steps: Mapped[list["InvestigationStep"]] = relationship(
        order_by="InvestigationStep.index", lazy="selectin", cascade="all, delete-orphan"
    )


class InvestigationStep(Base):
    """One model turn, tool call or final report. Committed as it starts and as it ends."""

    __tablename__ = "investigation_step"
    __table_args__ = (UniqueConstraint("investigation_id", "index", name="uq_step_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigation.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(128))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tokens: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), default="running")
