"""Resolve: multi-factor authentication routes."""
from fastapi import APIRouter, Request
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.dependencies import EnrollingUser,MfaSvc
from app.core.config import settings
from app.core.rate_limit import limiter

from app.schemas.mfa import (
    MfaDisable,
    MfaEnable,
    MfaLogin,
    MfaRecoveryCodes,
    MfaSetupRead,

)
from app.schemas.user import Token
mfa_router = APIRouter(prefix="/auth", tags=["mfa"])


@mfa_router.post("/login/mfa", response_model=Token)
@limiter.limit(settings.rate_limit_login)
async def login_mfa(request: Request, data: MfaLogin, svc:"MfaSvc"):
    """Finish a login that answered {"mfa_required": true, "mfa_token": ...}.
    Send the mfa_token plus either a 6-digit `code` or a one-time `recovery_code`."""
    return await svc.login(data)


@mfa_router.post("/mfa/setup", response_model=MfaSetupRead)
async def mfa_setup(user: "EnrollingUser", svc: "MfaSvc"):
    """Step 1: returns the secret and an otpauth:// link for a QR code."""
    secret, uri = await svc.setup(user)
    return MfaSetupRead(secret=secret, otpauth_uri=uri)


@mfa_router.post("/mfa/enable", response_model=MfaRecoveryCodes)
async def mfa_enable(data: MfaEnable, user: "EnrollingUser", svc: "MfaSvc"):
    """Step 2: confirm with a code from the app. Recovery codes are shown ONCE."""
    return MfaRecoveryCodes(recovery_codes=await svc.enable(user, data.code))


@mfa_router.post("/mfa/disable", response_model=Token)
@limiter.limit(settings.rate_limit_login)
async def mfa_disable(request: Request, data: MfaDisable, user: "EnrollingUser", svc: "MfaSvc"):
    """Needs the password AND a code (or recovery code). Returns fresh tokens."""
    return await svc.disable(user, data)