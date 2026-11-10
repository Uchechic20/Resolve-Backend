"""Resolve: repositories for revoked tokens, the notification outbox and access logs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.revoked_token import RevokedToken
from app.core.request_context import get_client_ip
from app.models import AccessLog, Notification, revoked_token
from app.repositories.base import BaseRepository, paginate


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RevokedTokenRepository(BaseRepository):
    async def revoke(
        self, jti: str, user_id: int, expires_at: datetime, reason: str = "logout"
    ) -> None:
        """Idempotent: revoking the same token twice is fine (the first reason stays)."""
        if not jti:
            return
        await self.session.execute(
            pg_insert(RevokedToken)
            .values(jti=jti, user_id=user_id, expires_at=expires_at, reason=reason)
            .on_conflict_do_nothing(index_elements=["jti"])
        )

    async def revocation_reason(self, jti: str) -> str | None:
        """None when the token is still good."""
        if not jti:
            return None
        return await self.session.scalar(
            select(RevokedToken.reason).where(RevokedToken.jti == jti)
        )

    async def is_revoked(self, jti: str) -> bool:
        return await self.revocation_reason(jti) is not None

    async def purge_expired(self) -> int:
        result = await self.session.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < _now())
        )
        return result.rowcount or 0


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