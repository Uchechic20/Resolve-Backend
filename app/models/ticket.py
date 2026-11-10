"""Resolve: Ticket and its child tables (comments, audit events, attachments)."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.department import Category, Department
from app.models.enums import TicketPriority, TicketStatus
from app.models.user import User

# Used by the service layer to build references like RSV-2026-00123:
#   n = db.scalar(ticket_ref_seq.next_value())
ticket_ref_seq = Sequence("ticket_ref_seq", metadata=Base.metadata)


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_department_status", "department_id", "status"),
        Index("ix_tickets_complainant", "complainant_id"),
        Index("ix_tickets_assignee", "assignee_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    complainant_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    # NULL until an admin triages the ticket.
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )
    # NULL until claimed/assigned.
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[TicketPriority] = mapped_column(
        enum_type(TicketPriority), default=TicketPriority.MEDIUM, nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        enum_type(TicketStatus), default=TicketStatus.SUBMITTED, nullable=False
    )
    # Shown to the complainant when a ticket is rejected or resolved.
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    complainant: Mapped[User] = relationship(
        back_populates="tickets_filed", foreign_keys=[complainant_id]
    )
    assignee: Mapped[User | None] = relationship(
        back_populates="tickets_assigned", foreign_keys=[assignee_id]
    )
    department: Mapped[Department | None] = relationship(back_populates="tickets")
    category: Mapped[Category | None] = relationship()

    comments: Mapped[list["TicketComment"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketComment.created_at",
    )
    events: Mapped[list["TicketEvent"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketEvent.created_at",
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketComment(Base):
    __tablename__ = "ticket_comments"
    __table_args__ = (
        Index("ix_comments_ticket", "ticket_id"),
        {"extend_existing": True}
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE")
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    body: Mapped[str] = mapped_column(Text)
    # Internal notes must NEVER be returned to complainants.
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class TicketEvent(Base):
    """Append-only audit log. Write one row for every meaningful change."""
    __tablename__ = "ticket_events"
    __table_args__ = (
        Index("ix_events_ticket", "ticket_id"),
        {"extend_existing": True}
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE")
    )

    # FIXED: The string was broken with "hash()" in the middle.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Added for the audit chain
    prev_hash:Mapped[str | None]=mapped_column(String(255),nullable=True)
    hash: Mapped[str] = mapped_column(String(255), nullable=True)

    # e.g. "status_changed", "triaged", "assigned", "transferred", "comment_added"
    event_type: Mapped[str] = mapped_column(String(50))
    from_value: Mapped[str | None] = mapped_column(String(100))
    to_value: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_ticket", "ticket_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE")
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ticket: Mapped[Ticket] = relationship(back_populates="attachments")
    uploader: Mapped[User] = relationship()