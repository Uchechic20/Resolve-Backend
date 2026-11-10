"""Resolve: repository base class and pagination helper.

Rules for all repositories:
- Only talk to the database: no permission checks, no business rules, no
  HTTP errors (those live in services/).
- Never commit. Flush so IDs are available; the service commits once at the
  end so "change ticket + write audit event" stays atomic.

"""
from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def paginate(
    session: AsyncSession, stmt: Select, page: int, page_size: int
) -> tuple[list, int]:
    """Run a select with LIMIT/OFFSET and also return the total row count."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = await session.scalar(count_stmt) or 0
    result = await session.scalars(
        stmt.limit(page_size).offset((page - 1) * page_size)
    )
    return list(result.all()), total


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _save(self, obj):
        """Add, flush (get IDs/defaults), and refresh server-generated columns."""
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj
