"""Resolve: auth and user schemas."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models import UserRole
from app.schemas.common import ORMModel, PageParams


class UserRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.isalpha() or v.isdigit():
            raise ValueError("Password must mix letters with numbers or symbols")
        return v


class ResendVerification(BaseModel):
    email: EmailStr


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class UserBrief(ORMModel):
    """Safe to embed anywhere (no email)."""
    id: int
    full_name: str


class UserRead(ORMModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_verified: bool
    is_active: bool
    created_at: datetime


class UserAdminUpdate(BaseModel):
    """Admin-only: change role or deactivate."""
    role: UserRole | None = None
    is_active: bool | None = None


class UserListFilters(PageParams):
    role: UserRole | None = None
    search: str | None = Field(None, max_length=100)


__all__ = [
    "UserRegister",
    "UserLogin",
    "ResendVerification",
    "Token",
    "TokenRefresh",
    "UserBrief",
    "UserRead",
    "UserAdminUpdate",
    "UserListFilters",
]
