"""Resolve: ticket routes."""
from typing import Annotated

from fastapi import APIRouter, Query, Request, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.database import get_db
from app.dependencies import AdminUser, CurrentUser, StaffUser, TicketSvc, get_current_user, require_role
from app.models.ticket import Ticket
from app.models.enums import TicketStatus
from app.models.user import User
from app.models.service_status import TicketApproval
from app.routers.helpers import (
    CommentOut,
    Pagination,
    StaffFilters,
    TicketOut,
    comment_response,
    page_of,
    ticket_response,
)
from app.schemas import (
    CommentCreate,
    MyTicketFilters,
    Page,
    TicketAssign,
    TicketCreate,
    TicketPublicSummary,
    TicketStaffSummary,
    TicketStatusUpdate,
    TicketTransfer,
    TicketTriage,
    TicketReopen,
)

tickets_router = APIRouter(prefix="/tickets", tags=["tickets"])


@tickets_router.post("", response_model=TicketOut, status_code=201)
@limiter.limit(settings.rate_limit_ticket_create)
async def create_ticket(
        request: Request, data: TicketCreate, user: CurrentUser, svc: TicketSvc
):
    return ticket_response(await svc.create_ticket(user, data))


@tickets_router.get("/mine", response_model=Page[TicketPublicSummary])
async def my_tickets(
        user: CurrentUser, svc: TicketSvc, filters: Annotated[MyTicketFilters, Query()]
):
    items, total = await svc.list_my_tickets(user, filters, filters.status)
    return page_of(TicketPublicSummary, items, total, filters)


@tickets_router.get("/intake", response_model=Page[TicketStaffSummary])
async def intake_queue(user: AdminUser, svc: TicketSvc, params: Pagination):
    """Admin triage queue: tickets not yet routed to a department."""
    items, total = await svc.list_intake(user, params)
    return page_of(TicketStaffSummary, items, total, params)


@tickets_router.get("", response_model=Page[TicketStaffSummary])
async def list_tickets(user: StaffUser, svc: TicketSvc, filters: StaffFilters):
    """Staff search/filter. Agents only ever see their own departments."""
    items, total = await svc.list_staff_tickets(user, filters)
    return page_of(TicketStaffSummary, items, total, filters)


@tickets_router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(ticket_id: int, user: CurrentUser, svc: TicketSvc):
    return ticket_response(await svc.get_ticket(user, ticket_id))


@tickets_router.post("/{ticket_id}/triage", response_model=TicketOut)
async def triage_ticket(
        ticket_id: int, data: TicketTriage, user: AdminUser, svc: TicketSvc
):
    return ticket_response(await svc.triage(user, ticket_id, data))


@tickets_router.post("/{ticket_id}/claim", response_model=TicketOut)
async def claim_ticket(ticket_id: int, user: StaffUser, svc: TicketSvc):
    return ticket_response(await svc.claim(user, ticket_id))


@tickets_router.patch("/{ticket_id}/assign", response_model=TicketOut)
async def assign_ticket(
        ticket_id: int, data: TicketAssign, user: StaffUser, svc: TicketSvc
):
    return ticket_response(await svc.assign(user, ticket_id, data))


@tickets_router.patch("/{ticket_id}/status", response_model=TicketOut)
async def update_ticket_status(
        ticket_id: int, data: TicketStatusUpdate, user: StaffUser, svc: TicketSvc
):
    return ticket_response(await svc.update_status(user, ticket_id, data))


@tickets_router.post("/{ticket_id}/transfer", response_model=TicketOut)
async def transfer_ticket(
        ticket_id: int, data: TicketTransfer, user: StaffUser, svc: TicketSvc
):
    return ticket_response(await svc.transfer(user, ticket_id, data))


@tickets_router.post("/{ticket_id}/reopen", response_model=TicketOut)
@limiter.limit(settings.rate_limit_write)
async def reopen_ticket(
        request: Request,
        ticket_id: int,
        data: TicketReopen,
        user: CurrentUser,
        svc: TicketSvc,
):
    return ticket_response(await svc.reopen(user, ticket_id, data))


@tickets_router.post(
    "/{ticket_id}/comments", response_model=CommentOut, status_code=201
)
@limiter.limit(settings.rate_limit_write)
async def add_comment(
        request: Request,
        ticket_id: int,
        data: CommentCreate,
        user: CurrentUser,
        svc: TicketSvc,
):
    return comment_response(await svc.add_comment(user, ticket_id, data))


# ==========================================
# CSAT (Satisfaction Rating) Endpoint
# ==========================================

class RatingRequest(BaseModel):
    rating: int  # 1-5
    feedback: str | None = None


@tickets_router.post("/{ticket_id}/rate")
async def rate_ticket(
        ticket_id: int,
        rating: RatingRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user),  # <--- FIX: Uses the actual function
):
    """CSAT: Complainants can rate resolved tickets."""
    stmt = select(Ticket).where(
        Ticket.id == ticket_id, Ticket.complainant_id == current_user.id
    )
    ticket = (await db.execute(stmt)).scalar_one_or_none()

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.status != TicketStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Can only rate resolved tickets")

    if not (1 <= rating.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    ticket.satisfaction_rating = rating.rating

    await db.commit()
    return {"message": "Rating submitted successfully"}


# ==========================================
# NEW: Root Cause Analysis (RCA)
# ==========================================

class RCARequest(BaseModel):
    root_cause: str


@tickets_router.post("/{ticket_id}/rca", response_model=TicketOut)
async def submit_rca(
        ticket_id: int,
        rca: RCARequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role("admin", "agent")),
):
    """Agents/Admins submit Root Cause Analysis before resolving."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # Update the ticket
    ticket.root_cause = rca.root_cause

    # Optional: Fire webhook or audit event here if you imported the functions
    # await fire_webhook(db, "ticket.rca_submitted", {"ticket_id": ticket.id})
    # await create_audit_event(db, ticket.id, current_user.id, "rca_added", "", rca.root_cause[:50])

    await db.commit()
    await db.refresh(ticket)
    return ticket_response(ticket)


# ==========================================
# NEW: Supervisor Approval System
# ==========================================

class ApprovalRequest(BaseModel):
    status: str  # 'approved' or 'rejected'
    notes: str | None = None


@tickets_router.post("/{ticket_id}/request-approval", response_model=TicketOut)
async def request_approval(
        ticket_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role("admin", "agent")),
):
    """Agent requests supervisor approval to resolve."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    ticket.requires_approval = True

    approval = TicketApproval(ticket_id=ticket_id, requested_by=current_user.id)
    db.add(approval)

    await db.commit()
    await db.refresh(ticket)
    return ticket_response(ticket)


@tickets_router.post("/{ticket_id}/approve", response_model=TicketOut)
async def approve_ticket(
        ticket_id: int,
        req: ApprovalRequest,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(require_role("admin")),  # Only admins can approve
):
    """Supervisor approves or rejects the resolution."""
    stmt = select(TicketApproval).where(TicketApproval.ticket_id == ticket_id, TicketApproval.status == "pending")
    approval = (await db.execute(stmt)).scalar_one_or_none()

    if not approval:
        raise HTTPException(404, "No pending approval found")

    approval.status = req.status
    approval.approved_by = current_user.id
    approval.notes = req.notes

    ticket = await db.get(Ticket, ticket_id)
    if req.status == "approved":
        ticket.status = TicketStatus.RESOLVED
        # await fire_webhook(db, "ticket.approved", {"ticket_id": ticket.id})

    await db.commit()
    await db.refresh(ticket)
    return ticket_response(ticket)