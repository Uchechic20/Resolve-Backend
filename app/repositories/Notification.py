
"""Resolve: notification outbox repository."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.models import Notification
from app.repositories.base import BaseRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NotificationRepository(BaseRepository):
    async def add(
        self, *, user_id: int, ticket_id: int | None, kind: str, subject: str, body: str
    ) -> Notification:
        return await self._save(
            Notification(
                user_id=user_id, ticket_id=ticket_id, kind=kind,
                subject=subject[:200], body=body,
            )
        )

    async def claim_pending(self, limit: int, max_attempts: int) -> list[Notification]:
        """Lock a batch for sending. SKIP LOCKED lets several workers run side by
        side without ever sending the same message twice."""
        result = await self.session.scalars(
            select(Notification)
            .where(Notification.status == "pending", Notification.attempts < max_attempts)
            .order_by(Notification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.all())

    async def count_by_status(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Notification.status, func.count()).group_by(Notification.status)
        )
        return {status: n for status, n in rows.all()}

    async def purge_old(self, days: int) -> int:
        cutoff = _now() - timedelta(days=days)
        result = await self.session.execute(
            delete(Notification).where(
                Notification.status.in_(("sent", "failed")), Notification.created_at < cutoff
            )
        )
        return result.rowcount or 0