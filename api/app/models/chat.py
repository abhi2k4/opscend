"""Ask Opscend: chat sessions and their messages."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.models.base import Base, UTCDateTime, new_id


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    # Public demo only: the visitor it belongs to, so nobody reads another's questions.
    owner: Mapped[str | None] = mapped_column(String(36), index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    messages: Mapped[list["ChatMessage"]] = relationship(
        order_by="ChatMessage.index", lazy="selectin", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """A user question or an assistant answer.

    An assistant message is created `pending` next to the user message, and the
    `chat_reply` job fills it in. `steps` (the tool calls made) is committed as
    each one finishes so the UI can show progress while it polls.
    """

    __tablename__ = "chat_message"
    __table_args__ = (UniqueConstraint("session_id", "index", name="uq_chat_message_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_session.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="done")  # pending|running|done|failed
    error: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Charts the answer shows, built by the tools from stored data (never by the model).
    charts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(128))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
