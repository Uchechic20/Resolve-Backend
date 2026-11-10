"""Resolve: user repository."""
from __future__ import annotations

from sqlalchemy import func, or_, select

from app.models import User, UserRole
from app.repositories.base import BaseRepository, paginate


class UserRepository(BaseRepository):
    async def get(self, user_id) -> User | None:
        # Safely handle None
        if user_id is None:
            return None

        # Safely extract ID if a dictionary (claims) was accidentally passed
        if isinstance(user_id, dict):
            user_id = user_id.get("sub") or user_id.get("id")

        # Force conversion to a clean integer
        try:
            clean_id = int(str(user_id).strip())
        except (ValueError, TypeError):
            return None

        return await self.session.get(User, clean_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )

    async def create(
            self,
            *,
            email: str,
            password_hash: str,
            full_name: str,
            role: UserRole = UserRole.COMPLAINANT,
    ) -> User:
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            full_name=full_name,
            role=role,
        )
        return await self._save(user)

    async def list(
            self,
            *,
            role: UserRole | None = None,
            search: str | None = None,
            page: int = 1,
            page_size: int = 20,
    ) -> tuple[list[User], int]:
        stmt = select(User).order_by(User.created_at.desc())
        if role:
            stmt = stmt.where(User.role == role)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
        return await paginate(self.session, stmt, page, page_size)