"""Resolve: return wrappers that tell the router which response schema to use."""
from dataclasses import dataclass

from app.models import Ticket, TicketComment


@dataclass
class TicketView:
    ticket: Ticket
    staff_view: bool  # True -> TicketStaffDetail, False -> TicketPublicDetail


@dataclass
class CommentView:
    comment: TicketComment
    staff_view: bool  # True -> CommentStaff, False -> CommentPublic
