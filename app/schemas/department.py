"""Resolve: department and category schemas."""
from pydantic import BaseModel, Field

from app.models import MemberRole
from app.schemas.common import ORMModel
from app.schemas.user import UserBrief


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None


class DepartmentRead(ORMModel):
    id: int
    name: str
    description: str | None
    is_active: bool


class DepartmentBrief(ORMModel):
    id: int
    name: str


class DepartmentMemberAdd(BaseModel):
    user_id: int
    member_role: MemberRole = MemberRole.AGENT


class DepartmentMemberRead(ORMModel):
    user: UserBrief
    member_role: MemberRole


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    suggested_department_id: int | None = None


class CategoryRead(ORMModel):
    id: int
    name: str
    # Staff-only hint. Not exposed in the public CategoryPublic below.
    suggested_department_id: int | None


class CategoryPublic(ORMModel):
    """What complainants see when picking a category."""
    id: int
    name: str


__all__ = [
    "DepartmentCreate",
    "DepartmentUpdate",
    "DepartmentRead",
    "DepartmentBrief",
    "DepartmentMemberAdd",
    "DepartmentMemberRead",
    "CategoryCreate",
    "CategoryRead",
    "CategoryPublic",
]
