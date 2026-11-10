"""Resolve: SQLAlchemy base, shared mixin and enum column helper."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def enum_type(e: type[enum.Enum]) -> SAEnum:
    return SAEnum(
        e,
        native_enum=False,
        length=20,
        values_callable=lambda x: [m.value for m in x],
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
