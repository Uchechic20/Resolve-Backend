"""Resolve: Department, DepartmentMember and Category models."""
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import MemberRole
from app.models.user import User

if TYPE_CHECKING:
    from app.models.ticket import Ticket


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = {"extend_existing":True}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    members: Mapped[list["DepartmentMember"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="department")


class DepartmentMember(Base):
    __tablename__ = "department_members"
    __table_args__ = {"extend_existing":True}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True
    )
    member_role: Mapped[MemberRole] = mapped_column(
        enum_type(MemberRole), default=MemberRole.AGENT, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    department: Mapped[Department] = relationship(back_populates="members")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = {"extend_existing":True}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    # Hint shown to the admin during triage; does NOT auto-route.
    suggested_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL")
    )

    suggested_department: Mapped[Department | None] = relationship()
