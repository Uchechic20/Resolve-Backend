"""Resolve: access-log repository (who looked at which ticket, from where)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.request_context import get_client_ip
from app.models import AccessLog
from app.repositories.base import BaseRepository, paginate


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccessLogRepository(BaseRepository):
    async def add(
        self, *, user_id: int | None, ticket_id: int | None, action: str, detail: str | None = None
    ) -> AccessLog:
        return await self._save(
            AccessLog(
                user_id=user_id, ticket_id=ticket_id, action=action,
                detail=(detail or None) and detail[:200], ip=get_client_ip(),
            )
        )

    async def list(
        self,
        *,
        ticket_id: int | None = None,
        user_id: int | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AccessLog], int]:
        stmt = select(AccessLog).order_by(AccessLog.id.desc())
        if ticket_id is not None:
            stmt = stmt.where(AccessLog.ticket_id == ticket_id)
        if user_id is not None:
            stmt = stmt.where(AccessLog.user_id == user_id)
        if action:
            stmt = stmt.where(AccessLog.action == action)
        return await paginate(self.session, stmt, page, page_size)

    async def purge_old(self, days: int) -> int:
        cutoff = _now() - timedelta(days=days)
        result = await self.session.execute(delete(AccessLog).where(AccessLog.created_at < cutoff))
        return result.rowcount or 0