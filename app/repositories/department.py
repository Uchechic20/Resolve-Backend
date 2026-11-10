"""Resolve: department, membership and category repositories."""
from __future__ import annotations

from typing import Sequence as Seq

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.models import Category, Department, DepartmentMember, MemberRole
from app.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository):
    async def get(self, department_id: int) -> Department | None:
        return await self.session.get(Department, department_id)

    async def get_by_name(self, name: str) -> Department | None:
        return await self.session.scalar(
            select(Department).where(func.lower(Department.name) == name.lower())
        )

    async def list(self, *, active_only: bool = False) -> Seq[Department]:
        stmt = select(Department).order_by(Department.name)
        if active_only:
            stmt = stmt.where(Department.is_active.is_(True))
        result = await self.session.scalars(stmt)
        return result.all()

    async def create(self, *, name: str, description: str | None = None) -> Department:
        return await self._save(Department(name=name, description=description))

    # ---- membership ----
    async def get_membership(
        self, user_id: int, department_id: int
    ) -> DepartmentMember | None:
        return await self.session.get(DepartmentMember, (user_id, department_id))

    async def add_member(
        self, *, user_id: int, department_id: int, member_role: MemberRole
    ) -> DepartmentMember:
        member = DepartmentMember(
            user_id=user_id, department_id=department_id, member_role=member_role
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def remove_member(self, member: DepartmentMember) -> None:
        await self.session.delete(member)  # AsyncSession.delete is a coroutine
        await self.session.flush()

    async def list_members(self, department_id: int) -> Seq[DepartmentMember]:
        stmt = (
            select(DepartmentMember)
            .where(DepartmentMember.department_id == department_id)
            .options(joinedload(DepartmentMember.user))
        )
        result = await self.session.scalars(stmt)
        return result.all()

    async def department_ids_for_user(self, user_id: int) -> list[int]:
        """Used to scope an agent's queues and ticket access."""
        result = await self.session.scalars(
            select(DepartmentMember.department_id).where(
                DepartmentMember.user_id == user_id
            )
        )
        return list(result.all())

    async def is_member(self, user_id: int, department_id: int) -> bool:
        return await self.get_membership(user_id, department_id) is not None

    async def is_head(self, user_id: int, department_id: int) -> bool:
        m = await self.get_membership(user_id, department_id)
        return m is not None and m.member_role == MemberRole.HEAD


class CategoryRepository(BaseRepository):
    async def get(self, category_id: int) -> Category | None:
        return await self.session.get(Category, category_id)

    async def get_by_name(self, name: str) -> Category | None:
        return await self.session.scalar(
            select(Category).where(func.lower(Category.name) == name.lower())
        )

    async def list(self) -> Seq[Category]:
        result = await self.session.scalars(select(Category).order_by(Category.name))
        return result.all()

    async def create(
        self, *, name: str, suggested_department_id: int | None = None
    ) -> Category:
        return await self._save(
            Category(name=name, suggested_department_id=suggested_department_id)
        )
