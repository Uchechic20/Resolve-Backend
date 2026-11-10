"""Resolve: access-log schemas."""
from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel, PageParams


class AccessLogRead(ORMModel):
    id: int
    user_id: int | None
    ticket_id: int | None
    action: str  # view | download
    detail: str | None
    ip: str | None
    created_at: datetime


class AccessLogFilters(PageParams):
    ticket_id: int | None = None
    user_id: int | None = None
    action: str | None = Field(None, max_length=30)


__all__ = ["AccessLogFilters", "AccessLogRead"]