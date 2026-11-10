"""Resolve: ticket routes.


"""
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.core.config import settings
from app.core.rate_limit import limiter
from app.dependencies import AdminUser, CurrentUser, StaffUser, TicketSvc
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
    TicketReopen,
    TicketStaffSummary,
    TicketStatusUpdate,
    TicketTransfer,
    TicketTriage,
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
