"""Resolve: ticket, comment, event (audit log) and attachment repositories."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence as Seq

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    Attachment,
    Ticket,
    TicketComment,
    TicketEvent,
    TicketPriority,
    TicketStatus,
    ticket_ref_seq,
)
from app.core.audit_chain import compute_event_hash
from app.repositories.base import BaseRepository, paginate


class TicketRepository(BaseRepository):
    # Relationships needed to render a list row (avoids N+1 AND lazy-load errors).
    _summary_loads = (
        joinedload(Ticket.complainant),
        joinedload(Ticket.assignee),
        joinedload(Ticket.department),
        joinedload(Ticket.category),
    )

    # ---- references ----
    async def next_reference(self, year: int | None = None) -> str:
        """Concurrency-safe: uses a Postgres sequence, never max(id)+1."""
        year = year or datetime.now(timezone.utc).year
        n = await self.session.scalar(ticket_ref_seq.next_value())
        return f"RSV-{year}-{n:05d}"

    # ---- writes ----
    async def create(
        self,
        *,
        complainant_id: int,
        category_id: int,
        title: str,
        description: str,
    ) -> Ticket:
        """Returns the ticket with columns refreshed but relationships NOT
        loaded. To build a response, re-fetch with get_detail()."""
        ticket = Ticket(
            reference=await self.next_reference(),
            complainant_id=complainant_id,
            category_id=category_id,
            title=title,
            description=description,
            status=TicketStatus.SUBMITTED,
        )
        return await self._save(ticket)

    # ---- single reads ----
    async def get(self, ticket_id: int) -> Ticket | None:
        return await self.session.get(Ticket, ticket_id)

    async def get_for_update(self, ticket_id: int) -> Ticket | None:
        """Row lock. Use in state transitions so two agents can't
        claim or change the same ticket at the same moment."""
        return await self.session.scalar(
            select(Ticket).where(Ticket.id == ticket_id).with_for_update()
        )

    async def get_by_reference(self, reference: str) -> Ticket | None:
        return await self.session.scalar(
            select(Ticket).where(Ticket.reference == reference)
        )

    async def get_detail(
        self, ticket_id: int, *, include_internal: bool, include_events: bool
    ) -> Ticket | None:
        """Ticket with everything needed for a detail response.

        include_internal=False filters internal notes at the QUERY level,
        so they never even reach the serializer for complainants.
        """
        comment_rel = Ticket.comments
        if not include_internal:
            comment_rel = Ticket.comments.and_(TicketComment.is_internal.is_(False))

        options = [
            *self._summary_loads,
            selectinload(comment_rel).joinedload(TicketComment.author),
            selectinload(Ticket.attachments),
        ]
        if include_events:
            options.append(selectinload(Ticket.events).joinedload(TicketEvent.actor))

        return await self.session.scalar(
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(*options)
            # Needed if the same Ticket is already in the session (e.g. after
            # get_for_update): forces the eager loads to apply to it.
            .execution_options(populate_existing=True)
        )

    # ---- list reads ----
    async def list_for_complainant(
        self,
        complainant_id: int,
        *,
        status: TicketStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Ticket], int]:
        stmt = (
            select(Ticket)
            .where(Ticket.complainant_id == complainant_id)
            .options(joinedload(Ticket.category))
            .order_by(Ticket.created_at.desc())
        )
        if status:
            stmt = stmt.where(Ticket.status == status)
        return await paginate(self.session, stmt, page, page_size)

    async def list_for_staff(
        self,
        *,
        department_ids: list[int] | None,
        status: TicketStatus | None = None,
        priority: TicketPriority | None = None,
        department_id: int | None = None,
        assignee_id: int | None = None,
        category_id: int | None = None,
        search: str | None = None,
        unassigned_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Ticket], int]:
        """department_ids is the access scope:
        - None  -> admin, may see every ticket (including intake)
        - [...] -> agent, restricted to those departments (no intake)
        """
        stmt = select(Ticket).options(*self._summary_loads)

        if department_ids is not None:
            stmt = stmt.where(Ticket.department_id.in_(department_ids))
        if status:
            stmt = stmt.where(Ticket.status == status)
        if priority:
            stmt = stmt.where(Ticket.priority == priority)
        if department_id is not None:
            stmt = stmt.where(Ticket.department_id == department_id)
        if assignee_id is not None:
            stmt = stmt.where(Ticket.assignee_id == assignee_id)
        if category_id is not None:
            stmt = stmt.where(Ticket.category_id == category_id)
        if unassigned_only:
            stmt = stmt.where(Ticket.assignee_id.is_(None))
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(Ticket.title.ilike(like), Ticket.reference.ilike(like))
            )

        return await paginate(
            self.session, stmt.order_by(Ticket.created_at.desc()), page, page_size
        )

    async def list_intake(
        self, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Ticket], int]:
        """Admin triage queue: submitted, not yet routed. Oldest first."""
        stmt = (
            select(Ticket)
            .where(Ticket.status == TicketStatus.SUBMITTED)
            .options(*self._summary_loads)
            .order_by(Ticket.created_at.asc())
        )
        return await paginate(self.session, stmt, page, page_size)

    async def list_department_queue(
        self, department_id: int, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[Ticket], int]:
        """Triaged and not yet claimed. Oldest first."""
        stmt = (
            select(Ticket)
            .where(
                Ticket.department_id == department_id,
                Ticket.status == TicketStatus.TRIAGED,
                Ticket.assignee_id.is_(None),
            )
            .options(*self._summary_loads)
            .order_by(Ticket.created_at.asc())
        )
        return await paginate(self.session, stmt, page, page_size)

    # ---- counts (handy for dashboards later) ----
    async def count_by_status(
        self, department_id: int | None = None
    ) -> dict[TicketStatus, int]:
        stmt = select(Ticket.status, func.count()).group_by(Ticket.status)
        if department_id is not None:
            stmt = stmt.where(Ticket.department_id == department_id)
        result = await self.session.execute(stmt)
        return {status: n for status, n in result.all()}


class CommentRepository(BaseRepository):
    async def add(
        self, *, ticket_id: int, author_id: int, body: str, is_internal: bool
    ) -> TicketComment:
        """Author is not loaded on the returned object. Re-fetch via
        list_for_ticket() if you need to serialize it with its author."""
        return await self._save(
            TicketComment(
                ticket_id=ticket_id,
                author_id=author_id,
                body=body,
                is_internal=is_internal,
            )
        )

    async def list_for_ticket(
        self, ticket_id: int, *, include_internal: bool
    ) -> Seq[TicketComment]:
        stmt = (
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket_id)
            .options(joinedload(TicketComment.author))
            .order_by(TicketComment.created_at)
        )
        if not include_internal:
            stmt = stmt.where(TicketComment.is_internal.is_(False))
        result = await self.session.scalars(stmt)
        return result.all()


class EventRepository(BaseRepository):
    async def add(
        self,
        *,
        ticket_id: int,
        actor_id: int | None,
        event_type: str,
        from_value: str | None = None,
        to_value: str | None = None,
    ) -> TicketEvent:
        # One writer at a time per ticket, so the hash chain can never fork.
        await self.session.execute(
            select(Ticket.id).where(Ticket.id == ticket_id).with_for_update()
        )
        prev_hash = await self.session.scalar(
            select(TicketEvent.hash)
            .where(TicketEvent.ticket_id == ticket_id)
            .order_by(TicketEvent.id.desc())
            .limit(1)
        )
        created_at = datetime.now(timezone.utc)
        return await self._save(
            TicketEvent(
                ticket_id=ticket_id,
                actor_id=actor_id,
                event_type=event_type,
                from_value=from_value,
                to_value=to_value,
                created_at=created_at,
                prev_hash=prev_hash,
                hash=compute_event_hash(
                    prev_hash, ticket_id, actor_id, event_type, from_value, to_value, created_at
                ),
            )
        )

    async def all_for_verification(self):
        """Every event, ordered for chain verification (use for audits, not requests)."""
        result = await self.session.scalars(
            select(TicketEvent).order_by(TicketEvent.ticket_id, TicketEvent.id)
        )
        return result.all()

    async def list_for_ticket(self, ticket_id: int) -> Seq[TicketEvent]:
        stmt = (
            select(TicketEvent)
            .where(TicketEvent.ticket_id == ticket_id)
            .options(joinedload(TicketEvent.actor))
            .order_by(TicketEvent.created_at)
        )
        result = await self.session.scalars(stmt)
        return result.all()


class AttachmentRepository(BaseRepository):
    async def add(
        self,
        *,
        ticket_id: int,
        uploaded_by: int,
        filename: str,
        storage_key: str,
        content_type: str,
        size_bytes: int,
    ) -> Attachment:
        return await self._save(
            Attachment(
                ticket_id=ticket_id,
                uploaded_by=uploaded_by,
                filename=filename,
                storage_key=storage_key,
                content_type=content_type,
                size_bytes=size_bytes,
            )
        )

    async def get(self, attachment_id: int) -> Attachment | None:
        return await self.session.get(Attachment, attachment_id)

    async def count_for_ticket(self, ticket_id: int) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Attachment)
                .where(Attachment.ticket_id == ticket_id)
            )
            or 0
        )

    async def delete(self, attachment: Attachment) -> None:
        await self.session.delete(attachment)
        await self.session.flush()

    async def list_for_ticket(self, ticket_id: int) -> Seq[Attachment]:
        result = await self.session.scalars(
            select(Attachment)
            .where(Attachment.ticket_id == ticket_id)
            .order_by(Attachment.created_at)
        )
        return result.all()