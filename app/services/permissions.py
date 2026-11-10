"""Resolve: small role helpers shared by services."""
from app.exceptions import PermissionDeniedError
from app.models import User, UserRole


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise PermissionDeniedError("Admin access required")
