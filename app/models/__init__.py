"""Resolve: models package.

Importing this package registers every table on Base.metadata, so Alembic
only needs:  from app.models import Base
"""
from app.models.base import Base, TimestampMixin
from app.models.department import Category, Department, DepartmentMember
from app.models.enums import MemberRole, TicketPriority, TicketStatus, UserRole
from app.models.ticket import (
    Attachment,
    Ticket,
    TicketComment,
    TicketEvent,
    ticket_ref_seq,
)
from app.models.user import User

__all__ = [
    "Attachment",
    "Base",
    "Category",
    "Department",
    "DepartmentMember",
    "MemberRole",
    "Ticket",
    "TicketComment",
    "TicketEvent",
    "TicketPriority",
    "TicketStatus",
    "TimestampMixin",
    "User",
    "UserRole",
    "ticket_ref_seq",
]
