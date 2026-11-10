"""Resolve: ticket attachments.

Safety rules enforced here:
- The file's TYPE is decided by its first bytes (magic numbers), never by
  the client-supplied filename or Content-Type header.
- Size is enforced WHILE streaming, so an oversized upload is aborted
  early instead of being fully written first.
- Only server-generated keys touch the disk (see core/storage.py).
- Same visibility rules as the ticket: complainants reach only their own.
"""
import re
from pathlib import Path
from typing import AsyncGenerator

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.storage import LocalStorage, storage as default_storage
from app.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    UnsupportedMediaTypeError,
)
from app.models import Attachment, User
from app.repositories import AttachmentRepository, EventRepository
from app.services.permissions import is_admin
from app.services.ticket_service import TERMINAL, TicketService

ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
CHUNK = 64 * 1024


def sniff_content_type(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_filename(name: str | None, fallback_ext: str) -> str:
    """Display name only. Strips any path, control characters and quotes."""
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r'[\x00-\x1f\x7f"]', "", base).strip()
    return (base or f"attachment{fallback_ext}")[:200]


class AttachmentService:
    def __init__(self, session: AsyncSession, storage: LocalStorage = default_storage):
        self.session = session
        self.storage = storage
        self.attachments = AttachmentRepository(session)
        self.events = EventRepository(session)
        self.tickets = TicketService(session)

    async def _get_for_ticket(self, ticket_id: int, attachment_id: int) -> Attachment:
        att = await self.attachments.get(attachment_id)
        if att is None or att.ticket_id != ticket_id:
            raise NotFoundError("Attachment not found")
        return att

    async def upload(self, actor: User, ticket_id: int, file: UploadFile) -> Attachment:
        ticket, _ = await self.tickets.authorize_view(actor, ticket_id)
        if ticket.status in TERMINAL:
            raise ConflictError("This ticket is closed to new attachments")
        if (
                await self.attachments.count_for_ticket(ticket.id)
                >= settings.max_attachments_per_ticket
        ):
            raise BusinessRuleError(
                f"A ticket can have at most {settings.max_attachments_per_ticket} attachments"
            )

        first = await file.read(CHUNK)
        content_type = sniff_content_type(first)
        if content_type is None:
            raise UnsupportedMediaTypeError("Only JPEG, PNG, WebP and PDF files are allowed")

        limit = settings.max_upload_bytes
        too_big = PayloadTooLargeError(f"File exceeds the {settings.max_upload_mb} MB limit")

        async def chunks():
            total = len(first)
            if total > limit:
                raise too_big
            yield first
            while chunk := await file.read(CHUNK):
                total += len(chunk)
                if total > limit:
                    raise too_big
                yield chunk

        ext = ALLOWED_TYPES[content_type]
        key = self.storage.new_key(ext)
        size = await self.storage.save(key, chunks())

        try:
            filename = clean_filename(file.filename, ext)
            att = await self.attachments.add(
                ticket_id=ticket.id,
                uploaded_by=actor.id,
                filename=filename,
                storage_key=key,
                content_type=content_type,
                size_bytes=size,
            )
            await self.events.add(
                ticket_id=ticket.id,
                actor_id=actor.id,
                event_type="attachment_added",
                to_value=filename[:100],
            )
            await self.session.commit()
        except BaseException:
            await self.storage.delete(key)  # don't leave orphan files behind
            raise
        return att

    async def get_for_download(
            self, actor: User, ticket_id: int, attachment_id: int
    ) -> tuple[Attachment, AsyncGenerator[bytes, None]]:
        """
        Returns the attachment metadata and an async generator of file bytes.
        This works for both LocalStorage and S3Storage without relying on local paths.
        """
        ticket, _ = await self.tickets.authorize_view(actor, ticket_id)
        att = await self._get_for_ticket(ticket.id, attachment_id)

        # Fetch the file stream from storage (assuming your storage adapter has a `get` or `stream` method)
        try:
            file_stream = self.storage.get(att.storage_key)
        except Exception:
            raise NotFoundError("File is no longer available")

        return att, file_stream

    async def delete(self, actor: User, ticket_id: int, attachment_id: int) -> None:
        """The uploader or an admin may remove a file, while the ticket is open."""
        ticket, _ = await self.tickets.authorize_view(actor, ticket_id)
        att = await self._get_for_ticket(ticket.id, attachment_id)
        if not (is_admin(actor) or att.uploaded_by == actor.id):
            raise PermissionDeniedError("Only the uploader or an admin can remove this file")
        if ticket.status in TERMINAL:
            raise ConflictError("This ticket is closed")

        key, filename = att.storage_key, att.filename
        await self.attachments.delete(att)
        await self.events.add(
            ticket_id=ticket.id,
            actor_id=actor.id,
            event_type="attachment_removed",
            from_value=filename[:100],
        )
        await self.session.commit()
        await self.storage.delete(key)  # after commit: DB is the source of truth