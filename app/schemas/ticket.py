"""Resolve: ticket, comment, event and attachment schemas.

Two views of a ticket: *Public* (complainant) and *Staff* (agents/admins).
CommentPublic deliberately has no is_internal field.
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import TicketPriority, TicketStatus
from app.schemas.common import ORMModel, PageParams
from app.schemas.department import CategoryPublic, DepartmentBrief
from app.schemas.user import UserBrief


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    # Ignored for complainants: the service forces this to False for them.
    is_internal: bool = False


class CommentPublic(ORMModel):
    """Complainant view. Deliberately has NO is_internal field.
    The service must filter internal comments out BEFORE serializing."""
    id: int
    author: UserBrief
    body: str
    created_at: datetime


class CommentStaff(CommentPublic):
    is_internal: bool


class EventRead(ORMModel):
    id: int
    actor: UserBrief | None
    event_type: str
    from_value: str | None
    to_value: str | None
    created_at: datetime


class AttachmentRead(ORMModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class TicketCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10, max_length=10000)
    category_id: int

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class TicketPublicSummary(ORMModel):
    """Row in 'my complaints' list."""
    id: int
    reference: str
    title: str
    status: TicketStatus
    category: CategoryPublic | None
    created_at: datetime
    updated_at: datetime


class TicketPublicDetail(TicketPublicSummary):
    """Complainant detail. No assignee, no internal notes, no events,
    and department is hidden: routing is an internal concern."""
    description: str
    priority: TicketPriority
    resolution_note: str | None
    resolved_at: datetime | None
    comments: list[CommentPublic] = []
    attachments: list[AttachmentRead] = []


class TicketReopen(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class TicketStaffSummary(TicketPublicSummary):
    priority: TicketPriority
    complainant: UserBrief
    department: DepartmentBrief | None
    assignee: UserBrief | None


class TicketStaffDetail(TicketStaffSummary):
    description: str
    resolution_note: str | None
    resolved_at: datetime | None
    comments: list[CommentStaff] = []
    events: list[EventRead] = []
    attachments: list[AttachmentRead] = []


class TicketFilters(PageParams):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    department_id: int | None = None
    assignee_id: int | None = None
    category_id: int | None = None
    search: str | None = Field(None, max_length=100)
    unassigned_only: bool = False


class MyTicketFilters(PageParams):
    """Complainant's own list: pagination + optional status.
    """
    status: TicketStatus | None = None


class TicketTriage(BaseModel):
    """Admin: route a ticket out of intake. Also covers rejection."""
    department_id: int | None = None
    priority: TicketPriority | None = None
    category_id: int | None = None
    reject: bool = False
    rejection_reason: str | None = Field(None, min_length=5, max_length=2000)

    @model_validator(mode="after")
    def check_route_or_reject(self):
        if self.reject:
            if not self.rejection_reason:
                raise ValueError("rejection_reason is required when rejecting")
            if self.department_id is not None:
                raise ValueError("Cannot set a department when rejecting")
        elif self.department_id is None:
            raise ValueError("department_id is required unless rejecting")
        return self


class TicketAssign(BaseModel):
    """Dept head/admin assigns. Agents use /claim, which needs no body."""
    assignee_id: int


class TicketStatusUpdate(BaseModel):
    """Agent progress updates: in_progress, resolved, closed.
    Allowed transitions are enforced in the service, not here."""
    status: TicketStatus
    resolution_note: str | None = Field(None, min_length=5, max_length=5000)

    @model_validator(mode="after")
    def resolved_needs_note(self):
        if self.status == TicketStatus.RESOLVED and not self.resolution_note:
            raise ValueError("resolution_note is required when resolving")
        return self


class TicketTransfer(BaseModel):
    department_id: int
    reason: str = Field(min_length=5, max_length=2000)


__all__ = [
    "CommentCreate",
    "CommentPublic",
    "CommentStaff",
    "EventRead",
    "AttachmentRead",
    "TicketCreate",
    "TicketPublicSummary",
    "TicketPublicDetail",
    "TicketReopen",
    "TicketStaffSummary",
    "TicketStaffDetail",
    "TicketFilters",
    "MyTicketFilters",
    "TicketTriage",
    "TicketAssign",
    "TicketStatusUpdate",
    "TicketTransfer",
]
