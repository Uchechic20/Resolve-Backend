"""Resolve: domain enums (stored as VARCHAR, not native PG enums,
which are far easier to migrate)."""
import enum


class UserRole(str, enum.Enum):
    COMPLAINANT = "complainant"
    AGENT = "agent"
    ADMIN = "admin"


class MemberRole(str, enum.Enum):
    AGENT = "agent"
    HEAD = "head"


class TicketStatus(str, enum.Enum):
    SUBMITTED = "submitted"      # in general intake queue, no department
    TRIAGED = "triaged"          # routed to a department queue
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REJECTED = "rejected"
    REOPENED = "reopened"


class TicketPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
