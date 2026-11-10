"""Resolve: repositories package (database access only)."""
from app.repositories.department import CategoryRepository, DepartmentRepository
from app.repositories.ticket import (
    AttachmentRepository,
    CommentRepository,
    EventRepository,
    TicketRepository,
)
from app.repositories.user import UserRepository

__all__ = [
    "AttachmentRepository",
    "CategoryRepository",
    "CommentRepository",
    "DepartmentRepository",
    "EventRepository",
    "TicketRepository",
    "UserRepository",
]
