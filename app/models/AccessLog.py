"""Resolve: AccessLog, a record of who looked at what."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccessLog(Base):
    """Who LOOKED at what (ticket_events records who changed things)."""

    __tablename__ = "access_logs"
    __table_args__ = (
        Index("ix_access_ticket", "ticket_id"),
        Index("ix_access_user", "user_id"),
        Index("ix_access_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(30))  # view | download | export | upload
    detail: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )