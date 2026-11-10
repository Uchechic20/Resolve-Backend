"""Resolve: User model."""
from typing import TYPE_CHECKING


from sqlalchemy import Boolean, String,Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.department import DepartmentMember
    from app.models.ticket import Ticket


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = ({"extend_existing":True})

    id: Mapped[int] = mapped_column(primary_key=True,autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[UserRole] = mapped_column(
        enum_type(UserRole), default=UserRole.COMPLAINANT, nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
    token_version:Mapped[int]=mapped_column(Integer,default=0,nullable=False)
    memberships: Mapped[list["DepartmentMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tickets_filed: Mapped[list["Ticket"]] = relationship(
        back_populates="complainant", foreign_keys="Ticket.complainant_id"
    )
    tickets_assigned: Mapped[list["Ticket"]] = relationship(
        back_populates="assignee", foreign_keys="Ticket.assignee_id"
    )
