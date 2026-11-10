"""Resolve: revoked-token repository (logout, refresh rotation)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.revoked_token import RevokedToken
from app.repositories.base import BaseRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RevokedTokenRepository(BaseRepository):
    async def revoke(
        self, jti: str, user_id: int, expires_at: datetime, reason: str = "logout"
    ) -> None:

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