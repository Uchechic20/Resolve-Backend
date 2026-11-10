"""Resolve: RevokedToken, the list of logged-out or rotated-away tokens."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RevokedToken(Base):
    """A token that was logged out or rotated away. Rows are only needed until
    the token would have expired anyway"""

    __tablename__ = "revoked_tokens"
    __table_args__ = (Index("ix_revoked_expires", "expires_at"),)

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # "logout" = the user ended the session. "rotated" = a refresh token that was
    # exchanged for a new one; presenting it again means it was copied.
    reason: Mapped[str] = mapped_column(String(10), default="logout", server_default="logout")
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )