"""Resolve: shared router helpers (response shaping, pagination params)."""
from typing import Annotated

from fastapi import Query

from app.schemas import (
    CommentPublic,
    CommentStaff,
    Page,
    PageParams,
    TicketFilters,
    TicketPublicDetail,
    TicketStaffDetail,
)
from app.services import CommentView, TicketView


# Query-string params as a validated model
Pagination = Annotated[PageParams, Query()]


StaffFilters = Annotated[TicketFilters, Query()]


def ticket_response(view: TicketView) -> TicketStaffDetail | TicketPublicDetail:
    """The service says which view the caller is entitled to."""
    schema = TicketStaffDetail if view.staff_view else TicketPublicDetail
    return schema.model_validate(view.ticket)


def comment_response(view: CommentView) -> CommentStaff | CommentPublic:
    schema = CommentStaff if view.staff_view else CommentPublic
    return schema.model_validate(view.comment)


def page_of(schema, items, total: int, params: PageParams):
    return Page[schema](
        items=[schema.model_validate(i) for i in items],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


# Staff schema FIRST: the staff models are the more specific ones.
TicketOut = TicketStaffDetail | TicketPublicDetail


CommentOut = CommentStaff | CommentPublic
