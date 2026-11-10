"""Resolve: domain exceptions.

Services raise these; they know nothing about HTTP. One exception handler
in main.py maps them to status codes (see STATUS_MAP at the bottom).
"""


class DomainError(Exception):
    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class AuthenticationError(DomainError):
    """Bad credentials or invalid/expired token."""


class PermissionDeniedError(DomainError):
    """Authenticated, but not allowed to do this."""


class NotFoundError(DomainError):
    """Missing, OR hidden from this user (we never leak existence)."""


class ConflictError(DomainError):
    """State clash: duplicate email, ticket already claimed, etc."""


class InvalidTransitionError(ConflictError):
    """Ticket status change not allowed from its current state."""


class BusinessRuleError(DomainError):
    """Input is well-formed but breaks a rule (inactive department, etc.)."""


class PayloadTooLargeError(DomainError):
    """Upload exceeds the size limit."""


class UnsupportedMediaTypeError(DomainError):
    """Upload is not an allowed file type."""


STATUS_MAP: dict[type[DomainError], int] = {
    AuthenticationError: 401,
    PermissionDeniedError: 403,
    NotFoundError: 404,
    InvalidTransitionError: 409,
    ConflictError: 409,
    BusinessRuleError: 422,
    PayloadTooLargeError: 413,
    UnsupportedMediaTypeError: 415,
}

# In main.py:
#
#   @app.exception_handler(DomainError)
#   async def domain_error_handler(request, exc: DomainError):
#       code = next(
#           (c for t, c in STATUS_MAP.items() if isinstance(exc, t)), 400
#       )
#       return JSONResponse(status_code=code, content={"detail": exc.message})
#
# STATUS_MAP is ordered most-specific first, so InvalidTransitionError
# is matched before its parent ConflictError.
