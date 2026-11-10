"""Resolve: FastAPI dependencies.

Within one request FastAPI reuses the same get_db session for the current
user lookup AND the service, so everything shares one transaction scope.
Role guards here are a fast first check; services still enforce the real
rules (department membership, ownership, etc.).
"""
from typing import Annotated, AsyncIterator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession



from app.core.database import SessionLocal
from app.exceptions import PermissionDeniedError
from app.models import User, UserRole
from app.services import AdminService, AttachmentService, AuthService, TicketService
from app.services.mfa_service import MfaService

# Swagger's "Authorize" button posts a form here (see /auth/token).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


async def get_db() -> AsyncIterator[AsyncSession]:
    # Anything not committed is rolled back when the session closes.
    async with SessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---- current user & role guards -------------------------------------------
async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    return await AuthService(db).user_from_access_token(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_staff(user: CurrentUser) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.AGENT):
        raise PermissionDeniedError("Staff access required")
    return user


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Admin access required")
    return user

EnrollingUser=Annotated[User,Depends(require_staff)]
StaffUser = Annotated[User, Depends(require_staff)]
AdminUser = Annotated[User, Depends(require_admin)]


# ---- services ---------------------------------------------------------------
def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


def get_ticket_service(db: DbSession) -> TicketService:
    return TicketService(db)


def get_admin_service(db: DbSession) -> AdminService:
    return AdminService(db)


def get_attachment_service(db: DbSession) -> AttachmentService:
    return AttachmentService(db)
def get_mfa_service(db:DbSession) -> MfaService:
    return MfaService(db)


AuthSvc = Annotated[AuthService, Depends(get_auth_service)]
TicketSvc = Annotated[TicketService, Depends(get_ticket_service)]
AdminSvc = Annotated[AdminService, Depends(get_admin_service)]
AttachmentSvc = Annotated[AttachmentService, Depends(get_attachment_service)]
MfaSvc=Annotated[MfaService,Depends(get_mfa_service)]