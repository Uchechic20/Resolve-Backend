"""Resolve: the ticket service. Owns the state machine, permissions, audit
events and transactions for everything that happens to a ticket.
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    BusinessRuleError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.models import Ticket, TicketStatus as S, User, UserRole
from app.repositories import (
    CategoryRepository,
    CommentRepository,
    DepartmentRepository,
    EventRepository,
    TicketRepository,
    UserRepository,
)
from app.schemas import (
    CommentCreate,
    PageParams,
    TicketAssign,
    TicketCreate,
    TicketFilters,
    TicketReopen,
    TicketStatusUpdate,
    TicketTransfer,
    TicketTriage,
)
from app.services.permissions import is_admin, require_admin
from app.services.views import CommentView, TicketView

ALLOWED_TRANSITIONS: dict[S, set[S]] = {
    S.SUBMITTED: {S.TRIAGED, S.REJECTED},
    S.TRIAGED: {S.ASSIGNED},
    S.ASSIGNED: {S.IN_PROGRESS, S.TRIAGED},  # TRIAGED = via transfer
    S.IN_PROGRESS: {S.RESOLVED, S.TRIAGED},
    S.RESOLVED: {S.CLOSED, S.REOPENED},
    S.REOPENED: {S.ASSIGNED, S.IN_PROGRESS, S.TRIAGED},
    S.CLOSED: set(),  # terminal
    S.REJECTED: set(),  # terminal
}

TERMINAL = {S.CLOSED, S.REJECTED}

AGENT_TARGETS = {S.IN_PROGRESS, S.RESOLVED, S.CLOSED}  # via update_status

ASSIGNABLE = {S.TRIAGED, S.ASSIGNED, S.IN_PROGRESS, S.REOPENED}

TRANSFERABLE = {S.TRIAGED, S.ASSIGNED, S.IN_PROGRESS, S.REOPENED}


class TicketService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.tickets = TicketRepository(session)
        self.comments = CommentRepository(session)
        self.events = EventRepository(session)
        self.departments = DepartmentRepository(session)
        self.categories = CategoryRepository(session)
        self.users = UserRepository(session)

    # ---------------------------------------------------------------- helpers
    async def _lock(self, ticket_id: int) -> Ticket:
        ticket = await self.tickets.get_for_update(ticket_id)
        if ticket is None:
            raise NotFoundError("Ticket not found")
        return ticket

    async def _can_staff_access(self, actor: User, ticket: Ticket) -> bool:
        """Admins: everything. Agents: only tickets in their departments
        (so intake tickets, which have no department, are admin-only)."""
        if is_admin(actor):
            return True
        if actor.role != UserRole.AGENT or ticket.department_id is None:
            return False
        return await self.departments.is_member(actor.id, ticket.department_id)

    async def _is_head_or_admin(self, actor: User, ticket: Ticket) -> bool:
        if is_admin(actor):
            return True
        if ticket.department_id is None:
            return False
        return await self.departments.is_head(actor.id, ticket.department_id)

    async def _require_staff_access(self, actor: User, ticket: Ticket) -> None:
        if not await self._can_staff_access(actor, ticket):
            raise NotFoundError("Ticket not found")  # don't leak existence

    @staticmethod
    def _set_status(ticket: Ticket, new: S) -> S:
        """The only place status changes. Returns the old status.
        Setting the same status is a no-op (callers that must forbid
        that check explicitly)."""
        old = ticket.status
        if new == old:
            return old
        if new not in ALLOWED_TRANSITIONS[old]:
            raise InvalidTransitionError(
                f"Cannot move a ticket from '{old.value}' to '{new.value}'"
            )
        ticket.status = new
        return old

    async def _log(
            self,
            ticket_id: int,
            actor: User | None,
            event_type: str,
            from_value: str | None = None,
            to_value: str | None = None,
    ) -> None:
        await self.events.add(
            ticket_id=ticket_id,
            actor_id=actor.id if actor else None,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
        )

    async def _commit_and_view(
            self, ticket: Ticket, actor: User, staff_view: bool | None = None
    ) -> TicketView:
        """Commit, then reload for the response. Pass staff_view when the
        action itself changes the actor's access (e.g. transfer), so the
        response reflects the access they had when they were authorized."""
        staff = (
            await self._can_staff_access(actor, ticket)
            if staff_view is None
            else staff_view
        )
        await self.session.commit()
        return await self._view(ticket.id, staff)

    async def _view(self, ticket_id: int, staff_view: bool) -> TicketView:
        ticket = await self.tickets.get_detail(
            ticket_id, include_internal=staff_view, include_events=staff_view
        )
        return TicketView(ticket=ticket, staff_view=staff_view)

    async def _active_department(self, department_id: int | None):
        if department_id is None:
            raise BusinessRuleError("A department ID must be provided for this action.")
        dept = await self.departments.get(department_id)
        if dept is None:
            raise NotFoundError("Department not found")
        if not dept.is_active:
            raise BusinessRuleError("That department is not active")
        return dept

    # ------------------------------------------------------------ complainant
    async def create_ticket(self, actor: User, data: TicketCreate) -> TicketView:
        if not actor.is_verified:
            raise PermissionDeniedError("Verify your email before filing a complaint")
        if await self.categories.get(data.category_id) is None:
            raise NotFoundError("Category not found")

        ticket = await self.tickets.create(
            complainant_id=actor.id,
            category_id=data.category_id,
            title=data.title,
            description=data.description,
        )
        await self._log(ticket.id, actor, "created", to_value=ticket.reference)
        return await self._commit_and_view(ticket, actor)

    async def list_my_tickets(
            self, actor: User, params: PageParams, status: S | None = None
    ) -> tuple[list[Ticket], int]:
        return await self.tickets.list_for_complainant(
            actor.id, status=status, page=params.page, page_size=params.page_size
        )

    async def reopen(
            self, actor: User, ticket_id: int, data: TicketReopen
    ) -> TicketView:
        ticket = await self._lock(ticket_id)
        if ticket.complainant_id != actor.id:
            raise NotFoundError("Ticket not found")
        if ticket.status != S.RESOLVED:
            raise InvalidTransitionError("Only resolved tickets can be reopened")

        self._set_status(ticket, S.REOPENED)
        ticket.resolved_at = None
        await self.comments.add(
            ticket_id=ticket.id,
            author_id=actor.id,
            body=f"Reopened: {data.reason}",
            is_internal=False,
        )
        await self._log(ticket.id, actor, "reopened", S.RESOLVED.value, S.REOPENED.value)
        return await self._commit_and_view(ticket, actor)

    # ------------------------------------------------------------------ reads
    async def authorize_view(self, actor: User, ticket_id: int) -> tuple[Ticket, bool]:
        """Return (ticket, is_staff_view) or raise NotFoundError. Hidden
        tickets look missing, so ticket IDs can't be probed. Also used by
        the attachment service."""
        ticket = await self.tickets.get(ticket_id)
        if ticket is None:
            raise NotFoundError("Ticket not found")
        staff = await self._can_staff_access(actor, ticket)
        if not staff and ticket.complainant_id != actor.id:
            raise NotFoundError("Ticket not found")
        return ticket, staff

    async def get_ticket(self, actor: User, ticket_id: int) -> TicketView:
        _, staff = await self.authorize_view(actor, ticket_id)
        return await self._view(ticket_id, staff)

    async def _staff_scope(self, actor: User) -> list[int] | None:
        """None = unrestricted (admin). List = departments an agent may see."""
        if is_admin(actor):
            return None
        if actor.role != UserRole.AGENT:
            raise PermissionDeniedError("Staff access required")
        return await self.departments.department_ids_for_user(actor.id)

    async def list_staff_tickets(
            self, actor: User, filters: TicketFilters
    ) -> tuple[list[Ticket], int]:
        scope = await self._staff_scope(actor)
        if scope is not None and not scope:
            return [], 0  # agent with no departments sees nothing
        return await self.tickets.list_for_staff(
            department_ids=scope, **filters.model_dump()
        )

    async def list_intake(
            self, actor: User, params: PageParams
    ) -> tuple[list[Ticket], int]:
        require_admin(actor)
        return await self.tickets.list_intake(
            page=params.page, page_size=params.page_size
        )

    async def list_department_queue(
            self, actor: User, department_id: int, params: PageParams
    ) -> tuple[list[Ticket], int]:
        if not is_admin(actor):
            if actor.role != UserRole.AGENT or not await self.departments.is_member(
                    actor.id, department_id
            ):
                raise PermissionDeniedError("You are not a member of this department")
        return await self.tickets.list_department_queue(
            department_id, page=params.page, page_size=params.page_size
        )

    # ------------------------------------------------------------------ triage
    async def triage(
            self, actor: User, ticket_id: int, data: TicketTriage
    ) -> TicketView:
        require_admin(actor)
        ticket = await self._lock(ticket_id)
        if ticket.status != S.SUBMITTED:
            raise InvalidTransitionError("Only tickets in intake can be triaged")

        if data.reject:
            old = self._set_status(ticket, S.REJECTED)
            ticket.resolution_note = data.rejection_reason
            await self._log(ticket.id, actor, "rejected", old.value, S.REJECTED.value)
            return await self._commit_and_view(ticket, actor)

        dept = await self._active_department(data.department_id)
        if data.category_id is not None:
            if await self.categories.get(data.category_id) is None:
                raise NotFoundError("Category not found")
            ticket.category_id = data.category_id
        if data.priority is not None:
            ticket.priority = data.priority

        ticket.department_id = dept.id
        old = self._set_status(ticket, S.TRIAGED)
        await self._log(ticket.id, actor, "triaged", old.value, dept.name)
        return await self._commit_and_view(ticket, actor)

    # ------------------------------------------------------ claim / assign
    async def claim(self, actor: User, ticket_id: int) -> TicketView:
        """Agent self-assigns from their department queue. The row lock
        means if two agents claim at once, the second one gets a 409."""
        ticket = await self._lock(ticket_id)

        # FIX: Allow admins to claim, as well as agents who have access.
        if not is_admin(actor):
            if actor.role != UserRole.AGENT or not await self._can_staff_access(actor, ticket):
                raise NotFoundError("Ticket not found")

        if ticket.status != S.TRIAGED or ticket.assignee_id is not None:
            raise ConflictError("This ticket is not available to claim")

        ticket.assignee_id = actor.id
        old = self._set_status(ticket, S.ASSIGNED)
        await self._log(ticket.id, actor, "claimed", old.value, S.ASSIGNED.value)
        return await self._commit_and_view(ticket, actor)

    async def assign(
            self, actor: User, ticket_id: int, data: TicketAssign
    ) -> TicketView:
        """Department head or admin assigns/reassigns."""
        ticket = await self._lock(ticket_id)
        await self._require_staff_access(actor, ticket)
        if not await self._is_head_or_admin(actor, ticket):
            raise PermissionDeniedError("Only a department head or admin can assign")
        if ticket.status not in ASSIGNABLE:
            raise InvalidTransitionError(
                f"A '{ticket.status.value}' ticket cannot be assigned"
            )

        assignee = await self.users.get(data.assignee_id)
        if (
                assignee is None
                or not assignee.is_active
                or not await self.departments.is_member(assignee.id, ticket.department_id)
        ):
            raise BusinessRuleError("Assignee must be an active member of this department")

        previous = ticket.assignee_id
        ticket.assignee_id = assignee.id
        if ticket.status in (S.TRIAGED, S.REOPENED):
            self._set_status(ticket, S.ASSIGNED)  # IN_PROGRESS/ASSIGNED stay as-is
        await self._log(
            ticket.id,
            actor,
            "assigned",
            str(previous) if previous else None,
            str(assignee.id),
        )
        return await self._commit_and_view(ticket, actor)

    # ----------------------------------------------------------- status updates
    async def update_status(
            self, actor: User, ticket_id: int, data: TicketStatusUpdate
    ) -> TicketView:
        """Progress updates: in_progress, resolved, closed."""
        if data.status not in AGENT_TARGETS:
            raise BusinessRuleError("Use the dedicated action for that change")

        ticket = await self._lock(ticket_id)
        await self._require_staff_access(actor, ticket)
        if not (
                ticket.assignee_id == actor.id
                or await self._is_head_or_admin(actor, ticket)
        ):
            raise PermissionDeniedError(
                "Only the assignee, department head or admin can update this ticket"
            )
        if ticket.status == data.status:
            raise InvalidTransitionError(f"Ticket is already '{data.status.value}'")

        old = self._set_status(ticket, data.status)
        if data.status == S.RESOLVED:
            ticket.resolution_note = data.resolution_note
            ticket.resolved_at = datetime.now(timezone.utc)
        await self._log(ticket.id, actor, "status_changed", old.value, data.status.value)
        return await self._commit_and_view(ticket, actor)

    async def transfer(
            self, actor: User, ticket_id: int, data: TicketTransfer
    ) -> TicketView:
        """Move a ticket to another department's queue. Clears the assignee
        and sends the ticket back to 'triaged' there."""
        ticket = await self._lock(ticket_id)
        await self._require_staff_access(actor, ticket)
        if not await self._is_head_or_admin(actor, ticket):
            raise PermissionDeniedError("Only a department head or admin can transfer")
        if ticket.status not in TRANSFERABLE:
            raise InvalidTransitionError(
                f"A '{ticket.status.value}' ticket cannot be transferred"
            )
        if data.department_id == ticket.department_id:
            raise BusinessRuleError("Ticket is already in that department")

        new_dept = await self._active_department(data.department_id)
        old_dept = await self.departments.get(ticket.department_id)

        ticket.department_id = new_dept.id
        ticket.assignee_id = None
        self._set_status(ticket, S.TRIAGED)
        await self.comments.add(
            ticket_id=ticket.id,
            author_id=actor.id,
            body=f"Transferred to {new_dept.name}: {data.reason}",
            is_internal=True,
        )
        await self._log(
            ticket.id, actor, "transferred", old_dept.name if old_dept else None, new_dept.name
        )
        # The actor may no longer have access to the ticket's new department,
        # but they were authorized for this action, so answer with staff view.
        return await self._commit_and_view(ticket, actor, staff_view=True)

    # ---------------------------------------------------------------- comments
    async def add_comment(
            self, actor: User, ticket_id: int, data: CommentCreate
    ) -> CommentView:
        ticket = await self.tickets.get(ticket_id)
        if ticket is None:
            raise NotFoundError("Ticket not found")
        staff = await self._can_staff_access(actor, ticket)
        if not staff and ticket.complainant_id != actor.id:
            raise NotFoundError("Ticket not found")
        if ticket.status in TERMINAL:
            raise ConflictError("This ticket is closed to new comments")

        # Complainants can never post internal notes, whatever they send.
        is_internal = data.is_internal and staff

        comment = await self.comments.add(
            ticket_id=ticket.id,
            author_id=actor.id,
            body=data.body,
            is_internal=is_internal,
        )
        ticket.updated_at = datetime.now(timezone.utc)
        await self._log(
            ticket.id,
            actor,
            "comment_added",
            to_value="internal" if is_internal else "public",
        )
        await self.session.commit()
        await self.session.refresh(comment, ["author"])
        return CommentView(comment=comment, staff_view=staff)